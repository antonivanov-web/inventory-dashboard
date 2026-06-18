import pandas as pd
import re
from datetime import datetime, timezone


CELL_RE = re.compile(r'[A-Za-z]')


def is_cell_barcode(code: str) -> bool:
    return bool(CELL_RE.search(code))


def parse_scan_file(file) -> list[dict]:
    df = pd.read_excel(file, header=0)
    barcode_col = df.columns[0]
    qty_col = df.columns[1]

    results = []
    current_cell = None
    product_buffer: dict[str, int] = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for _, row in df.iterrows():
        code = str(row[barcode_col]).strip()
        if code in ("nan", "", "None"):
            continue

        try:
            qty = int(float(row[qty_col])) if pd.notna(row[qty_col]) else 1
        except (ValueError, TypeError):
            qty = 1

        if is_cell_barcode(code):
            if current_cell is not None:
                _flush(results, current_cell, product_buffer, now)
            current_cell = code
            product_buffer = {}
        else:
            if current_cell is not None:
                product_buffer[code] = product_buffer.get(code, 0) + qty

    if current_cell is not None:
        _flush(results, current_cell, product_buffer, now)

    return results


def _flush(results: list, cell: str, products: dict, now: str):
    if products:
        for barcode, amt in products.items():
            results.append({
                "cell_barcode": cell,
                "barcode": barcode,
                "amount_in_location": amt,
                "uploaded_at": now,
            })
    else:
        results.append({
            "cell_barcode": cell,
            "barcode": "",
            "amount_in_location": 0,
            "uploaded_at": now,
        })
