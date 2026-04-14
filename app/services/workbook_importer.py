from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config.workbook_schema import SUPPORTED_SHEETS
from app.db import connect_sqlite
from app.services.workbook_reader import WorkbookSheet, read_workbook_sheet_map


DATE_FIELDS = {
    "Date Aquired",
    "Date Listed",
    "Date Sold",
    "Date Won",
    "Collection Date",
    "Date",
    "scheduled_date",
    "completed_date",
}

NUMERIC_FIELDS = {
    "Cars Sold",
    "Total Revenue",
    "Total Gross Profit",
    "Company Expenses",
    "Total SA Gross Profit",
    "Investor Expense",
    "Company Fuel Costs",
    "Other Money In",
    "Other Money Out",
    "Net Profit Exc Investor",
    "Net Exc Investor",
    "Total Cost",
    "Sold",
    "Part Ex",
    "SA/Investor Profit Share",
    "Total Profit",
    "Investor Profit",
    "SA Profit",
    "Days to Sell",
    "PX Value",
    "Price",
    "Reconditioning costs",
    "Sale Price",
    "Amount",
    "Amount ",
    "Initial Balance",
    "Capital Returned",
    "Total Balance",
    "Purchased",
    "Total Profit (since Nov-25)",
    "Available",
}

PLATE_FIELDS = {"Number Plate reference", "Plate Number", "Reg"}
PLATE_PATTERN = re.compile(r"[A-Z]{1,3}\d{1,4}[A-Z]{0,3}")
UK_PLATE_PATTERN = re.compile(r"[A-Z]{2}\d{2}[A-Z]{3}")
STOCK_ID_PREFIX = "STK"


@dataclass
class ImportSummary:
    workbook_path: str
    vehicles_created: int = 0
    investors_created: int = 0
    allocations_created: int = 0
    vehicle_expenses_created: int = 0
    collection_jobs_created: int = 0
    money_movements_created: int = 0
    sync_run_id: int | None = None
    preserved_links_restored: dict[str, int] | None = None
    validation: dict[str, Any] | None = None


def normalize_text(value: Any) -> str:
    return str(value or "").strip()


def record_value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return ""


def normalize_plate(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value).upper())


def extract_plate_candidate(value: Any) -> str:
    text = normalize_text(value).upper()
    direct = normalize_plate(text)
    if direct in {"", "CARD", "CASH"}:
        direct = ""
    if direct and len(direct) >= 5:
        return direct

    matches = re.findall(r"[A-Z0-9]{2,4}\s?[A-Z0-9]{2,4}\s?[A-Z0-9]{0,3}", text)
    for match in matches:
        candidate = normalize_plate(match)
        if len(candidate) >= 5 and any(char.isdigit() for char in candidate):
            return candidate
    return ""


def normalize_model(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_text(value))


def parse_decimal(value: Any) -> float:
    text = normalize_text(value).replace(",", "")
    if not text:
        return 0.0
    try:
        return round(float(text), 2)
    except ValueError:
        return 0.0


def relink_preserved_records(connection: Any) -> dict[str, int]:
    restored = {
        "service_records": 0,
        "viewings": 0,
        "fines": 0,
        "receipts": 0,
        "document_files": 0,
    }

    updates = {
        "service_records": ("plate", "vehicle_id", True),
        "viewings": ("vehicle_plate", "vehicle_id", True),
        "fines": ("plate", "vehicle_id", True),
        "receipts": ("plate", "vehicle_id", False),
    }
    for table_name, (plate_column, vehicle_column, has_updated_at) in updates.items():
        set_updated_at = ", updated_at = CURRENT_TIMESTAMP" if has_updated_at else ""
        cursor = connection.execute(
            f"""
            UPDATE {table_name}
            SET {vehicle_column} = (
                SELECT v.id
                FROM vehicles v
                WHERE v.plate_normalized = REPLACE(REPLACE(UPPER(COALESCE({table_name}.{plate_column}, '')), ' ', ''), '-', '')
                ORDER BY CASE WHEN v.status = 'In Stock' THEN 0 ELSE 1 END, v.id DESC
                LIMIT 1
            ){set_updated_at}
            WHERE {vehicle_column} IS NULL
              AND TRIM(COALESCE({plate_column}, '')) != ''
            """
        )
        restored[table_name] = int(cursor.rowcount or 0)

    doc_cursor = connection.execute(
        """
        UPDATE document_files
        SET vehicle_id = (
            SELECT v.id
            FROM vehicles v
            WHERE v.stock_id = document_files.stock_id
            LIMIT 1
        )
        WHERE vehicle_id IS NULL
          AND TRIM(COALESCE(stock_id, '')) != ''
        """
    )
    restored["document_files"] = int(doc_cursor.rowcount or 0)
    return restored


def snapshot_invoices(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            invoice_type,
            invoice_number,
            invoice_date,
            customer_name,
            contact_info,
            warranty,
            autoguard_number,
            stock_id,
            amount_total,
            profit_total,
            investor_profit_amount,
            company_profit_amount,
            html_snapshot,
            file_path
        FROM invoices
        ORDER BY id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def restore_preserved_invoices(
    connection: Any,
    preserved_invoices: list[dict[str, Any]],
    validation: dict[str, Any],
) -> int:
    restored_count = 0
    for invoice in preserved_invoices:
        stock_id = normalize_text(invoice.get("stock_id"))
        invoice_number = normalize_text(invoice.get("invoice_number"))
        if not stock_id or not invoice_number:
            continue

        vehicle = connection.execute(
            "SELECT id FROM vehicles WHERE stock_id = ? LIMIT 1",
            (stock_id,),
        ).fetchone()
        if vehicle is None:
            validation.setdefault("unmatched_preserved_invoices", []).append(invoice_number)
            continue

        existing = connection.execute(
            "SELECT id FROM invoices WHERE invoice_number = ? LIMIT 1",
            (invoice_number,),
        ).fetchone()
        if existing is not None:
            continue

        connection.execute(
            """
            INSERT INTO invoices (
                vehicle_id,
                invoice_type,
                invoice_number,
                invoice_date,
                customer_name,
                contact_info,
                warranty,
                autoguard_number,
                stock_id,
                amount_total,
                profit_total,
                investor_profit_amount,
                company_profit_amount,
                html_snapshot,
                file_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(vehicle["id"]),
                invoice.get("invoice_type") or "investor_sale",
                invoice_number,
                invoice.get("invoice_date") or "",
                invoice.get("customer_name") or "",
                invoice.get("contact_info") or "",
                invoice.get("warranty") or "",
                invoice.get("autoguard_number") or "",
                stock_id,
                parse_decimal(invoice.get("amount_total")),
                parse_decimal(invoice.get("profit_total")),
                parse_decimal(invoice.get("investor_profit_amount")),
                parse_decimal(invoice.get("company_profit_amount")),
                invoice.get("html_snapshot") or "",
                invoice.get("file_path") or "",
            ),
        )
        restored_count += 1

    connection.execute(
        """
        UPDATE document_files
        SET invoice_id = (
            SELECT i.id
            FROM invoices i
            WHERE i.stock_id = document_files.stock_id
              AND (
                document_files.stored_name = i.invoice_number || '.html'
                OR document_files.original_name = i.invoice_number || '.html'
                OR document_files.relative_path LIKE '%' || i.invoice_number || '.html'
              )
            LIMIT 1
        ),
            entity_id = COALESCE(
                (
                    SELECT i.invoice_number
                    FROM invoices i
                    WHERE i.stock_id = document_files.stock_id
                      AND (
                        document_files.stored_name = i.invoice_number || '.html'
                        OR document_files.original_name = i.invoice_number || '.html'
                        OR document_files.relative_path LIKE '%' || i.invoice_number || '.html'
                      )
                    LIMIT 1
                ),
                entity_id
            )
        WHERE entity_type = 'invoice'
        """
    )
    return restored_count


def parse_excel_date(value: Any) -> str | None:
    text = normalize_text(value)
    if not text:
        return None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue

    if re.fullmatch(r"\d+(\.\d+)?", text):
        serial = float(text)
        if 30000 <= serial <= 60000:
            base = datetime(1899, 12, 30)
            return (base + timedelta(days=serial)).date().isoformat()

    return text


def split_make_model(display_name: str) -> tuple[str | None, str]:
    normalized = normalize_model(display_name)
    if not normalized:
        return None, ""
    parts = normalized.split(" ", 1)
    if len(parts) == 1:
        return parts[0], parts[0]
    return parts[0], normalized


def is_probable_vehicle_row(record: dict[str, Any], source_sheet: str) -> bool:
    plate = normalize_plate(record_value(record, "Number Plate reference", "Plate Number"))
    model = normalize_model(record_value(record, "Make & Model"))
    total_cost = parse_decimal(record_value(record, "Total Cost"))
    sold_price = parse_decimal(record_value(record, "Sold"))
    purchase_price = parse_decimal(record_value(record, "Price"))
    date_acquired = parse_excel_date(record_value(record, "Date Aquired"))
    month = parse_excel_date(record_value(record, "Month")) or normalize_text(record_value(record, "Month"))

    if not plate and not model:
        return False
    if plate and len(plate) < 5 and not model:
        return False
    if not any([total_cost, sold_price, purchase_price, date_acquired, month]):
        return False
    return True


def is_probable_investor_row(record: dict[str, Any]) -> bool:
    name = normalize_text(record_value(record, "Investors"))
    if not name:
        return False
    if not any(
        [
            parse_decimal(record_value(record, "Initial Balance")),
            parse_decimal(record_value(record, "Total Balance")),
            parse_decimal(record_value(record, "Purchased")),
            parse_decimal(record_value(record, "Available")),
        ]
    ):
        return False
    return True


def is_probable_collection_row(record: dict[str, Any]) -> bool:
    return bool(normalize_plate(record_value(record, "Plate Number")) or normalize_model(record_value(record, "Make & Model")))


def is_probable_expense_row(record: dict[str, Any], amount_field: str) -> bool:
    amount = parse_decimal(record_value(record, amount_field, amount_field.strip()))
    if amount <= 0:
        return False
    category = normalize_text(record_value(record, "Category"))
    if category.lower().startswith("total "):
        return False
    text_blob = " ".join(
        normalize_text(record_value(record, field, field.strip()))
        for field in ("Category", "Notes", "Reason", "From", "Cost Incurred on", "Reg", "Car")
    ).strip()
    return bool(text_blob)


def derive_vehicle_status(source_sheet: str, raw_status: str, sold_price: float) -> tuple[str, str]:
    normalized_status = normalize_text(raw_status)
    lower_status = normalized_status.lower()

    if source_sheet == "Sold Stock" or sold_price > 0 and "sold" in lower_status:
        return "Sold", ""
    if any(token in lower_status for token in ("live", "on sale", "listed")):
        return "Live", normalized_status if normalized_status.lower() != "live" else ""
    if "sold" in lower_status:
        return "Sold", ""
    if normalized_status:
        return "In Stock", normalized_status
    return "In Stock", ""


def clean_header_row(row: list[str]) -> list[str]:
    return [normalize_text(cell) for cell in row]


def detect_header_index(rows: list[list[str]], expected_headers: list[str]) -> int | None:
    expected = {header.strip() for header in expected_headers}
    best_match_index = None
    best_match_count = 0
    for index, row in enumerate(rows[:10]):
        row_headers = {cell for cell in clean_header_row(row) if cell}
        match_count = len(row_headers & expected)
        if match_count > best_match_count:
            best_match_count = match_count
            best_match_index = index
    return best_match_index if best_match_count >= 2 else None


def build_rows_from_sheet(sheet: WorkbookSheet, expected_headers: list[str]) -> list[dict[str, Any]]:
    header_index = detect_header_index(sheet.rows, expected_headers)
    if header_index is None:
        return []

    raw_headers = clean_header_row(sheet.rows[header_index])
    rows: list[dict[str, Any]] = []
    for row_offset, row in enumerate(sheet.rows[header_index + 1 :], start=header_index + 2):
        if not any(normalize_text(cell) for cell in row):
            continue

        record: dict[str, Any] = {}
        for cell_index, header in enumerate(raw_headers):
            if not header:
                continue
            record[header] = normalize_text(row[cell_index]) if cell_index < len(row) else ""
        record["_sheet_name"] = sheet.name
        record["_row_ref"] = f"{sheet.name}:{row_offset}"
        rows.append(record)
    return rows


def build_workbook_rows(sheet_map: dict[str, WorkbookSheet]) -> dict[str, list[dict[str, Any]]]:
    workbook_rows: dict[str, list[dict[str, Any]]] = {}
    for sheet_name, expected_headers in SUPPORTED_SHEETS.items():
        sheet = sheet_map.get(sheet_name)
        if sheet is None:
            workbook_rows[sheet_name] = []
            continue
        workbook_rows[sheet_name] = build_rows_from_sheet(sheet, expected_headers)
    return workbook_rows


def normalize_vehicle_row(record: dict[str, Any], source_sheet: str) -> dict[str, Any]:
    plate = record_value(record, "Number Plate reference", "Plate Number") or ""
    model = record_value(record, "Make & Model") or ""
    date_acquired = parse_excel_date(record_value(record, "Date Aquired"))
    date_sold = parse_excel_date(record_value(record, "Date Sold"))
    month = parse_excel_date(record_value(record, "Month")) or record_value(record, "Month") or ""
    sold_price = parse_decimal(record_value(record, "Sold"))
    status, derived_notes = derive_vehicle_status(source_sheet, record_value(record, "Status") or "", sold_price)
    source = record_value(record, "Source") or ""
    display_name = normalize_model(model or plate or "Unknown Vehicle")

    return {
        "source_sheet": source_sheet,
        "row_ref": record["_row_ref"],
        "plate": normalize_text(plate).upper(),
        "plate_normalized": normalize_plate(plate),
        "model": display_name,
        "make": split_make_model(display_name)[0],
        "display_name": display_name,
        "status": status,
        "source": normalize_text(source),
        "date_acquired": date_acquired,
        "date_listed": parse_excel_date(record_value(record, "Date Listed")),
        "date_sold": date_sold,
        "month": month,
        "purchase_price": parse_decimal(record_value(record, "Price")),
        "px_value": parse_decimal(record_value(record, "PX Value", "Part Ex")),
        "reconditioning_costs": parse_decimal(record_value(record, "Reconditioning costs")),
        "total_cost": parse_decimal(record_value(record, "Total Cost")),
        "sold_price": sold_price,
        "profit_total": parse_decimal(record_value(record, "Total Profit", "Profit")),
        "platform": normalize_text(record_value(record, "Platfrom")),
        "investor_name": normalize_text(record_value(record, "SA/Investor Name", "Investor/SA")),
        "invoice_number": normalize_text(record_value(record, "Invoice Number")),
        "customer_name": normalize_text(record_value(record, "Customer Name")),
        "contact_info": normalize_text(record_value(record, "Contact info")),
        "warranty": normalize_text(record_value(record, "Warranty")),
        "autoguard_number": normalize_text(record_value(record, "AutoGuard Number")),
        "notes": normalize_text(record_value(record, "Notes") or derived_notes),
    }


def vehicle_fingerprint(vehicle: dict[str, Any]) -> str:
    parts = [
        vehicle.get("plate_normalized") or "",
        normalize_model(vehicle.get("display_name")),
        vehicle.get("date_acquired") or "",
        vehicle.get("date_sold") or "",
        vehicle.get("month") or "" if not vehicle.get("date_acquired") and not vehicle.get("date_sold") else "",
    ]
    return "|".join(parts)


def generate_stock_id(fingerprint: str) -> str:
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest().upper()[:10]
    return f"{STOCK_ID_PREFIX}-{digest}"


def pick_detail_sheet_vehicle(
    sheet_name: str,
    vehicles_by_plate: dict[str, list[dict[str, Any]]],
    vehicles_by_stock_id: dict[str, dict[str, Any]],
) -> str | None:
    normalized_sheet = normalize_plate(sheet_name)
    possible_matches = []

    for plate, vehicles in vehicles_by_plate.items():
        if plate and plate in normalized_sheet:
            possible_matches.extend(vehicles)

    if len(possible_matches) == 1:
        return possible_matches[0]["stock_id"]

    exact_plate_matches = [vehicle for vehicle in possible_matches if vehicle["plate_normalized"] == normalized_sheet]
    if len(exact_plate_matches) == 1:
        return exact_plate_matches[0]["stock_id"]

    sheet_label = normalize_model(sheet_name).lower()
    display_matches = [
        vehicle for vehicle in vehicles_by_stock_id.values() if normalize_model(vehicle["display_name"]).lower() in sheet_label
    ]
    if len(display_matches) == 1:
        return display_matches[0]["stock_id"]

    return None


def parse_detail_sheet_expenses(
    sheet: WorkbookSheet,
    vehicles_by_plate: dict[str, list[dict[str, Any]]],
    vehicles_by_stock_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    if sheet.name in SUPPORTED_SHEETS:
        return [], None

    stock_id = pick_detail_sheet_vehicle(sheet.name, vehicles_by_plate, vehicles_by_stock_id)
    if not stock_id:
        return [], None

    expenses: list[dict[str, Any]] = []
    skip_labels = {"item", "price", "car price", "brought", "px", "px value", "part ex value", "sold for", "profit / loss", "profit", ""}
    for row_index, row in enumerate(sheet.rows[:50], start=1):
        item = normalize_model(row[0]) if len(row) > 0 else ""
        amount_text = normalize_text(row[1]) if len(row) > 1 else ""
        if item.lower() in skip_labels:
            continue
        amount = parse_decimal(amount_text)
        if not item or amount == 0:
            continue

        expenses.append(
            {
                "stock_id": stock_id,
                "expense_scope": "detail_sheet",
                "expense_type": "vehicle_detail",
                "category": item,
                "description": item,
                "vendor": "",
                "amount": amount,
                "payment_method": "",
                "paid_by": "",
                "expense_date": None,
                "source_sheet": sheet.name,
                "source_row_ref": f"{sheet.name}:{row_index}",
                "workbook_detail_sheet": sheet.name,
                "notes": "",
            }
        )
    return expenses, stock_id


def import_workbook_to_database(db_path: Path, workbook_path: Path) -> ImportSummary:
    summary = ImportSummary(workbook_path=str(workbook_path), validation={})
    sheet_map = read_workbook_sheet_map(workbook_path)
    workbook_rows = build_workbook_rows(sheet_map)

    stock_rows = [
        normalize_vehicle_row(row, "Stock Data")
        for row in workbook_rows.get("Stock Data", [])
        if is_probable_vehicle_row(row, "Stock Data")
    ]
    sold_rows = [
        normalize_vehicle_row(row, "Sold Stock")
        for row in workbook_rows.get("Sold Stock", [])
        if is_probable_vehicle_row(row, "Sold Stock")
    ]

    all_vehicle_rows = stock_rows + sold_rows
    vehicles_by_fingerprint: dict[str, dict[str, Any]] = {}
    duplicate_plate_counter = Counter(row["plate_normalized"] for row in all_vehicle_rows if row["plate_normalized"])

    validation = {
        "duplicate_plate_candidates": sorted([plate for plate, count in duplicate_plate_counter.items() if count > 1]),
        "unmatched_detail_sheets": [],
        "ambiguous_vehicle_links": [],
        "sheets_missing_headers": [],
        "unmatched_preserved_invoices": [],
    }

    for row in all_vehicle_rows:
        fingerprint = vehicle_fingerprint(row)
        stock_id = generate_stock_id(fingerprint)
        merged = vehicles_by_fingerprint.get(fingerprint)
        if merged is None:
            row["stock_id"] = stock_id
            vehicles_by_fingerprint[fingerprint] = row
            continue

        for field in (
            "status",
            "source",
            "date_listed",
            "date_sold",
            "purchase_price",
            "px_value",
            "reconditioning_costs",
            "total_cost",
            "sold_price",
            "profit_total",
            "platform",
            "investor_name",
            "invoice_number",
            "customer_name",
            "contact_info",
            "warranty",
            "autoguard_number",
            "notes",
        ):
            if not merged.get(field) and row.get(field):
                merged[field] = row[field]

    vehicles = list(vehicles_by_fingerprint.values())
    vehicles_by_stock_id = {vehicle["stock_id"]: vehicle for vehicle in vehicles}
    vehicles_by_plate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vehicle in vehicles:
        if vehicle["plate_normalized"]:
            vehicles_by_plate[vehicle["plate_normalized"]].append(vehicle)

    investor_rows = workbook_rows.get("Investor Budget", [])
    investors = []
    for row in investor_rows:
        name = normalize_text(record_value(row, "Investors"))
        if not is_probable_investor_row(row):
            continue
        investors.append(
            {
                "name": name,
                "initial_balance": parse_decimal(record_value(row, "Initial Balance")),
                "capital_returned": parse_decimal(record_value(row, "Capital Returned")),
                "total_balance_cached": parse_decimal(record_value(row, "Total Balance")),
                "purchased_total_cached": parse_decimal(record_value(row, "Purchased")),
                "profit_total_cached": parse_decimal(record_value(row, "Total Profit (since Nov-25)")),
                "available_balance_cached": parse_decimal(record_value(row, "Available")),
                "workbook_primary_sheet": "Investor Budget",
                "workbook_row_ref": row["_row_ref"],
            }
        )

    with connect_sqlite(db_path) as connection:
        preserved_invoices = snapshot_invoices(connection)
        sync_run_id = connection.execute(
            """
            INSERT INTO workbook_sync_runs (direction, status, source_path)
            VALUES ('import', 'running', ?)
            """,
            (str(workbook_path),),
        ).lastrowid
        summary.sync_run_id = sync_run_id

        for table_name in (
            "vehicle_expenses",
            "vehicle_investor_allocations",
            "collections_deliveries",
            "money_movements",
            "investors",
            "vehicles",
        ):
            connection.execute(f"DELETE FROM {table_name}")

        vehicle_id_map: dict[str, int] = {}
        for vehicle in vehicles:
            cursor = connection.execute(
                """
                INSERT INTO vehicles (
                    stock_id,
                    plate,
                    plate_normalized,
                    make,
                    model,
                    display_name,
                    status,
                    source,
                    date_acquired,
                    date_listed,
                    date_sold,
                    purchase_price,
                    px_value,
                    reconditioning_costs,
                    total_cost_cached,
                    sold_price,
                    profit_total_cached,
                    customer_name,
                    contact_info,
                    warranty,
                    autoguard_number,
                    platform,
                    invoice_number,
                    notes,
                    workbook_primary_sheet,
                    workbook_row_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle["stock_id"],
                    vehicle["plate"],
                    vehicle["plate_normalized"],
                    vehicle["make"],
                    vehicle["model"],
                    vehicle["display_name"],
                    vehicle["status"],
                    vehicle["source"],
                    vehicle["date_acquired"],
                    vehicle["date_listed"],
                    vehicle["date_sold"],
                    vehicle["purchase_price"],
                    vehicle["px_value"],
                    vehicle["reconditioning_costs"],
                    vehicle["total_cost"],
                    vehicle["sold_price"],
                    vehicle["profit_total"],
                    vehicle["customer_name"],
                    vehicle["contact_info"],
                    vehicle["warranty"],
                    vehicle["autoguard_number"],
                    vehicle["platform"],
                    vehicle["invoice_number"],
                    vehicle["notes"],
                    vehicle["source_sheet"],
                    vehicle["row_ref"],
                ),
            )
            vehicle_id_map[vehicle["stock_id"]] = int(cursor.lastrowid)
        summary.vehicles_created = len(vehicle_id_map)

        investor_id_map: dict[str, int] = {}
        for investor in investors:
            cursor = connection.execute(
                """
                INSERT INTO investors (
                    name,
                    initial_balance,
                    capital_returned,
                    total_balance_cached,
                    purchased_total_cached,
                    profit_total_cached,
                    available_balance_cached,
                    workbook_primary_sheet,
                    workbook_row_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    investor["name"],
                    investor["initial_balance"],
                    investor["capital_returned"],
                    investor["total_balance_cached"],
                    investor["purchased_total_cached"],
                    investor["profit_total_cached"],
                    investor["available_balance_cached"],
                    investor["workbook_primary_sheet"],
                    investor["workbook_row_ref"],
                ),
            )
            investor_id_map[investor["name"].lower()] = int(cursor.lastrowid)
        summary.investors_created = len(investor_id_map)

        for vehicle in vehicles:
            investor_name = normalize_text(vehicle.get("investor_name"))
            if not investor_name or investor_name.upper() == "SA":
                continue
            investor_id = investor_id_map.get(investor_name.lower())
            if not investor_id:
                validation["ambiguous_vehicle_links"].append(
                    {
                        "type": "missing_investor",
                        "stock_id": vehicle["stock_id"],
                        "investor_name": investor_name,
                    }
                )
                continue

            cursor = connection.execute(
                """
                INSERT INTO vehicle_investor_allocations (
                    vehicle_id,
                    investor_id,
                    allocation_role,
                    capital_amount,
                    profit_share_percent,
                    investor_profit_amount,
                    company_profit_amount,
                    notes
                ) VALUES (?, ?, 'primary', ?, 0, 0, 0, ?)
                """,
                (
                    vehicle_id_map[vehicle["stock_id"]],
                    investor_id,
                    vehicle["total_cost"],
                    vehicle["source_sheet"],
                ),
            )
            summary.allocations_created += 1

        def resolve_vehicle_id_from_plate(plate_value: Any) -> int | None:
            normalized_plate = extract_plate_candidate(plate_value)
            if not normalized_plate:
                return None
            matches = vehicles_by_plate.get(normalized_plate, [])
            if len(matches) == 1:
                return vehicle_id_map[matches[0]["stock_id"]]
            if len(matches) > 1:
                validation["ambiguous_vehicle_links"].append(
                    {"type": "duplicate_plate_reference", "plate": normalized_plate, "count": len(matches)}
                )
            return None

        expense_rows = workbook_rows.get("Expense", [])
        investor_car_expense_rows = workbook_rows.get("Investor Car Expense", [])
        fuel_rows = workbook_rows.get("Fuel Expense", [])
        detail_expense_rows: list[dict[str, Any]] = []
        for sheet_name, sheet in sheet_map.items():
            detail_rows, matched_stock_id = parse_detail_sheet_expenses(sheet, vehicles_by_plate, vehicles_by_stock_id)
            if sheet_name not in SUPPORTED_SHEETS and not matched_stock_id and any(sheet.rows):
                validation["unmatched_detail_sheets"].append(sheet_name)
            detail_expense_rows.extend(detail_rows)

        def insert_vehicle_expense(
            *,
            vehicle_id: int,
            expense_scope: str,
            expense_type: str,
            category: str,
            description: str,
            vendor: str,
            amount: float,
            payment_method: str,
            paid_by: str,
            expense_date: str | None,
            source_sheet: str,
            source_row_ref: str,
            workbook_detail_sheet: str | None,
            notes: str,
        ) -> None:
            connection.execute(
                """
                INSERT INTO vehicle_expenses (
                    vehicle_id,
                    expense_scope,
                    expense_type,
                    category,
                    description,
                    vendor,
                    amount,
                    payment_method,
                    paid_by,
                    expense_date,
                    source_sheet,
                    source_row_ref,
                    workbook_detail_sheet,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle_id,
                    expense_scope,
                    expense_type,
                    category,
                    description,
                    vendor,
                    amount,
                    payment_method,
                    paid_by,
                    expense_date,
                    source_sheet,
                    source_row_ref,
                    workbook_detail_sheet,
                    notes,
                ),
            )

        for row in expense_rows:
            if not is_probable_expense_row(row, "Amount "):
                continue
            vehicle_id = resolve_vehicle_id_from_plate(record_value(row, "Notes", "From"))
            if vehicle_id is None:
                continue
            insert_vehicle_expense(
                vehicle_id=vehicle_id,
                expense_scope="main_sheet",
                expense_type="expense",
                category=normalize_text(record_value(row, "Category")),
                description=normalize_text(record_value(row, "Notes", "Category") or "Expense"),
                vendor=normalize_text(record_value(row, "From")),
                amount=parse_decimal(record_value(row, "Amount", "Amount ")),
                payment_method=normalize_text(record_value(row, "Payment Method")),
                paid_by=normalize_text(record_value(row, "Paid By")),
                expense_date=parse_excel_date(record_value(row, "Date")) or parse_excel_date(record_value(row, "Month")),
                source_sheet="Expense",
                source_row_ref=row["_row_ref"],
                workbook_detail_sheet=None,
                notes=normalize_text(record_value(row, "Notes")),
            )
            summary.vehicle_expenses_created += 1

        for row in investor_car_expense_rows:
            if not is_probable_expense_row(row, "Amount"):
                continue
            vehicle_id = resolve_vehicle_id_from_plate(record_value(row, "Reg"))
            if vehicle_id is None:
                continue
            insert_vehicle_expense(
                vehicle_id=vehicle_id,
                expense_scope="main_sheet",
                expense_type="investor_car_expense",
                category="Investor Car Expense",
                description=normalize_text(record_value(row, "Reason") or "Investor Car Expense"),
                vendor="",
                amount=parse_decimal(record_value(row, "Amount")),
                payment_method="",
                paid_by="",
                expense_date=parse_excel_date(record_value(row, "Date")) or parse_excel_date(record_value(row, "Month")),
                source_sheet="Investor Car Expense",
                source_row_ref=row["_row_ref"],
                workbook_detail_sheet=None,
                notes=normalize_text(record_value(row, "Reg")),
            )
            summary.vehicle_expenses_created += 1

        for row in fuel_rows:
            if not is_probable_expense_row(row, "Amount "):
                continue
            vehicle_id = resolve_vehicle_id_from_plate(record_value(row, "Car"))
            if vehicle_id is None:
                continue
            insert_vehicle_expense(
                vehicle_id=vehicle_id,
                expense_scope="main_sheet",
                expense_type="fuel_expense",
                category="Fuel",
                description="Fuel Expense",
                vendor="",
                amount=parse_decimal(record_value(row, "Amount", "Amount ")),
                payment_method="",
                paid_by="",
                expense_date=parse_excel_date(record_value(row, "Date")) or parse_excel_date(record_value(row, "Month")),
                source_sheet="Fuel Expense",
                source_row_ref=row["_row_ref"],
                workbook_detail_sheet=None,
                notes=normalize_text(record_value(row, "Car")),
            )
            summary.vehicle_expenses_created += 1

        for row in detail_expense_rows:
            vehicle_id = vehicle_id_map[row["stock_id"]]
            insert_vehicle_expense(
                vehicle_id=vehicle_id,
                expense_scope=row["expense_scope"],
                expense_type=row["expense_type"],
                category=row["category"],
                description=row["description"],
                vendor=row["vendor"],
                amount=row["amount"],
                payment_method=row["payment_method"],
                paid_by=row["paid_by"],
                expense_date=row["expense_date"],
                source_sheet=row["source_sheet"],
                source_row_ref=row["source_row_ref"],
                workbook_detail_sheet=row["workbook_detail_sheet"],
                notes=row["notes"],
            )
            summary.vehicle_expenses_created += 1

        collection_rows = workbook_rows.get("Collection", [])
        for row in collection_rows:
            if not is_probable_collection_row(row):
                continue
            vehicle_id = resolve_vehicle_id_from_plate(record_value(row, "Plate Number"))
            connection.execute(
                """
                INSERT INTO collections_deliveries (
                    vehicle_id,
                    job_type,
                    source,
                    date_won,
                    scheduled_date,
                    completed_date,
                    address,
                    postcode,
                    distance_note,
                    contact_number,
                    status,
                    notes,
                    source_sheet,
                    source_row_ref
                ) VALUES (?, 'collection', ?, ?, ?, NULL, ?, ?, ?, ?, 'Pending', ?, 'Collection', ?)
                """,
                (
                    vehicle_id,
                    normalize_text(record_value(row, "Source")),
                    parse_excel_date(record_value(row, "Date Won")),
                    parse_excel_date(record_value(row, "Collection Date")),
                    normalize_text(record_value(row, "Location")),
                    normalize_text(record_value(row, "Post Code")),
                    normalize_text(record_value(row, "How Far?")),
                    normalize_text(record_value(row, "Number")),
                    normalize_text(record_value(row, "Additional notes")),
                    row["_row_ref"],
                ),
            )
            summary.collection_jobs_created += 1

        def insert_money_movement(row: dict[str, Any], source_sheet: str, direction: str) -> None:
            vehicle_id = resolve_vehicle_id_from_plate(record_value(row, "Reg", "Notes", "Cost Incurred on"))
            connection.execute(
                """
                INSERT INTO money_movements (
                    vehicle_id,
                    direction,
                    category,
                    amount,
                    movement_date,
                    payment_method,
                    counterparty,
                    notes,
                    source_sheet,
                    source_row_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vehicle_id,
                    direction,
                    normalize_text(record_value(row, "Category") or source_sheet),
                    parse_decimal(record_value(row, "Amount", "Amount ")),
                    parse_excel_date(record_value(row, "Date")) or parse_excel_date(record_value(row, "Month")),
                    normalize_text(record_value(row, "Payment Method")),
                    normalize_text(record_value(row, "Paid By", "From")),
                    normalize_text(record_value(row, "Notes", "Reason")),
                    source_sheet,
                    row["_row_ref"],
                ),
            )

        for row in workbook_rows.get("Money in", []):
            if not is_probable_expense_row(row, "Amount "):
                continue
            insert_money_movement(row, "Money in", "in")
            summary.money_movements_created += 1
        for row in workbook_rows.get("Money Out", []):
            if not is_probable_expense_row(row, "Amount "):
                continue
            insert_money_movement(row, "Money Out", "out")
            summary.money_movements_created += 1
        for row in workbook_rows.get("Cash Spending", []):
            if not is_probable_expense_row(row, "Amount "):
                continue
            insert_money_movement(row, "Cash Spending", "out")
            summary.money_movements_created += 1

        restored_invoices = restore_preserved_invoices(connection, preserved_invoices, validation)
        summary.preserved_links_restored = relink_preserved_records(connection)
        summary.preserved_links_restored["invoices"] = restored_invoices
        summary.validation = validation
        connection.execute(
            """
            UPDATE workbook_sync_runs
            SET status = 'completed',
                finished_at = CURRENT_TIMESTAMP,
                summary_json = ?,
                conflicts_json = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    {
                        "vehicles_created": summary.vehicles_created,
                        "investors_created": summary.investors_created,
                        "allocations_created": summary.allocations_created,
                        "vehicle_expenses_created": summary.vehicle_expenses_created,
                        "collection_jobs_created": summary.collection_jobs_created,
                        "money_movements_created": summary.money_movements_created,
                        "preserved_links_restored": summary.preserved_links_restored,
                    }
                ),
                json.dumps(validation),
                sync_run_id,
            ),
        )
        connection.commit()

    return summary


def seed_from_workbook_if_database_empty(db_path: Path, workbook_path: Path) -> ImportSummary | None:
    with connect_sqlite(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM vehicles").fetchone()
        vehicle_count = int(row["count"]) if row else 0

    if vehicle_count > 0:
        return None

    return import_workbook_to_database(db_path, workbook_path)


def list_workbook_sync_runs(db_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    with connect_sqlite(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, direction, status, source_path, started_at, finished_at, summary_json, conflicts_json
            FROM workbook_sync_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        summary_json = row["summary_json"]
        conflicts_json = row["conflicts_json"]
        results.append(
            {
                "id": row["id"],
                "direction": row["direction"],
                "status": row["status"],
                "source_path": row["source_path"] or "",
                "started_at": row["started_at"] or "",
                "finished_at": row["finished_at"] or "",
                "summary": json.loads(summary_json) if summary_json else None,
                "conflicts": json.loads(conflicts_json) if conflicts_json else None,
            }
        )
    return results
