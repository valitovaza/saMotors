from __future__ import annotations

import shutil
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.workbook_schema import (
    BACKUP_ROOT,
    EXPORT_ROOT,
    INVOICE_FOLDER_TEMPLATE,
    INVESTOR_FOLDER_TEMPLATE,
    LOCAL_DB,
    LOCAL_WORKBOOK,
    SOURCE_WORKBOOK,
    STORAGE_ROOT,
)
from app.db import apply_schema_migrations, initialize_database
from app.services import seed_from_workbook_if_database_empty


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_workbook_copy() -> None:
    ensure_directory(LOCAL_WORKBOOK.parent)
    if SOURCE_WORKBOOK.exists() and not LOCAL_WORKBOOK.exists():
        shutil.copy2(SOURCE_WORKBOOK, LOCAL_WORKBOOK)


def ensure_storage_layout() -> None:
    ensure_directory(STORAGE_ROOT / "Cars")
    ensure_directory(STORAGE_ROOT / "Investors")
    ensure_directory(STORAGE_ROOT / "Invoices")
    ensure_directory(EXPORT_ROOT)
    ensure_directory(BACKUP_ROOT)

    for folder_name in INVESTOR_FOLDER_TEMPLATE:
        ensure_directory(STORAGE_ROOT / "Investors" / "_template" / folder_name)

    for folder_name in INVOICE_FOLDER_TEMPLATE:
        ensure_directory(STORAGE_ROOT / "Invoices" / folder_name)


def ensure_database() -> None:
    ensure_directory(LOCAL_DB.parent)
    initialize_database(LOCAL_DB, LOCAL_WORKBOOK.name)
    apply_schema_migrations(LOCAL_DB)


def main() -> None:
    ensure_workbook_copy()
    ensure_storage_layout()
    ensure_database()
    import_summary = seed_from_workbook_if_database_empty(LOCAL_DB, LOCAL_WORKBOOK)
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Workbook copy: {LOCAL_WORKBOOK}")
    print(f"Database: {LOCAL_DB}")
    print(f"Storage root: {STORAGE_ROOT}")
    if import_summary is not None:
        print(
            "Seed import:"
            f" vehicles={import_summary.vehicles_created},"
            f" investors={import_summary.investors_created},"
            f" allocations={import_summary.allocations_created},"
            f" vehicle_expenses={import_summary.vehicle_expenses_created},"
            f" collection_jobs={import_summary.collection_jobs_created},"
            f" money_movements={import_summary.money_movements_created}"
        )


if __name__ == "__main__":
    main()
