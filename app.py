import streamlit as st
import pandas as pd
import io

import sheets as sh
from parser import parse_scan_file

st.set_page_config(
    page_title="Инвентаризация",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stMetricValue"] { font-size: 2rem; font-weight: 700; }
[data-testid="stMetricLabel"] { font-size: 0.85rem; color: #aaa; }
.block-container { padding-top: 1.5rem; }
h2 { border-bottom: 1px solid #333; padding-bottom: 6px; margin-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)

PAGES = ["📊 Дашборд", "📤 Загрузить результаты", "⚙️ Инициализация данных"]
page = st.sidebar.radio("Навигация", PAGES, label_visibility="collapsed")
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Обновить данные"):
    st.cache_data.clear()
    st.rerun()


# ── DASHBOARD ──────────────────────────────────────────────────────────────────
if page == PAGES[0]:
    st.title("📦 Аналитика инвентаризации")

    with st.spinner("Загрузка данных..."):
        try:
            topology = sh.load_sheet("topology")
            products = sh.load_sheet("products")
            assignments = sh.load_sheet("assignments")
            scan = sh.load_sheet("scan_results")
        except Exception as e:
            st.error(f"Ошибка загрузки данных: {e}")
            st.info("Сначала загрузите справочники на странице ⚙️ Инициализация данных")
            st.stop()

    if topology.empty or products.empty:
        st.warning("Справочники не загружены. Перейдите в ⚙️ Инициализация данных")
        st.stop()

    # ── Normalize ──
    products["barcodes"] = products["barcodes"].astype(str).str.strip()
    products["cell_barcode"] = products["cell_barcode"].astype(str).str.strip()
    products["amount_available"] = pd.to_numeric(products["amount_available"], errors="coerce").fillna(0)
    if not scan.empty:
        scan["cell_barcode"] = scan["cell_barcode"].astype(str).str.strip()
        scan["barcode"] = scan["barcode"].astype(str).str.strip()
        scan["amount_in_location"] = pd.to_numeric(scan["amount_in_location"], errors="coerce").fillna(0)

    total_cells = len(topology)
    scanned_cells = scan["cell_barcode"].nunique() if not scan.empty else 0

    # ── Block 1: Progress ──────────────────────────────────────────────────────
    st.header("1. Прогресс инвентаризации")

    col1, col2, col3 = st.columns(3)
    col1.metric("Всего ячеек", f"{total_cells:,}")
    col2.metric("Посчитано ячеек", f"{scanned_cells:,}")
    pct_overall = scanned_cells / total_cells * 100 if total_cells > 0 else 0
    col3.metric("Выполнено", f"{pct_overall:.1f}%")

    scanned_set = set(scan["cell_barcode"].unique()) if not scan.empty else set()

    if not assignments.empty and "Ячейка" in assignments.columns and not scan.empty:
        st.subheader("По сотрудникам")
        asgn = assignments.copy()
        asgn["Ячейка"] = asgn["Ячейка"].astype(str).str.strip()

        assigned_counts = asgn.groupby("Сотрудник")["Ячейка"].count().reset_index()
        assigned_counts.columns = ["Сотрудник", "Задание"]

        scanned_set = set(scan["cell_barcode"].unique())
        asgn["посчитана"] = asgn["Ячейка"].isin(scanned_set)
        scanned_counts = asgn[asgn["посчитана"]].groupby("Сотрудник")["Ячейка"].count().reset_index()
        scanned_counts.columns = ["Сотрудник", "Посчитано"]

        emp_table = assigned_counts.merge(scanned_counts, on="Сотрудник", how="left").fillna(0)
        emp_table["Посчитано"] = emp_table["Посчитано"].astype(int)
        emp_table["% выполнения"] = (emp_table["Посчитано"] / emp_table["Задание"] * 100).round(1)
        emp_table = emp_table.sort_values("% выполнения")

        all_missed = asgn[~asgn["посчитана"]][["Сотрудник", "Ячейка"]].copy()
        if not all_missed.empty:
            buf_all = io.BytesIO()
            all_missed.to_excel(buf_all, index=False)
            st.download_button(
                "⬇️ Скачать все непосчитанные ячейки (все сотрудники)",
                data=buf_all.getvalue(),
                file_name="missed_all.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_all",
            )

        for _, emp_row in emp_table.iterrows():
            emp = emp_row["Сотрудник"]
            with st.expander(f"**{emp}** — {emp_row['% выполнения']}% ({emp_row['Посчитано']:.0f} из {emp_row['Задание']:.0f})"):
                missed = asgn[(asgn["Сотрудник"] == emp) & (~asgn["посчитана"])]["Ячейка"].tolist()
                st.write(f"Непосчитанных ячеек: {len(missed)}")
                if missed:
                    missed_df = pd.DataFrame({"Ячейка": missed})
                    buf = io.BytesIO()
                    missed_df.to_excel(buf, index=False)
                    st.download_button(
                        "⬇️ Скачать непосчитанные ячейки",
                        data=buf.getvalue(),
                        file_name=f"missed_{emp}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{emp}",
                    )
    elif assignments.empty:
        st.info("Задания сотрудников не загружены")

    st.divider()

    # ── Block 2: Cell discrepancies ────────────────────────────────────────────
    st.header("2. Расхождения по ячейкам")

    if scan.empty:
        st.info("Нет данных сканирования")
    else:
        plan = (
            products[
                products["cell_barcode"].isin(scanned_set) &
                products["barcodes"].astype(str).ne("")
            ][["cell_barcode", "barcodes", "amount_in_location"]]
            .rename(columns={"barcodes": "barcode", "amount_in_location": "plan_qty"})
            .groupby(["cell_barcode", "barcode"], as_index=False)["plan_qty"].sum()
        )
        fact = (
            scan[scan["barcode"] != ""][["cell_barcode", "barcode", "amount_in_location"]]
            .groupby(["cell_barcode", "barcode"], as_index=False)["amount_in_location"].sum()
        )

        merged_cells = plan.merge(fact, on=["cell_barcode", "barcode"], how="outer")
        merged_cells["plan_qty"] = merged_cells["plan_qty"].fillna(0)
        merged_cells["amount_in_location"] = merged_cells["amount_in_location"].fillna(0)
        merged_cells["discrepancy"] = merged_cells["plan_qty"] != merged_cells["amount_in_location"]

        scanned_only = merged_cells[merged_cells["cell_barcode"].isin(scanned_set)]
        cells_with_disc = scanned_only[scanned_only["discrepancy"]]["cell_barcode"].nunique()
        disc_rate = cells_with_disc / scanned_cells * 100 if scanned_cells > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Посчитанных ячеек", f"{scanned_cells:,}")
        col2.metric("Ячеек с расхождением", f"{cells_with_disc:,}")
        col3.metric("Доля расхождений", f"{disc_rate:.1f}%")

        with st.expander("Детализация расхождений по ячейкам"):
            disc_detail = (
                scanned_only[scanned_only["discrepancy"]]
                .merge(products[["barcodes", "name"]].rename(columns={"barcodes": "barcode"}),
                       on="barcode", how="left")
                [["cell_barcode", "barcode", "name", "plan_qty", "amount_in_location"]]
                .rename(columns={
                    "cell_barcode": "Ячейка", "barcode": "Баркод", "name": "Наименование",
                    "plan_qty": "План", "amount_in_location": "Факт",
                })
            )
            disc_detail["Разница"] = disc_detail["Факт"] - disc_detail["План"]
            st.dataframe(disc_detail, use_container_width=True, hide_index=True)

    st.divider()

    # ── Block 3: SKU discrepancies ─────────────────────────────────────────────
    st.header("3. Расхождения по SKU")

    if scan.empty:
        st.info("Нет данных сканирования")
    else:
        barcode_to_sku = (
            products[["barcodes", "SKU WMS ID", "cell_barcode"]]
            .rename(columns={"barcodes": "barcode"})
        )
        # fact: only barcodes that matched to a SKU in scanned cells
        fact_with_sku = (
            scan[scan["barcode"] != ""]
            .merge(barcode_to_sku, on="barcode", how="inner")
        )
        sku_fact = fact_with_sku.groupby("SKU WMS ID")["amount_in_location"].sum().reset_index()

        sku_plan = (
            products[products["cell_barcode"].isin(scanned_set)]
            .groupby("SKU WMS ID")["amount_in_location"].sum().reset_index()
            .rename(columns={"amount_in_location": "plan_qty"})
        )

        sku_merged = sku_plan.merge(sku_fact, on="SKU WMS ID", how="inner").fillna(0)
        sku_merged["discrepancy"] = sku_merged["plan_qty"] != sku_merged["amount_in_location"]

        total_sku = len(sku_merged)
        sku_disc = int(sku_merged["discrepancy"].sum())
        sku_disc_rate = sku_disc / total_sku * 100 if total_sku > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Всего SKU", f"{total_sku:,}")
        col2.metric("SKU с расхождением", f"{sku_disc:,}")
        col3.metric("Доля расхождений по SKU", f"{sku_disc_rate:.1f}%")

        with st.expander("Детализация по SKU"):
            sku_detail = (
                sku_merged[sku_merged["discrepancy"]]
                .merge(products[["SKU WMS ID", "name"]].drop_duplicates("SKU WMS ID"), on="SKU WMS ID", how="left")
                [["SKU WMS ID", "name", "plan_qty", "amount_in_location"]]
                .rename(columns={
                    "SKU WMS ID": "SKU", "name": "Наименование",
                    "plan_qty": "План (кол-во)", "amount_in_location": "Факт (кол-во)",
                })
            )
            sku_detail["Разница"] = sku_detail["Факт (кол-во)"] - sku_detail["План (кол-во)"]
            sku_detail = sku_detail.sort_values("Разница")
            st.dataframe(sku_detail, use_container_width=True, hide_index=True)

    st.divider()

    # ── Block 4: SKU completion ────────────────────────────────────────────────
    st.header("4. Полнота подсчёта SKU")

    if scan.empty:
        st.info("Нет данных сканирования")
    else:
        # All cells per SKU from products
        sku_all_cells = (
            products[products["barcodes"].astype(str).ne("")]
            .groupby("SKU WMS ID")["cell_barcode"]
            .apply(set).reset_index()
            .rename(columns={"cell_barcode": "plan_cells"})
        )

        # Scanned cells per SKU (via barcode match)
        b2sku = products[["barcodes", "SKU WMS ID"]].rename(columns={"barcodes": "barcode"})
        scan_sku = (
            scan[scan["barcode"] != ""]
            .merge(b2sku, on="barcode", how="inner")
            .groupby("SKU WMS ID")["cell_barcode"]
            .apply(set).reset_index()
            .rename(columns={"cell_barcode": "scanned_cells"})
        )

        sku_status = sku_all_cells.merge(scan_sku, on="SKU WMS ID", how="left")
        sku_status["scanned_cells"] = sku_status["scanned_cells"].apply(
            lambda x: x if isinstance(x, set) else set()
        )
        sku_status["all_scanned"] = sku_status.apply(
            lambda r: r["plan_cells"].issubset(scanned_set), axis=1
        )

        # Plan vs fact per SKU for scanned cells
        b2sku2 = products[["barcodes", "SKU WMS ID"]].rename(columns={"barcodes": "barcode"})

        # Plan: total amount_in_location per SKU across ALL cells
        sku_plan_qty = (
            products.groupby("SKU WMS ID")["amount_in_location"].sum().reset_index()
            .rename(columns={"amount_in_location": "План"})
        )

        # Fact: total scanned per SKU across all scanned cells
        sku_fact_qty = (
            scan[scan["barcode"] != ""]
            .merge(b2sku2, on="barcode", how="inner")
            .groupby("SKU WMS ID")["amount_in_location"].sum().reset_index()
            .rename(columns={"amount_in_location": "Факт"})
        )

        # Only fully counted SKUs (all plan cells scanned)
        fully_counted = int(sku_status["all_scanned"].sum())

        # Compare plan vs fact for fully counted SKUs only
        fully_counted_skus = sku_status[sku_status["all_scanned"]]["SKU WMS ID"]
        sku_compare = (
            sku_plan_qty[sku_plan_qty["SKU WMS ID"].isin(fully_counted_skus)]
            .merge(sku_fact_qty, on="SKU WMS ID", how="left").fillna(0)
        )
        sku_compare["Разница"] = sku_compare["Факт"] - sku_compare["План"]
        sku_compare["discrepancy"] = sku_compare["План"] != sku_compare["Факт"]
        with_disc = int(sku_compare["discrepancy"].sum())

        col1, col2 = st.columns(2)
        col1.metric("SKU подсчитано полностью", f"{fully_counted:,}")
        col2.metric("SKU с расхождениями", f"{with_disc:,}")

        disc_detail = (
            sku_compare[sku_compare["discrepancy"]]
            .merge(products[["SKU WMS ID", "name"]].drop_duplicates("SKU WMS ID"), on="SKU WMS ID", how="left")
            [["SKU WMS ID", "name", "План", "Факт", "Разница"]]
            .rename(columns={"SKU WMS ID": "SKU", "name": "Наименование"})
            .sort_values("Разница")
        )

        with st.expander(f"Детализация SKU с расхождениями ({with_disc:,})"):
            st.dataframe(disc_detail, use_container_width=True, hide_index=True)
            if not disc_detail.empty:
                buf = io.BytesIO()
                disc_detail.to_excel(buf, index=False)
                st.download_button(
                    "⬇️ Скачать расхождения по SKU",
                    data=buf.getvalue(),
                    file_name="sku_discrepancies.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


# ── UPLOAD RESULTS ─────────────────────────────────────────────────────────────
elif page == PAGES[1]:
    st.title("📤 Загрузить результаты сканирования")
    st.markdown("Загрузите Excel-файл с результатами инвентаризации (формат: Штрих-код | Кол-во | ...)")

    uploaded_files = st.file_uploader("Выберите файлы", type=["xlsx", "xls"], accept_multiple_files=True)

    if uploaded_files:
        all_records = []
        for f in uploaded_files:
            try:
                records = parse_scan_file(f)
                all_records.extend(records)
            except Exception as e:
                st.error(f"Ошибка при чтении {f.name}: {e}")

        if not all_records:
            st.warning("Файлы не содержат данных для загрузки")
            st.stop()

        new_df = pd.DataFrame(all_records)
        st.write(f"Распознано: **{new_df['cell_barcode'].nunique()}** ячеек, **{len(new_df)}** записей из {len(uploaded_files)} файлов")
        st.dataframe(new_df.head(20), use_container_width=True, hide_index=True)

        with st.spinner("Проверка дублей..."):
            existing_cells = sh.get_existing_cells()

        new_cells = set(new_df["cell_barcode"].unique())
        duplicate_cells = new_cells & existing_cells
        new_only = new_df[~new_df["cell_barcode"].isin(duplicate_cells)]

        if duplicate_cells:
            st.warning(
                f"Найдено {len(duplicate_cells)} ячеек которые уже загружены — они будут пропущены:\n"
                + ", ".join(sorted(duplicate_cells)[:10])
                + ("..." if len(duplicate_cells) > 10 else "")
            )

        if new_only.empty:
            st.info("Все ячейки уже загружены. Новых данных нет.")
            st.stop()

        st.success(f"Будет загружено: **{new_only['cell_barcode'].nunique()}** новых ячеек, **{len(new_only)}** записей")

        if st.button("✅ Загрузить в Google Sheets", type="primary"):
            rows = new_only[["cell_barcode", "barcode", "amount_in_location", "uploaded_at"]].values.tolist()
            with st.spinner("Загрузка..."):
                sh.append_rows("scan_results", rows)
            st.cache_data.clear()
            st.success("Загружено успешно!")
            st.rerun()


# ── INITIALIZATION ─────────────────────────────────────────────────────────────
elif page == PAGES[2]:
    st.title("⚙️ Инициализация данных")
    st.markdown("Загрузите базовые справочники. **Внимание: каждая загрузка полностью перезаписывает лист.**")

    with st.spinner("Создание листов..."):
        try:
            sh.ensure_sheets()
            st.success("Структура Google Sheets готова")
        except Exception as e:
            st.error(f"Ошибка: {e}")
            st.stop()

    st.divider()

    # Topology
    st.subheader("1. Топология (все ячейки склада)")
    st.caption("Файл: Топология актуальная.xlsx — лист Лист1")
    topo_file = st.file_uploader("Загрузить топологию", type=["xlsx", "xls"], key="topo")
    if topo_file and st.button("Записать топологию", key="btn_topo"):
        with st.spinner("Читаем файл..."):
            xl = pd.ExcelFile(topo_file)
            # prefer "Лист1" if exists, otherwise first sheet
            sheet = "Лист1" if "Лист1" in xl.sheet_names else xl.sheet_names[0]
            df = pd.read_excel(xl, sheet_name=sheet, header=0)
            df = df.dropna(how="all")
            # First column is always the cell barcode
            first_col = df.columns[0]
            df = df[df[first_col].astype(str).str.strip().ne("")]
            rows = df.astype(str).values.tolist()
            headers = list(df.columns)
        progress = st.progress(0, text="Запись в Google Sheets...")
        def topo_progress(done, total):
            progress.progress(done / total, text=f"Записано {done:,} из {total:,}")
        sh.bulk_write("topology", headers, rows, topo_progress)
        st.cache_data.clear()
        st.success(f"Топология загружена: {len(rows):,} ячеек")

    st.divider()

    # Products
    st.subheader("2. Справочник товаров (остатки)")
    st.caption("Файл: 20260618_065037.xlsx — якорный файл остатков")
    prod_file = st.file_uploader("Загрузить справочник товаров", type=["xlsx", "xls"], key="prod")
    if prod_file and st.button("Записать товары", key="btn_prod"):
        with st.spinner("Читаем файл..."):
            df = pd.read_excel(prod_file, sheet_name=0, header=0)
            df = df.fillna("")
            rows = df.astype(str).values.tolist()
            headers = list(df.columns)
        progress = st.progress(0, text="Запись в Google Sheets...")
        def prod_progress(done, total):
            progress.progress(done / total, text=f"Записано {done:,} из {total:,}")
        sh.bulk_write("products", headers, rows, prod_progress)
        st.cache_data.clear()
        st.success(f"Товары загружены: {len(rows):,} строк")

    st.divider()

    # Assignments
    st.subheader("3. Задания сотрудников")
    st.caption("Файл с колонками: Ячейка | Зона | Ряд | Стеллаж | Ячейка_номер | Сотрудник")
    asgn_file = st.file_uploader("Загрузить задания", type=["xlsx", "xls"], key="asgn")
    if asgn_file and st.button("Записать задания", key="btn_asgn"):
        with st.spinner("Читаем файл..."):
            xl = pd.ExcelFile(asgn_file)
            sheet = "Лист1" if "Лист1" in xl.sheet_names else xl.sheet_names[0]
            df = pd.read_excel(xl, sheet_name=sheet, header=0)
            df = df.fillna("")
            rows = df.astype(str).values.tolist()
            headers = list(df.columns)
        sh.bulk_write("assignments", headers, rows)
        st.cache_data.clear()
        st.success(f"Задания загружены: {len(rows):,} строк")

    st.divider()

    # Reset scan results
    st.subheader("4. Сбросить результаты сканирования")
    st.caption("Очищает лист scan_results. Используй с осторожностью.")
    if st.button("🗑️ Очистить scan_results", type="secondary"):
        sh.bulk_write("scan_results", sh.SHEET_HEADERS["scan_results"], [])
        st.cache_data.clear()
        st.success("Результаты очищены")
