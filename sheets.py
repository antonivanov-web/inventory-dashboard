import gspread
import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEET_HEADERS = {
    "topology": ["Ячейка", "Зона", "Ряд", "Стеллаж", "Ячейка_номер"],
    "products": [
        "index", "original_invoice_number", "zone_prefix", "cell_barcode",
        "barcode", "SKU WMS ID", "name", "barcodes", "width", "length",
        "height", "amount_available", "amount_in_location", "amount_incident",
        "ОСГ", "partner_id", "warehouse_id",
    ],
    "assignments": ["Ячейка", "Зона", "Ряд", "Стеллаж", "Ячейка_номер", "Сотрудник"],
    "scan_results": ["cell_barcode", "barcode", "amount_in_location", "uploaded_at"],
}


@st.cache_resource
def get_client():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(creds)


def get_spreadsheet():
    return get_client().open_by_key(st.secrets["sheet_id"])


def ensure_sheets():
    spreadsheet = get_spreadsheet()
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    for name, headers in SHEET_HEADERS.items():
        if name not in existing:
            ws = spreadsheet.add_worksheet(name, rows=2, cols=len(headers))
            ws.append_row(headers)
    if "Sheet1" in existing and len(existing) > 1:
        try:
            spreadsheet.del_worksheet(existing["Sheet1"])
        except Exception:
            pass


@st.cache_data(ttl=300)
def load_sheet(worksheet_name: str) -> pd.DataFrame:
    ws = get_spreadsheet().worksheet(worksheet_name)
    records = ws.get_all_records()
    return pd.DataFrame(records)


def append_rows(worksheet_name: str, rows: list[list]):
    ws = get_spreadsheet().worksheet(worksheet_name)
    ws.append_rows(rows, value_input_option="RAW")


def bulk_write(worksheet_name: str, headers: list[str], rows: list[list], progress_cb=None):
    spreadsheet = get_spreadsheet()
    try:
        ws = spreadsheet.worksheet(worksheet_name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(worksheet_name, rows=1, cols=len(headers))

    total_rows = len(rows) + 1
    ws.resize(rows=max(total_rows + 10, 10), cols=max(len(headers), 5))

    all_rows = [headers] + rows
    chunk = 3000
    for i in range(0, len(all_rows), chunk):
        batch = all_rows[i : i + chunk]
        start_row = i + 1
        ws.update(f"A{start_row}", batch, value_input_option="RAW")
        if progress_cb:
            progress_cb(min(i + chunk, len(all_rows)), len(all_rows))


def get_existing_cells(worksheet_name: str = "scan_results") -> set:
    ws = get_spreadsheet().worksheet(worksheet_name)
    values = ws.col_values(1)
    return set(values[1:]) if len(values) > 1 else set()
