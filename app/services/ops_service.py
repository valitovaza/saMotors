from __future__ import annotations

from datetime import UTC, datetime
import mimetypes
import os
from pathlib import Path
from typing import Any

from app.config.workbook_schema import LOCAL_DB, STORAGE_ROOT
from app.db import checkpoint_wal, connect_sqlite
from app.services.workbook_importer import normalize_model, normalize_plate


def _to_money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _storage_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return "/storage/" + str(relative_path).replace(os.sep, "/").lstrip("/")


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (name or "file"))
    return cleaned.strip("._") or "file"


def _resolve_vehicle(connection: Any, plate: str | None) -> dict[str, Any] | None:
    normalized_plate = normalize_plate(plate or "")
    if not normalized_plate:
        return None
    row = connection.execute(
        """
        SELECT id, stock_id, plate, display_name
        FROM vehicles
        WHERE plate_normalized = ?
        ORDER BY CASE WHEN status = 'In Stock' THEN 0 ELSE 1 END, id DESC
        LIMIT 1
        """,
        (normalized_plate,),
    ).fetchone()
    return dict(row) if row else None


def _ensure_default_staff(connection: Any) -> None:
    count = connection.execute("SELECT COUNT(*) AS count FROM staff_members").fetchone()["count"]
    if count:
        return
    connection.executemany(
        """
        INSERT INTO staff_members (name, role, pay_type, rate, phone, owed_amount, paid_total, linked_plate)
        VALUES (?, ?, ?, ?, '', 0, 0, '')
        """,
        [
            ("Jatin", "Driver / Runner", "Per Job", 80),
            ("Ernest", "Prep / Bodywork", "Per Car", 150),
        ],
    )
    connection.commit()


def load_ops_state(db_path: Path = LOCAL_DB) -> dict[str, list[dict[str, Any]]]:
    connection = connect_sqlite(db_path)
    try:
        _ensure_default_staff(connection)
        service_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT sr.*, COALESCE(v.display_name, '') AS vehicle_model
                FROM service_records sr
                LEFT JOIN vehicles v ON v.id = sr.vehicle_id
                ORDER BY COALESCE(sr.service_date, sr.created_at) DESC, sr.id DESC
                """
            ).fetchall()
        ]
        viewing_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM viewings
                ORDER BY viewing_date DESC, COALESCE(viewing_time, '') DESC, id DESC
                """
            ).fetchall()
        ]
        fine_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM fines
                ORDER BY COALESCE(fine_date, created_at) DESC, id DESC
                """
            ).fetchall()
        ]
        receipt_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT r.*, COALESCE(v.display_name, '') AS vehicle_model
                FROM receipts r
                LEFT JOIN vehicles v ON v.id = r.vehicle_id
                ORDER BY COALESCE(r.receipt_date, r.created_at) DESC, r.id DESC
                """
            ).fetchall()
        ]
        staff_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM staff_members
                WHERE active = 1
                ORDER BY name COLLATE NOCASE ASC
                """
            ).fetchall()
        ]
        wage_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT wp.*, sm.name
                FROM wage_payments wp
                JOIN staff_members sm ON sm.id = wp.staff_id
                ORDER BY COALESCE(wp.payment_date, wp.created_at) DESC, wp.id DESC
                """
            ).fetchall()
        ]
        task_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM custom_tasks
                ORDER BY COALESCE(due_date, created_at) DESC, id DESC
                """
            ).fetchall()
        ]
    finally:
        connection.close()

    return {
        "service_records": [
            {
                "id": row["id"],
                "plate": row["plate"] or "",
                "model": row["vehicle_model"] or "",
                "type": row["record_type"],
                "date": row["service_date"] or "",
                "miles": row["mileage"] or 0,
                "stamps": row["stamps"] or 0,
                "notes": row["notes"] or "",
                "photo": _storage_url(row["photo_path"]),
                "ref": row["reference"],
            }
            for row in service_rows
        ],
        "viewings": [
            {
                "id": row["id"],
                "name": row["customer_name"],
                "phone": row["phone"] or "",
                "vehicle": row["vehicle_label"] or "",
                "date": row["viewing_date"] or "",
                "time": row["viewing_time"] or "",
                "notes": row["notes"] or "",
                "status": row["status"] or "Booked",
                "source": row["source"] or "",
                "finance": row["finance"] or "",
                "delivery": row["delivery"] or "",
                "outcome": row["outcome"] or row["status"] or "",
            }
            for row in viewing_rows
        ],
        "fines": [
            {
                "id": row["id"],
                "plate": row["plate"] or "",
                "type": row["fine_type"],
                "date": row["fine_date"] or "",
                "amount": _to_money(row["amount"]),
                "due": row["due_date"] or "",
                "ref": row["reference"] or "",
                "notes": row["notes"] or "",
                "status": row["status"] or "Unpaid",
            }
            for row in fine_rows
        ],
        "receipts": [
            {
                "id": row["id"],
                "plate": row["plate"] or "",
                "model": row["vehicle_model"] or "",
                "cat": row["category"],
                "notes": row["notes"] or "",
                "amount": _to_money(row["amount"]),
                "date": row["receipt_date"] or "",
                "img": _storage_url(row["image_path"]),
            }
            for row in receipt_rows
        ],
        "staff": [
            {
                "id": row["id"],
                "name": row["name"],
                "role": row["role"] or "",
                "payType": row["pay_type"],
                "rate": _to_money(row["rate"]),
                "phone": row["phone"] or "",
                "owed": _to_money(row["owed_amount"]),
                "paid": _to_money(row["paid_total"]),
                "linkedPlate": row["linked_plate"] or "",
            }
            for row in staff_rows
        ],
        "wage_payments": [
            {
                "id": row["id"],
                "staff_id": row["staff_id"],
                "name": row["name"],
                "amount": _to_money(row["amount"]),
                "date": row["payment_date"] or "",
                "period": row["period"] or "",
                "method": row["method"] or "",
                "notes": row["notes"] or "",
            }
            for row in wage_rows
        ],
        "custom_tasks": [
            {
                "id": row["id"],
                "title": row["title"],
                "dueDate": row["due_date"] or "",
                "priority": row["priority"] or "Normal",
                "notes": row["notes"] or "",
                "status": row["status"] or "Pending",
            }
            for row in task_rows
        ],
    }


def create_service_record(
    *,
    plate: str,
    record_type: str,
    service_date: str,
    mileage: int,
    stamps: int,
    notes: str,
    file_name: str | None = None,
    mime_type: str | None = None,
    content: bytes | None = None,
    db_path: Path = LOCAL_DB,
) -> None:
    connection = connect_sqlite(db_path)
    try:
        vehicle = _resolve_vehicle(connection, plate)
        reference = "SVC-" + str(int(datetime.now(UTC).timestamp() * 1000))[-6:]
        photo_path = None
        if content:
            if vehicle:
                target_dir = STORAGE_ROOT / "Cars" / vehicle["stock_id"] / "ServiceHistory"
            else:
                target_dir = STORAGE_ROOT / "ServiceHistory"
            target_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _sanitize_filename(file_name or "service-record")
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix or mimetypes.guess_extension(mime_type or "") or ""
            stored_name = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{stem}{suffix}"
            file_path = target_dir / stored_name
            file_path.write_bytes(content)
            photo_path = str(file_path.relative_to(STORAGE_ROOT))
        cursor = connection.execute(
            """
            INSERT INTO service_records (
                vehicle_id, plate, record_type, service_date, mileage, stamps, notes, photo_path, reference
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle["id"] if vehicle else None,
                plate.strip().upper(),
                (record_type or "Service").strip(),
                service_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                int(mileage or 0),
                int(stamps or 0),
                (notes or "").strip(),
                photo_path,
                reference,
            ),
        )
        service_record_id = int(cursor.lastrowid)
        if photo_path:
            connection.execute(
                """
                INSERT INTO document_files (
                    entity_type, entity_id, vehicle_id, stock_id, category,
                    original_name, stored_name, relative_path, mime_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "service_record",
                    str(service_record_id),
                    vehicle["id"] if vehicle else None,
                    vehicle["stock_id"] if vehicle else None,
                    "ServiceHistory",
                    file_name or "service-record",
                    Path(photo_path).name,
                    photo_path,
                    mime_type or "",
                ),
            )
        connection.commit()
        # Checkpoint WAL to ensure data is immediately visible to other connections
        checkpoint_wal(db_path)
    finally:
        connection.close()


def create_viewing(
    *,
    customer_name: str,
    phone: str,
    vehicle_label: str,
    viewing_date: str,
    viewing_time: str,
    notes: str,
    source: str,
    finance: str,
    delivery: str,
    db_path: Path = LOCAL_DB,
) -> None:
    if not customer_name.strip():
        raise ValueError("Customer name is required.")
    if not viewing_date.strip():
        raise ValueError("Viewing date is required.")
    vehicle = None
    connection = connect_sqlite(db_path)
    try:
        vehicle_plate = ""
        if vehicle_label:
            vehicle_plate = vehicle_label.split(" · ")[-1].strip().upper()
            vehicle = _resolve_vehicle(connection, vehicle_plate)
        connection.execute(
            """
            INSERT INTO viewings (
                vehicle_id, vehicle_plate, vehicle_label, customer_name, phone, viewing_date, viewing_time,
                notes, status, source, finance, delivery, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Booked', ?, ?, ?, 'Booked')
            """,
            (
                vehicle["id"] if vehicle else None,
                vehicle_plate,
                vehicle_label.strip(),
                customer_name.strip(),
                phone.strip(),
                viewing_date.strip(),
                viewing_time.strip(),
                notes.strip(),
                source.strip(),
                finance.strip(),
                delivery.strip(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def update_viewing_status(*, viewing_id: int, status: str, db_path: Path = LOCAL_DB) -> None:
    normalized_status = (status or "Booked").strip() or "Booked"
    connection = connect_sqlite(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE viewings
            SET status = ?,
                outcome = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_status, normalized_status, viewing_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Viewing not found.")
        connection.commit()
    finally:
        connection.close()


def create_fine(
    *,
    plate: str,
    fine_type: str,
    fine_date: str,
    amount: float,
    due_date: str,
    reference: str,
    notes: str,
    db_path: Path = LOCAL_DB,
) -> None:
    normalized_amount = _to_money(amount)
    if normalized_amount <= 0:
        raise ValueError("Fine amount must be greater than zero.")
    connection = connect_sqlite(db_path)
    try:
        vehicle = _resolve_vehicle(connection, plate)
        connection.execute(
            """
            INSERT INTO fines (
                vehicle_id, plate, fine_type, fine_date, amount, due_date, reference, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Unpaid')
            """,
            (
                vehicle["id"] if vehicle else None,
                plate.strip().upper(),
                (fine_type or "Fine").strip(),
                fine_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                normalized_amount,
                due_date or "",
                reference.strip(),
                notes.strip(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def update_fine_status(*, fine_id: int, status: str, db_path: Path = LOCAL_DB) -> None:
    connection = connect_sqlite(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE fines
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            ((status or "Unpaid").strip(), fine_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Fine not found.")
        connection.commit()
    finally:
        connection.close()


def create_receipt(
    *,
    plate: str,
    category: str,
    notes: str,
    amount: float,
    receipt_date: str,
    file_name: str | None,
    mime_type: str | None,
    content: bytes | None,
    db_path: Path = LOCAL_DB,
) -> None:
    normalized_amount = _to_money(amount)
    if normalized_amount <= 0:
        raise ValueError("Receipt amount must be greater than zero.")
    connection = connect_sqlite(db_path)
    try:
        vehicle = _resolve_vehicle(connection, plate)
        image_path = None
        if content:
            if vehicle:
                target_dir = STORAGE_ROOT / "Cars" / vehicle["stock_id"] / "Documents"
            else:
                target_dir = STORAGE_ROOT / "Receipts"
            target_dir.mkdir(parents=True, exist_ok=True)
            safe_name = _sanitize_filename(file_name or "receipt")
            stem = Path(safe_name).stem
            suffix = Path(safe_name).suffix or mimetypes.guess_extension(mime_type or "") or ""
            stored_name = f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}-{stem}{suffix}"
            file_path = target_dir / stored_name
            file_path.write_bytes(content)
            image_path = str(file_path.relative_to(STORAGE_ROOT))
        connection.execute(
            """
            INSERT INTO receipts (
                vehicle_id, plate, category, notes, amount, receipt_date, image_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vehicle["id"] if vehicle else None,
                plate.strip().upper(),
                (category or "Other").strip(),
                notes.strip(),
                normalized_amount,
                receipt_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                image_path,
            ),
        )
        if vehicle:
            connection.execute(
                """
                INSERT INTO vehicle_expenses (
                    vehicle_id, expense_scope, expense_type, category, description, vendor, amount,
                    payment_method, paid_by, expense_date, source_sheet, source_row_ref, workbook_detail_sheet, notes
                ) VALUES (?, 'receipt', 'expense', ?, ?, '', ?, '', '', ?, 'App Receipt Entry', 'APP:receipt', NULL, ?)
                """,
                (
                    vehicle["id"],
                    (category or "Other").strip(),
                    ((notes or category or "Receipt") + " (receipt)").strip(),
                    normalized_amount,
                    receipt_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                    notes.strip(),
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
                (normalized_amount, normalized_amount, vehicle["id"]),
            )
        connection.commit()
    finally:
        connection.close()


def create_staff_member(
    *,
    name: str,
    role: str,
    pay_type: str,
    rate: float,
    phone: str,
    db_path: Path = LOCAL_DB,
) -> None:
    if not name.strip():
        raise ValueError("Staff name is required.")
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT INTO staff_members (name, role, pay_type, rate, phone, owed_amount, paid_total, linked_plate)
            VALUES (?, ?, ?, ?, ?, 0, 0, '')
            """,
            (name.strip(), role.strip(), pay_type.strip() or "Per Job", _to_money(rate), phone.strip()),
        )
        connection.commit()
    finally:
        connection.close()


def adjust_staff_owed(*, staff_id: int, amount_delta: float, db_path: Path = LOCAL_DB) -> None:
    normalized_delta = _to_money(amount_delta)
    if normalized_delta <= 0:
        raise ValueError("Amount must be greater than zero.")
    connection = connect_sqlite(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE staff_members
            SET owed_amount = owed_amount + ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_delta, staff_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Staff member not found.")
        connection.commit()
    finally:
        connection.close()


def create_wage_payment(
    *,
    staff_id: int,
    amount: float,
    payment_date: str,
    period: str,
    method: str,
    notes: str,
    db_path: Path = LOCAL_DB,
) -> None:
    normalized_amount = _to_money(amount)
    if normalized_amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    connection = connect_sqlite(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE staff_members
            SET owed_amount = MAX(0, owed_amount - ?),
                paid_total = paid_total + ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_amount, normalized_amount, staff_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Staff member not found.")
        connection.execute(
            """
            INSERT INTO wage_payments (staff_id, payment_date, amount, period, method, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                staff_id,
                payment_date or datetime.now(UTC).strftime("%Y-%m-%d"),
                normalized_amount,
                period.strip(),
                method.strip(),
                notes.strip(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def create_custom_task(
    *,
    title: str,
    due_date: str,
    priority: str,
    notes: str,
    db_path: Path = LOCAL_DB,
) -> None:
    if not title.strip():
        raise ValueError("Task title is required.")
    connection = connect_sqlite(db_path)
    try:
        connection.execute(
            """
            INSERT INTO custom_tasks (title, due_date, priority, notes, status)
            VALUES (?, ?, ?, ?, 'Pending')
            """,
            (title.strip(), due_date or "", (priority or "Normal").strip(), notes.strip()),
        )
        connection.commit()
    finally:
        connection.close()


def update_custom_task_status(*, task_id: int, status: str, db_path: Path = LOCAL_DB) -> None:
    normalized_status = (status or "Pending").strip() or "Pending"
    connection = connect_sqlite(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE custom_tasks
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_status, task_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Task not found.")
        connection.commit()
    finally:
        connection.close()


def delete_custom_task(*, task_id: int, db_path: Path = LOCAL_DB) -> None:
    connection = connect_sqlite(db_path)
    try:
        cursor = connection.execute(
            "DELETE FROM custom_tasks WHERE id = ?",
            (task_id,),
        )
        if cursor.rowcount == 0:
            raise ValueError("Task not found.")
        connection.commit()
    finally:
        connection.close()
