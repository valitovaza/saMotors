from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime
import mimetypes
import os
from pathlib import Path
import json
from typing import Any

from app.config.workbook_schema import (
    INVOICE_FOLDER_TEMPLATE,
    INVESTOR_FOLDER_TEMPLATE,
    LOCAL_DB,
    STORAGE_ROOT,
    VEHICLE_FOLDER_TEMPLATE,
)
from app.db import checkpoint_wal, connect_sqlite
from app.services.ops_service import load_ops_state
from app.services.workbook_importer import normalize_model, normalize_plate, split_make_model


VEHICLE_QUERY = """
SELECT
    v.*,
    COALESCE(
        (
            SELECT i.name
            FROM vehicle_investor_allocations via
            JOIN investors i ON i.id = via.investor_id
            WHERE via.vehicle_id = v.id
            ORDER BY via.id ASC
            LIMIT 1
        ),
        'SA'
    ) AS investor_name,
    COALESCE(
        (
            SELECT SUM(ve.amount)
            FROM vehicle_expenses ve
            WHERE ve.vehicle_id = v.id
        ),
        0
    ) AS expense_total,
    COALESCE(
        (
            SELECT SUM(via.investor_profit_amount)
            FROM vehicle_investor_allocations via
            WHERE via.vehicle_id = v.id
        ),
        0
    ) AS investor_profit_total,
    COALESCE(
        (
            SELECT SUM(via.company_profit_amount)
            FROM vehicle_investor_allocations via
            WHERE via.vehicle_id = v.id
        ),
        0
    ) AS company_profit_total
FROM vehicles v
ORDER BY COALESCE(v.date_sold, v.date_acquired, v.created_at) DESC, v.id DESC
"""


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for candidate in (text, f"{text}T00:00:00"):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except ValueError:
            continue
    return None


def _days_between(start: str | None, end: str | None = None) -> int:
    start_dt = _parse_iso_date(start)
    if start_dt is None:
        return 0
    end_dt = _parse_iso_date(end) or datetime.now(UTC)
    return max(0, (end_dt.date() - start_dt.date()).days)


def _today_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _month_bucket(*values: str | None) -> str:
    for value in values:
        parsed = _parse_iso_date(value)
        if parsed is not None:
            return parsed.strftime("%Y-%m-01")
    return ""


def _month_label(month: str) -> str:
    parsed = _parse_iso_date(month)
    return parsed.strftime("%b %y") if parsed is not None else "—"


def _storage_url(relative_path: str) -> str:
    return "/storage/" + relative_path.replace(os.sep, "/").lstrip("/")


def _to_money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _categorize_expense(label: str | None) -> str:
    text = (label or "").strip()
    lower = text.lower()
    if "fuel" in lower:
        return "Fuel"
    if "mot" in lower:
        return "MOT"
    if "transport" in lower or "uber" in lower or "tfl" in lower:
        return "Transport"
    if "warranty" in lower or "autoguard" in lower:
        return "Warranty"
    if "fee" in lower or "auction" in lower:
        return "Fees"
    if "part" in lower:
        return "Parts"
    if "labour" in lower or "bodywork" in lower:
        return "Labour"
    if "valet" in lower or "clean" in lower:
        return "Valet"
    if "fixed overhead" in lower or "rent" in lower or "admin" in lower or "office" in lower:
        return "Fixed Overhead"
    return text or "Other"


def _vehicle_payload(row: dict[str, Any]) -> dict[str, Any]:
    recon_cost = max(_to_money(row["reconditioning_costs"]), _to_money(row["expense_total"]))
    total_cost = _to_money(row["total_cost_cached"]) or _to_money(row["purchase_price"]) + recon_cost
    sold_price = _to_money(row["sold_price"])
    profit_total = _to_money(row["profit_total_cached"]) or round(sold_price - total_cost, 2)
    investor_name = row["investor_name"] or "SA"
    listed = bool(row["date_listed"])
    payload = {
        "stock_id": row["stock_id"],
        "plate": row["plate"] or "",
        "model": row["display_name"] or row["model"] or "Unknown Vehicle",
        "month": _month_bucket(row["date_acquired"], row["date_sold"], row["created_at"]),
        "date_acquired": row["date_acquired"] or "",
        "date_sold": row["date_sold"] or "",
        "mot_expiry": row["mot_expiry"] or "",
        "mot_status": row["mot_status"] or "",
        "mot_last_result": row["mot_last_result"] or "",
        "mot_last_checked": row["mot_last_checked"] or "",
        "mot_advisories": json.loads(row["mot_advisories_json"] or "[]"),
        "source": row["source"] or "",
        "investor": investor_name if investor_name not in {"MP", ""} else "SA",
        "purchase_price": _to_money(row["purchase_price"]),
        "recon_cost": recon_cost,
        "total_cost": total_cost,
        "sold_price": sold_price,
        "profit": profit_total,
        "investor_profit": _to_money(row["investor_profit_total"]),
        "mp_profit": _to_money(row["company_profit_total"]),
        "status": row["status"] or "In Stock",
        "notes": row["notes"] or "",
        "platform": row["platform"] or "",
        "invoice_number": row["invoice_number"] or "",
        "customer_name": row["customer_name"] or "",
        "contact_info": row["contact_info"] or "",
        "warranty": row["warranty"] or "",
        "autoguard": row["autoguard_number"] or "",
        "days_in_stock": _days_between(row["date_acquired"], row["date_sold"]),
        "needs_mot": bool(row["mot_expiry"])
        and _days_between(_today_iso(), row["mot_expiry"]) <= 183,
        "website_listed": listed,
        "autotrader_listed": listed,
        "todo": [] if listed else ["List live"],
    }
    return payload


def _collection_payload(row: dict[str, Any]) -> dict[str, Any]:
    date_won = row["date_won"] or ""
    driver, cost, linked_vehicles, clean_notes = _parse_collection_notes(row["notes"])
    return {
        "id": f"job-{row['id']}",
        "type": "Incoming" if row["job_type"] == "collection" else "Delivery",
        "plate": row["plate"] or "",
        "stock_id": row["stock_id"] or "",
        "model": row["display_name"] or row["model"] or "Unknown Vehicle",
        "source": row["source"] or "",
        "date_won": date_won,
        "date": row["scheduled_date"] or row["completed_date"] or "",
        "scheduled_date": row["scheduled_date"] or "",
        "collection_date": row["scheduled_date"] or "",
        "addr": row["address"] or "",
        "maps_place_id": row["maps_place_id"] or "",
        "maps_latitude": row["maps_latitude"],
        "maps_longitude": row["maps_longitude"],
        "postcode": row["postcode"] or "",
        "distance_note": row["distance_note"] or "",
        "driver": driver,
        "cost": cost,
        "status": row["status"] or "Pending",
        "notes": clean_notes,
        "days_pending": _days_between(date_won) if (row["status"] or "").lower() != "collected" else 0,
        "linked_vehicles": linked_vehicles,
    }


def _monthly_summary(sold: list[dict[str, Any]], finance_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "month": "",
            "label": "",
            "cars_sold": 0,
            "revenue": 0.0,
            "gross_profit": 0.0,
            "net_profit": 0.0,
            "expenses": 0.0,
            "fuel": 0.0,
        }
    )

    for vehicle in sold:
        month = vehicle["month"] or _month_bucket(vehicle.get("date_sold"), vehicle.get("date_acquired"))
        if not month:
            continue
        row = grouped[month]
        row["month"] = month
        row["label"] = _month_label(month)
        row["cars_sold"] += 1
        row["revenue"] += _to_money(vehicle.get("sold_price"))
        row["gross_profit"] += _to_money(vehicle.get("profit"))

    for entry in finance_log:
        month = _month_bucket(entry.get("date"))
        if not month:
            continue
        row = grouped[month]
        row["month"] = month
        row["label"] = _month_label(month)
        amount = _to_money(entry.get("amount"))
        if amount <= 0:
            continue
        if entry.get("cat") == "Fuel":
            row["fuel"] += amount
        else:
            row["expenses"] += amount

    for month in list(grouped.keys()):
        grouped[month]["net_profit"] = round(
            grouped[month]["gross_profit"] - grouped[month]["expenses"] - grouped[month]["fuel"],
            2,
        )
        for field in ("revenue", "gross_profit", "net_profit", "expenses", "fuel"):
            grouped[month][field] = round(grouped[month][field], 2)

    return [grouped[month] for month in sorted(grouped.keys())]


def ensure_storage_layout() -> None:
    cars_root = STORAGE_ROOT / "Cars"
    investors_root = STORAGE_ROOT / "Investors"
    invoices_root = STORAGE_ROOT / "Invoices"
    cars_root.mkdir(parents=True, exist_ok=True)
    investors_root.mkdir(parents=True, exist_ok=True)
    invoices_root.mkdir(parents=True, exist_ok=True)
    for folder_name in INVOICE_FOLDER_TEMPLATE:
        (invoices_root / folder_name).mkdir(parents=True, exist_ok=True)


def ensure_vehicle_storage(stock_id: str) -> Path:
    ensure_storage_layout()
    vehicle_root = STORAGE_ROOT / "Cars" / stock_id
    vehicle_root.mkdir(parents=True, exist_ok=True)
    for folder_name in VEHICLE_FOLDER_TEMPLATE:
        (vehicle_root / folder_name).mkdir(parents=True, exist_ok=True)
    return vehicle_root


def ensure_investor_storage(name: str) -> Path:
    ensure_storage_layout()
    safe_name = normalize_model(name or "Unknown Investor").replace("/", "-")
    investor_root = STORAGE_ROOT / "Investors" / safe_name
    investor_root.mkdir(parents=True, exist_ok=True)
    for folder_name in INVESTOR_FOLDER_TEMPLATE:
        (investor_root / folder_name).mkdir(parents=True, exist_ok=True)
    return investor_root


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (name or "file"))
    return cleaned.strip("._") or "file"


def _compose_collection_notes(
    *,
    notes: str,
    driver: str,
    cost: float,
    linked_vehicles: list[str],
) -> str:
    payload = {
        "notes": (notes or "").strip(),
        "driver": (driver or "").strip(),
        "cost": _to_money(cost),
        "linked_vehicles": [item.strip().upper() for item in linked_vehicles if item.strip()],
    }
    return json.dumps(payload)


def _parse_collection_notes(raw_notes: str | None) -> tuple[str, float, list[str], str]:
    if not raw_notes:
        return "", 0.0, [], ""
    try:
        payload = json.loads(raw_notes)
    except json.JSONDecodeError:
        return "", 0.0, [], raw_notes
    return (
        str(payload.get("driver") or ""),
        _to_money(payload.get("cost")),
        [str(item).strip().upper() for item in payload.get("linked_vehicles") or [] if str(item).strip()],
        str(payload.get("notes") or ""),
    )


def _resolve_vehicle_id(connection: Any, plate: str | None) -> int | None:
    normalized_plate = normalize_plate(plate or "")
    if not normalized_plate:
        return None
    rows = connection.execute(
        """
        SELECT id, status
        FROM vehicles
        WHERE plate_normalized = ?
        ORDER BY CASE WHEN status = 'In Stock' THEN 0 ELSE 1 END, id DESC
        """,
        (normalized_plate,),
    ).fetchall()
    if not rows:
        return None
    return int(rows[0]["id"])


def _resolve_vehicle_row(connection: Any, stock_id: str | None = None, plate: str | None = None) -> dict[str, Any] | None:
    if stock_id:
        row = connection.execute(
            """
            SELECT *
            FROM vehicles
            WHERE stock_id = ?
            LIMIT 1
            """,
            (stock_id,),
        ).fetchone()
        return dict(row) if row else None

    normalized_plate = normalize_plate(plate or "")
    if not normalized_plate:
        return None
    row = connection.execute(
        """
        SELECT *
        FROM vehicles
        WHERE plate_normalized = ?
        ORDER BY CASE WHEN status = 'In Stock' THEN 0 ELSE 1 END, id DESC
        LIMIT 1
        """,
        (normalized_plate,),
    ).fetchone()
    return dict(row) if row else None


def load_vehicle_rows(db_path: Path = LOCAL_DB) -> list[dict[str, Any]]:
    connection = connect_sqlite(db_path)
    try:
        rows = connection.execute(VEHICLE_QUERY).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def build_app_state(db_path: Path = LOCAL_DB) -> dict[str, Any]:
    ensure_storage_layout()
    connection = connect_sqlite(db_path)
    try:
        vehicle_rows = [dict(row) for row in connection.execute(VEHICLE_QUERY).fetchall()]

        investor_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM investors
                ORDER BY name COLLATE NOCASE ASC
                """
            ).fetchall()
        ]
        collection_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    cd.*,
                    v.stock_id,
                    v.plate,
                    v.model,
                    v.display_name
                FROM collections_deliveries cd
                LEFT JOIN vehicles v ON v.id = cd.vehicle_id
                ORDER BY COALESCE(cd.scheduled_date, cd.date_won, cd.created_at) DESC, cd.id DESC
                """
            ).fetchall()
        ]

        expense_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    ve.id,
                    ve.expense_date,
                    ve.category,
                    ve.description,
                    ve.vendor,
                    ve.amount,
                    ve.payment_method,
                    ve.paid_by,
                    ve.notes,
                    v.stock_id,
                    v.plate,
                    v.display_name
                FROM vehicle_expenses ve
                JOIN vehicles v ON v.id = ve.vehicle_id
                ORDER BY COALESCE(ve.expense_date, ve.created_at) DESC, ve.id DESC
                """
            ).fetchall()
        ]

        movement_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    mm.id,
                    mm.direction,
                    mm.category,
                    mm.amount,
                    mm.movement_date,
                    mm.payment_method,
                    mm.counterparty,
                    mm.notes,
                    v.stock_id,
                    v.plate,
                    v.display_name
                FROM money_movements mm
                LEFT JOIN vehicles v ON v.id = mm.vehicle_id
                ORDER BY COALESCE(mm.movement_date, mm.created_at) DESC, mm.id DESC
                """
            ).fetchall()
        ]
        invoice_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    i.id,
                    i.invoice_type,
                    i.invoice_number,
                    i.invoice_date,
                    i.customer_name,
                    i.amount_total,
                    i.profit_total,
                    i.investor_profit_amount,
                    i.company_profit_amount,
                    i.html_snapshot,
                    i.file_path,
                    COALESCE(i.stock_id, v.stock_id) AS stock_id,
                    v.plate,
                    v.display_name
                FROM invoices i
                LEFT JOIN vehicles v ON v.id = i.vehicle_id
                ORDER BY COALESCE(i.invoice_date, i.created_at) DESC, i.id DESC
                """
            ).fetchall()
        ]
    finally:
        connection.close()

    stock: list[dict[str, Any]] = []
    sold: list[dict[str, Any]] = []
    for row in vehicle_rows:
        payload = _vehicle_payload(row)
        if (row["status"] or "").lower() == "sold":
            sold.append(payload)
        else:
            stock.append(payload)

    investors = [
        {
            "id": row["id"],
            "name": row["name"],
            "initial_balance": _to_money(row["initial_balance"]),
            "capital_returned": _to_money(row["capital_returned"]),
            "total_balance": _to_money(row["total_balance_cached"]),
            "purchased": _to_money(row["purchased_total_cached"]),
            "total_profit": _to_money(row["profit_total_cached"]),
            "available": _to_money(row["available_balance_cached"]),
            "notes": row["notes"] or "",
        }
        for row in investor_rows
    ]

    collections: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    for row in collection_rows:
        payload = _collection_payload(row)
        if row["job_type"] == "delivery":
            deliveries.append(payload)
        else:
            collections.append(payload)

    finance_log = [
        {
            "id": f"ve-{row['id']}",
            "date": row["expense_date"] or "",
            "plate": row["plate"] or "",
            "model": row["display_name"] or "",
            "desc": " · ".join(part for part in [row["vendor"], row["description"], row["notes"]] if part),
            "cat": _categorize_expense(row["category"] or row["description"]),
            "amount": _to_money(row["amount"]),
            "direction": "out",
        }
        for row in expense_rows
    ]

    for row in movement_rows:
        category = row["category"] or ("Money In" if row["direction"] == "in" else "Money Out")
        amount = _to_money(row["amount"])
        finance_log.append(
            {
                "id": f"mm-{row['id']}",
                "date": row["movement_date"] or "",
                "plate": row["plate"] or "",
                "model": row["display_name"] or "",
                "desc": " · ".join(part for part in [category, row["counterparty"], row["notes"]] if part),
                "cat": "Money In" if row["direction"] == "in" else _categorize_expense(category),
                "amount": -amount if row["direction"] == "in" else amount,
                "direction": row["direction"],
            }
        )

    finance_log.sort(key=lambda item: (item["date"] or "", item["id"]), reverse=True)

    monthly = _monthly_summary(sold, finance_log)
    invoices = [
        {
            "id": row["id"],
            "stock_id": row["stock_id"],
            "invNum": row["invoice_number"],
            "model": row["display_name"] or row["plate"] or row["stock_id"] or row["invoice_number"],
            "plate": row["plate"] or "",
            "sale": _to_money(row["amount_total"]),
            "cost": round(_to_money(row["amount_total"]) - _to_money(row["profit_total"]), 2),
            "profit": _to_money(row["profit_total"]),
            "invP": _to_money(row["investor_profit_amount"]),
            "mpP": _to_money(row["company_profit_amount"]),
            "pct": round((_to_money(row["investor_profit_amount"]) / _to_money(row["profit_total"]) * 100), 2)
            if _to_money(row["profit_total"]) not in {0.0, -0.0}
            else 0,
            "investor": row["customer_name"] or "SA",
            "saleDate": row["invoice_date"] or "",
            "html": row["html_snapshot"] or "",
            "fileUrl": _storage_url(row["file_path"]) if row["file_path"] else None,
        }
        for row in invoice_rows
    ]

    state = {
        "stock": stock,
        "sold": sold,
        "investors": investors,
        "collections": collections,
        "deliveries": deliveries,
        "finance_log": finance_log,
        "monthly": monthly,
        "invoices": invoices,
    }
    state.update(load_ops_state(db_path))
    return state


def list_vehicles(db_path: Path = LOCAL_DB) -> list[dict[str, Any]]:
    return [_vehicle_payload(row) for row in load_vehicle_rows(db_path)]


def _generate_manual_stock_id(plate: str, model: str) -> str:
    seed = f"{normalize_plate(plate)}|{normalize_model(model)}|{datetime.now(UTC).isoformat()}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest().upper()[:10]
    return f"STOCK-{digest}"


def create_vehicle(
    *,
    plate: str,
    model: str,
    source: str = "",
    investor_name: str = "",
    purchase_price: float = 0,
    recon_cost: float = 0,
    notes: str = "",
    db_path: Path = LOCAL_DB,
) -> dict[str, Any]:
    normalized_plate = normalize_plate(plate)
    if not normalized_plate:
        raise ValueError("Plate is required.")

    display_name = normalize_model(model)
    if not display_name:
        raise ValueError("Model is required.")

    stock_id = _generate_manual_stock_id(plate, model)
    vehicle_root = ensure_vehicle_storage(stock_id)
    investor_clean = (investor_name or "").strip()

    connection = connect_sqlite(db_path)
    try:
        duplicate = connection.execute(
            "SELECT stock_id FROM vehicles WHERE plate_normalized = ? AND status != 'Sold' LIMIT 1",
            (normalized_plate,),
        ).fetchone()
        if duplicate is not None:
            raise ValueError(f"An active vehicle with plate {plate.upper()} already exists.")

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
                purchase_price,
                reconditioning_costs,
                total_cost_cached,
                notes,
                workbook_primary_sheet,
                workbook_row_ref,
                folder_path
            ) VALUES (?, ?, ?, ?, ?, ?, 'In Stock', ?, DATE('now'), ?, ?, ?, ?, 'App Manual Entry', 'APP:manual', ?)
            """,
            (
                stock_id,
                plate.strip().upper(),
                normalized_plate,
                split_make_model(display_name)[0],
                display_name,
                display_name,
                source.strip(),
                _to_money(purchase_price),
                _to_money(recon_cost),
                round(_to_money(purchase_price) + _to_money(recon_cost), 2),
                notes.strip(),
                str(vehicle_root),
            ),
        )
        vehicle_id = int(cursor.lastrowid)

        if investor_clean and investor_clean.upper() not in {"MP", "SA"}:
            investor_row = connection.execute(
                "SELECT id, name FROM investors WHERE lower(name) = lower(?) LIMIT 1",
                (investor_clean,),
            ).fetchone()
            if investor_row is None:
                raise ValueError(f"Investor '{investor_clean}' does not exist in the workbook-backed database.")
            ensure_investor_storage(str(investor_row["name"]))
            connection.execute(
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
                ) VALUES (?, ?, 'primary', ?, 0, 0, 0, 'App manual entry')
                """,
                (
                    vehicle_id,
                    int(investor_row["id"]),
                    round(_to_money(purchase_price) + _to_money(recon_cost), 2),
                ),
            )

        connection.commit()
    finally:
        connection.close()

    # Checkpoint WAL to ensure data is immediately visible to other connections
    checkpoint_wal(db_path)

    vehicle_rows = [row for row in load_vehicle_rows(db_path) if row["stock_id"] == stock_id]
    if not vehicle_rows:
        raise RuntimeError("Vehicle was created but could not be reloaded.")
    return _vehicle_payload(vehicle_rows[0])


def create_finance_entry(
    *,
    plate: str,
    category: str,
    description: str,
    amount: float,
    entry_date: str,
    db_path: Path = LOCAL_DB,
) -> None:
    normalized_description = (description or "").strip()
    if not normalized_description:
        raise ValueError("Description is required.")
    normalized_amount = _to_money(amount)
    if normalized_amount <= 0:
        raise ValueError("Amount must be greater than zero.")

    connection = connect_sqlite(db_path)
    try:
        vehicle_id = _resolve_vehicle_id(connection, plate)
        if vehicle_id is not None:
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
                ) VALUES (?, 'app_manual', 'expense', ?, ?, '', ?, '', '', ?, 'App Manual Entry', 'APP:manual', NULL, '')
                """,
                (
                    vehicle_id,
                    (category or "Other").strip(),
                    normalized_description,
                    normalized_amount,
                    entry_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                ),
            )
            connection.execute(
                """
                UPDATE vehicles
                SET reconditioning_costs = COALESCE(reconditioning_costs, 0) + ?,
                    total_cost_cached = COALESCE(total_cost_cached, 0) + ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_amount, normalized_amount, vehicle_id),
            )
        else:
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
                ) VALUES (NULL, 'out', ?, ?, ?, '', '', ?, 'App Manual Entry', 'APP:manual')
                """,
                (
                    (category or "Other").strip(),
                    normalized_amount,
                    entry_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                    normalized_description,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    # Checkpoint WAL to ensure data is immediately visible to other connections
    checkpoint_wal(db_path)


def create_collection_delivery(
    *,
    job_type: str,
    plate: str,
    date_won: str,
    scheduled_date: str,
    address: str,
    status: str,
    notes: str,
    driver: str,
    cost: float,
    linked_vehicles: list[str],
    maps_place_id: str = "",
    maps_latitude: float | None = None,
    maps_longitude: float | None = None,
    db_path: Path = LOCAL_DB,
) -> None:
    normalized_job_type = "delivery" if (job_type or "").lower() == "delivery" else "collection"
    normalized_status = (status or "Pending").strip() or "Pending"

    connection = connect_sqlite(db_path)
    try:
        vehicle_id = _resolve_vehicle_id(connection, plate)
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
                maps_place_id,
                maps_latitude,
                maps_longitude,
                postcode,
                distance_note,
                contact_number,
                status,
                notes,
                source_sheet,
                source_row_ref
            ) VALUES (?, ?, 'App Manual Entry', ?, ?, NULL, ?, ?, ?, ?, '', '', ?, ?, 'App Manual Entry', 'APP:manual')
            """,
            (
                vehicle_id,
                normalized_job_type,
                date_won or datetime.now(UTC).strftime("%Y-%m-%d"),
                scheduled_date or None,
                (address or "").strip(),
                (maps_place_id or "").strip() or None,
                maps_latitude,
                maps_longitude,
                normalized_status,
                _compose_collection_notes(
                    notes=notes,
                    driver=driver,
                    cost=cost,
                    linked_vehicles=linked_vehicles,
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    # Checkpoint WAL to ensure data is immediately visible to other connections
    checkpoint_wal(db_path)


def update_investor_total_balance(
    *,
    investor_id: int,
    total_balance: float,
    db_path: Path = LOCAL_DB,
) -> dict[str, Any]:
    normalized_total = _to_money(total_balance)
    connection = connect_sqlite(db_path)
    try:
        row = connection.execute(
            """
            SELECT id, name, purchased_total_cached
            FROM investors
            WHERE id = ?
            """,
            (investor_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Investor not found.")

        purchased_total = _to_money(row["purchased_total_cached"])
        available_total = round(normalized_total - purchased_total, 2)
        connection.execute(
            """
            UPDATE investors
            SET total_balance_cached = ?,
                available_balance_cached = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_total, available_total, investor_id),
        )
        connection.commit()
        
        # Checkpoint WAL to ensure data is immediately visible to other connections
        checkpoint_wal(db_path)
        
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "total_balance": normalized_total,
            "available": available_total,
        }
    finally:
        connection.close()


def complete_sale(
    *,
    stock_id: str,
    sale_price: float,
    sale_date: str,
    investor_name: str,
    profit_share_percent: float,
    html_snapshot: str,
    db_path: Path = LOCAL_DB,
) -> dict[str, Any]:
    normalized_sale_price = _to_money(sale_price)
    if normalized_sale_price <= 0:
        raise ValueError("Sale price must be greater than zero.")

    normalized_pct = round(float(profit_share_percent or 0), 2)
    normalized_investor = (investor_name or "SA").strip() or "SA"
    normalized_sale_date = sale_date or datetime.now(UTC).strftime("%Y-%m-%d")

    connection = connect_sqlite(db_path)
    try:
        vehicle = _resolve_vehicle_row(connection, stock_id=stock_id)
        if vehicle is None:
            raise ValueError("Vehicle not found.")
        if (vehicle["status"] or "").lower() == "sold":
            raise ValueError("Vehicle is already marked as sold.")

        cost = _to_money(vehicle["total_cost_cached"]) or _to_money(vehicle["purchase_price"]) + _to_money(
            vehicle["reconditioning_costs"]
        )
        profit = round(normalized_sale_price - cost, 2)
        investor_profit = round(profit * normalized_pct / 100, 2)
        company_profit = round(profit - investor_profit, 2)
        invoice_number = f"{normalize_plate(vehicle['plate'])}-{normalized_sale_date.replace('-', '')}-{int(datetime.now(UTC).timestamp())}"

        investor_row = None
        if normalized_investor.upper() not in {"SA", "MP"}:
            investor_row = connection.execute(
                "SELECT id, name FROM investors WHERE lower(name) = lower(?) LIMIT 1",
                (normalized_investor,),
            ).fetchone()
            if investor_row is None:
                raise ValueError(f"Investor '{normalized_investor}' does not exist.")

        connection.execute(
            """
            UPDATE vehicles
            SET status = 'Sold',
                date_sold = ?,
                sold_price = ?,
                profit_total_cached = ?,
                invoice_number = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_sale_date, normalized_sale_price, profit, invoice_number, vehicle["id"]),
        )

        if investor_row is not None:
            existing_allocation = connection.execute(
                """
                SELECT id
                FROM vehicle_investor_allocations
                WHERE vehicle_id = ? AND investor_id = ?
                LIMIT 1
                """,
                (vehicle["id"], int(investor_row["id"])),
            ).fetchone()
            if existing_allocation is None:
                connection.execute(
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
                    ) VALUES (?, ?, 'primary', ?, ?, ?, ?, 'Completed sale')
                    """,
                    (vehicle["id"], int(investor_row["id"]), cost, normalized_pct, investor_profit, company_profit),
                )
            else:
                connection.execute(
                    """
                    UPDATE vehicle_investor_allocations
                    SET profit_share_percent = ?,
                        investor_profit_amount = ?,
                        company_profit_amount = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (normalized_pct, investor_profit, company_profit, int(existing_allocation["id"])),
                )

        sale_folder = ensure_vehicle_storage(vehicle["stock_id"]) / "Sale"
        sale_folder.mkdir(parents=True, exist_ok=True)
        invoice_storage_root = STORAGE_ROOT / "Invoices" / "Investor"
        invoice_storage_root.mkdir(parents=True, exist_ok=True)
        vehicle_invoice_path = sale_folder / f"{invoice_number}.html"
        shared_invoice_path = invoice_storage_root / f"{invoice_number}.html"
        vehicle_invoice_path.write_text(html_snapshot, encoding="utf-8")
        shared_invoice_path.write_text(html_snapshot, encoding="utf-8")

        invoice_cursor = connection.execute(
            """
            INSERT INTO invoices (
                vehicle_id,
                invoice_type,
                invoice_number,
                invoice_date,
                customer_name,
                amount_total,
                profit_total,
                investor_profit_amount,
                company_profit_amount,
                stock_id,
                html_snapshot,
                file_path
            ) VALUES (?, 'investor_sale', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle["id"],
                invoice_number,
                normalized_sale_date,
                investor_row["name"] if investor_row is not None else normalized_investor,
                normalized_sale_price,
                profit,
                investor_profit,
                company_profit,
                vehicle["stock_id"],
                html_snapshot,
                str(shared_invoice_path.relative_to(STORAGE_ROOT)),
            ),
        )
        invoice_id = int(invoice_cursor.lastrowid)

        for relative_path, category in (
            (vehicle_invoice_path.relative_to(STORAGE_ROOT), "Sale"),
            (shared_invoice_path.relative_to(STORAGE_ROOT), "Invoice"),
        ):
            absolute_path = STORAGE_ROOT / relative_path
            connection.execute(
                """
                INSERT INTO document_files (
                    entity_type,
                    entity_id,
                    vehicle_id,
                    invoice_id,
                    stock_id,
                    category,
                    original_name,
                    stored_name,
                    relative_path,
                    mime_type,
                    size_bytes
                ) VALUES ('invoice', ?, ?, ?, ?, ?, ?, ?, ?, 'text/html', ?)
                """,
                (
                    invoice_number,
                    vehicle["id"],
                    invoice_id,
                    vehicle["stock_id"],
                    category,
                    f"{invoice_number}.html",
                    f"{invoice_number}.html",
                    str(relative_path),
                    absolute_path.stat().st_size if absolute_path.exists() else 0,
                ),
            )

        connection.commit()
    finally:
        connection.close()

    # Checkpoint WAL to ensure data is immediately visible to other connections
    checkpoint_wal(db_path)

    state = build_app_state(db_path)
    invoice = next((item for item in state["invoices"] if item["invNum"] == invoice_number), None)
    vehicle_payload = next((item for item in state["sold"] if item["stock_id"] == stock_id), None)
    if invoice is None or vehicle_payload is None:
        raise RuntimeError("Sale completed but invoice state could not be reloaded.")
    invoice["investor"] = normalized_investor
    invoice["pct"] = normalized_pct
    return {"vehicle": vehicle_payload, "invoice": invoice}


def list_vehicle_files(
    *,
    stock_id: str,
    category: str | None = None,
    db_path: Path = LOCAL_DB,
) -> list[dict[str, Any]]:
    connection = connect_sqlite(db_path)
    try:
        params: list[Any] = [stock_id]
        query = """
            SELECT id, category, original_name, stored_name, relative_path, mime_type, size_bytes, uploaded_at
            FROM document_files
            WHERE stock_id = ?
        """
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY uploaded_at ASC, id ASC"
        rows = connection.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "category": row["category"],
                "name": row["original_name"],
                "stored_name": row["stored_name"],
                "url": _storage_url(row["relative_path"]),
                "relative_path": row["relative_path"],
                "mime_type": row["mime_type"] or "",
                "size_bytes": row["size_bytes"] or 0,
                "uploaded_at": row["uploaded_at"],
            }
            for row in rows
        ]
    finally:
        connection.close()


def upload_vehicle_file(
    *,
    stock_id: str,
    category: str,
    original_name: str,
    mime_type: str,
    content: bytes,
    db_path: Path = LOCAL_DB,
) -> dict[str, Any]:
    target_category = category if category in VEHICLE_FOLDER_TEMPLATE else "Documents"
    connection = connect_sqlite(db_path)
    try:
        vehicle = _resolve_vehicle_row(connection, stock_id=stock_id)
        if vehicle is None:
            raise ValueError("Vehicle not found.")
        folder = ensure_vehicle_storage(stock_id) / target_category
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = _sanitize_filename(original_name)
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix or mimetypes.guess_extension(mime_type or "") or ""
        stored_name = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{stem}{suffix}"
        file_path = folder / stored_name
        file_path.write_bytes(content)
        relative_path = str(file_path.relative_to(STORAGE_ROOT))
        cursor = connection.execute(
            """
            INSERT INTO document_files (
                entity_type,
                entity_id,
                vehicle_id,
                stock_id,
                category,
                original_name,
                stored_name,
                relative_path,
                mime_type,
                size_bytes
            ) VALUES ('vehicle', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stock_id,
                vehicle["id"],
                stock_id,
                target_category,
                original_name,
                stored_name,
                relative_path,
                mime_type,
                len(content),
            ),
        )
        connection.commit()
        return {
            "id": int(cursor.lastrowid),
            "category": target_category,
            "name": original_name,
            "stored_name": stored_name,
            "url": _storage_url(relative_path),
            "relative_path": relative_path,
            "mime_type": mime_type,
            "size_bytes": len(content),
        }
    finally:
        connection.close()
