from __future__ import annotations

from pathlib import Path
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.workbook_schema import BACKUP_ROOT, LOCAL_DB, LOCAL_WORKBOOK, SOURCE_WORKBOOK, STORAGE_ROOT
from app.services import seed_from_workbook_if_database_empty
from scripts.bootstrap import ensure_database, ensure_storage_layout, ensure_workbook_copy


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def main() -> None:
    remove_path(LOCAL_DB)
    remove_path(STORAGE_ROOT)
    remove_path(BACKUP_ROOT)
    if LOCAL_WORKBOOK.exists() and LOCAL_WORKBOOK != SOURCE_WORKBOOK:
        remove_path(LOCAL_WORKBOOK)

    ensure_workbook_copy()
    ensure_storage_layout()
    ensure_database()
    import_summary = seed_from_workbook_if_database_empty(LOCAL_DB, LOCAL_WORKBOOK)

    print("DealerOS local data reset complete.")
    print(f"Workbook ready: {LOCAL_WORKBOOK}")
    print(f"Database ready: {LOCAL_DB}")
    print(f"Storage ready: {STORAGE_ROOT}")
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
