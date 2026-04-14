from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.workbook_schema import EXPORT_ROOT, LOCAL_DB


def run_bootstrap(python_bin: str) -> None:
    subprocess.run([python_bin, str(PROJECT_ROOT / "scripts" / "bootstrap.py")], check=True, cwd=PROJECT_ROOT)


def as_json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    body = getattr(value, "body", None)
    if body is None:
        raise TypeError(f"Unsupported payload type: {type(value)!r}")
    return json.loads(body.decode("utf-8"))


def restore_db(backup_path: Path | None, db_existed: bool) -> None:
    if backup_path and backup_path.exists():
        LOCAL_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, LOCAL_DB)
    elif not db_existed and LOCAL_DB.exists():
        LOCAL_DB.unlink()


def main() -> None:
    python_bin = sys.executable
    db_existed = LOCAL_DB.exists()
    db_backup_path = Path("/tmp/dealeros_acceptance_check.db.bak") if db_existed else None
    if db_backup_path and LOCAL_DB.exists():
        shutil.copy2(LOCAL_DB, db_backup_path)

    run_bootstrap(python_bin)

    try:
        from app.main import (
            CustomTaskCreateRequest,
            SaleCompleteRequest,
            StatusUpdateRequest,
            VehicleCreateRequest,
            ViewingCreateRequest,
            add_custom_task,
            app_state,
            add_viewing,
            bootstrap_status,
            export_workbook,
            finalize_sale,
            health,
            patch_custom_task,
            patch_viewing_status,
            remove_custom_task,
            sync_runs,
            vehicle_files,
            add_vehicle,
        )

        health_payload = health()
        assert health_payload["status"] == "ok"
        assert health_payload["frontend_exists"] and health_payload["db_exists"]

        bootstrap_payload = bootstrap_status()
        assert bootstrap_payload["summary"]["supported_sheet_count"] >= 10

        state_payload = as_json_payload(app_state())
        assert len(state_payload.get("stock", [])) > 0

        unique_plate = f"TS{int(time.time()) % 90 + 10}CHK"
        create_payload = add_vehicle(
            VehicleCreateRequest(
                plate=unique_plate,
                model="Acceptance Check Hatchback",
                source="Acceptance Test",
                investor="MP",
                purchase_price=2500,
                recon_cost=150,
                notes="Acceptance flow test",
            )
        )
        stock_id = create_payload["vehicle"]["stock_id"]

        viewing_create_payload = add_viewing(
            ViewingCreateRequest(
                customer_name="Acceptance Buyer",
                phone="07000000000",
                vehicle_label=f"Acceptance Check Hatchback · {unique_plate}",
                viewing_date="2026-04-14",
                viewing_time="11:00",
                notes="Acceptance viewing flow",
                source="Website",
                finance="Cash",
                delivery="No",
            )
        )
        assert viewing_create_payload["status"] == "created"
        state_after_viewing = as_json_payload(app_state())
        viewing_id = next(item["id"] for item in state_after_viewing["viewings"] if item["name"] == "Acceptance Buyer")
        patch_viewing_status(viewing_id, StatusUpdateRequest(status="Bought"))

        task_create_payload = add_custom_task(
            CustomTaskCreateRequest(
                title="Acceptance Task",
                due_date="2026-04-20",
                priority="High",
                notes="Acceptance task flow",
            )
        )
        assert task_create_payload["status"] == "created"
        state_after_task = as_json_payload(app_state())
        task_id = next(item["id"] for item in state_after_task["custom_tasks"] if item["title"] == "Acceptance Task")
        patch_custom_task(task_id, StatusUpdateRequest(status="Done"))
        remove_custom_task(task_id)

        sale_payload = finalize_sale(
            SaleCompleteRequest(
                stock_id=stock_id,
                sale_price=3950,
                sale_date="2026-04-14",
                investor="MP",
                profit_share_percent=50,
                html_snapshot="<div>Acceptance invoice</div>",
            )
        )
        invoice_number = sale_payload["invoice"]["invNum"]

        files_payload = vehicle_files(stock_id)
        assert len(files_payload.get("items", [])) >= 2

        export_payload = export_workbook()
        export_file = export_payload["export"]["filename"]
        assert (EXPORT_ROOT / export_file).exists()

        runs_payload = sync_runs(limit=5)
        assert runs_payload["count"] >= 1

        final_state = as_json_payload(app_state())
        assert any(item["stock_id"] == stock_id for item in final_state.get("sold", []))
        assert any(item["name"] == "Acceptance Buyer" and item["status"] == "Bought" for item in final_state.get("viewings", []))
        assert not any(item["title"] == "Acceptance Task" for item in final_state.get("custom_tasks", []))

        print(
            json.dumps(
                {
                    "status": "ok",
                    "stock_id": stock_id,
                    "invoice_number": invoice_number,
                    "export_file": export_file,
                    "sync_runs_checked": runs_payload["count"],
                },
                indent=2,
            )
        )
    finally:
        restore_db(db_backup_path, db_existed)


if __name__ == "__main__":
    main()
