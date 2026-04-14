from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from app.config.runtime import public_frontend_config
from app.config.workbook_schema import (
    EXPORT_ROOT,
    LOCAL_DB,
    LOCAL_WORKBOOK,
    PROJECT_ROOT,
    STORAGE_ROOT,
    SUPPORTED_SHEETS,
    WORKBOOK_TO_INTERNAL_FIELDS,
    build_schema_summary,
)
from app.db import apply_schema_migrations, schema_table_names
from app.services import (
    adjust_staff_owed,
    build_app_state,
    check_all_vehicle_mot,
    check_vehicle_mot,
    complete_sale,
    create_collection_delivery,
    create_custom_task,
    create_database_backup,
    create_fine,
    create_finance_entry,
    create_receipt,
    create_service_record,
    create_staff_member,
    create_vehicle,
    create_viewing,
    create_wage_payment,
    delete_custom_task,
    export_database_to_workbook,
    import_workbook_to_database,
    list_vehicles,
    list_vehicle_files,
    list_workbook_sync_runs,
    update_custom_task_status,
    upload_vehicle_file,
    update_fine_status,
    update_investor_total_balance,
    update_viewing_status,
)


app = FastAPI(title="DealerOS Local Backend", version="0.1.0")
apply_schema_migrations(LOCAL_DB)

frontend_dir = PROJECT_ROOT / "frontend"
index_file = frontend_dir / "index.html"

app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")
app.mount("/storage", StaticFiles(directory=STORAGE_ROOT), name="storage")


class VehicleCreateRequest(BaseModel):
    plate: str = Field(min_length=1)
    model: str = Field(min_length=1)
    source: str = ""
    investor: str = "MP"
    purchase_price: float = 0
    recon_cost: float = 0
    notes: str = ""


class FinanceEntryCreateRequest(BaseModel):
    plate: str = ""
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: float = Field(gt=0)
    entry_date: str = ""


class CollectionDeliveryCreateRequest(BaseModel):
    job_type: str = "Collection"
    plate: str = ""
    date_won: str = ""
    scheduled_date: str = ""
    address: str = ""
    maps_place_id: str = ""
    maps_latitude: float | None = None
    maps_longitude: float | None = None
    status: str = "Pending"
    notes: str = ""
    driver: str = ""
    cost: float = 0
    linked_vehicles: list[str] = []


class InvestorBalanceUpdateRequest(BaseModel):
    total_balance: float = Field(ge=0)


class DVSAPlateLookupRequest(BaseModel):
    plate: str = Field(min_length=1)


class SaleCompleteRequest(BaseModel):
    stock_id: str = Field(min_length=1)
    sale_price: float = Field(gt=0)
    sale_date: str = ""
    investor: str = "SA"
    profit_share_percent: float = Field(ge=0, le=100)
    html_snapshot: str = ""


class ServiceRecordCreateRequest(BaseModel):
    plate: str = ""
    record_type: str = Field(min_length=1)
    service_date: str = ""
    mileage: int = 0
    stamps: int = 0
    notes: str = ""


class ViewingCreateRequest(BaseModel):
    customer_name: str = Field(min_length=1)
    phone: str = ""
    vehicle_label: str = ""
    viewing_date: str = Field(min_length=1)
    viewing_time: str = ""
    notes: str = ""
    source: str = ""
    finance: str = ""
    delivery: str = ""


class FineCreateRequest(BaseModel):
    plate: str = ""
    fine_type: str = Field(min_length=1)
    fine_date: str = ""
    amount: float = Field(gt=0)
    due_date: str = ""
    reference: str = ""
    notes: str = ""


class FineStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=1)


class StaffCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    role: str = ""
    pay_type: str = "Per Job"
    rate: float = Field(ge=0)
    phone: str = ""


class StaffOwedUpdateRequest(BaseModel):
    amount_delta: float = Field(gt=0)


class WagePaymentCreateRequest(BaseModel):
    staff_id: int
    amount: float = Field(gt=0)
    payment_date: str = ""
    period: str = ""
    method: str = ""
    notes: str = ""


class CustomTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    due_date: str = ""
    priority: str = "Normal"
    notes: str = ""


class StatusUpdateRequest(BaseModel):
    status: str = Field(min_length=1)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "frontend_exists": index_file.exists(),
        "db_exists": LOCAL_DB.exists(),
        "workbook_exists": LOCAL_WORKBOOK.exists(),
        "storage_exists": STORAGE_ROOT.exists(),
    }


@app.get("/api/debug/db-status")
def debug_db_status() -> dict[str, object]:
    """Diagnostic endpoint to check database status and app-created vehicles."""
    from app.db import checkpoint_wal, connect_sqlite
    
    try:
        # Checkpoint WAL
        checkpoint_wal(LOCAL_DB)
        
        # Check vehicle counts
        conn = connect_sqlite(LOCAL_DB)
        total = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
        app_created = conn.execute(
            "SELECT COUNT(*) FROM vehicles WHERE workbook_primary_sheet = 'App Manual Entry'"
        ).fetchone()[0]
        in_stock = conn.execute(
            "SELECT COUNT(*) FROM vehicles WHERE status = 'In Stock' AND workbook_primary_sheet = 'App Manual Entry'"
        ).fetchone()[0]
        conn.close()
        
        # Get state count
        state = build_app_state(LOCAL_DB)
        stock_count = len(state.get("stock", []))
        
        return {
            "status": "ok",
            "database": {
                "total_vehicles": total,
                "app_created_total": app_created,
                "app_created_in_stock": in_stock,
            },
            "api_state": {
                "stock_count": stock_count,
            },
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/api/bootstrap")
def bootstrap_status() -> dict[str, object]:
    summary = build_schema_summary()
    return {
        "summary": summary.__dict__,
        "database_tables": schema_table_names(),
        "supported_sheets": SUPPORTED_SHEETS,
        "field_mappings": WORKBOOK_TO_INTERNAL_FIELDS,
    }


@app.get("/api/frontend-config")
def frontend_config() -> dict[str, object]:
    return public_frontend_config()


@app.post("/api/sync/export-workbook")
def export_workbook() -> dict[str, object]:
    try:
        summary = export_database_to_workbook(
            db_path=LOCAL_DB, template_workbook_path=LOCAL_WORKBOOK
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "status": "created",
        "export": {
            "filename": summary.filename,
            "path": summary.workbook_path,
            "download_url": f"/api/sync/exports/{summary.filename}",
            "sync_run_id": summary.sync_run_id,
            "exported_sheets": summary.exported_sheets,
            "untouched_sheets": summary.untouched_sheets,
            "rows_written": summary.rows_written,
        },
    }


@app.post("/api/sync/import-workbook")
def import_workbook() -> dict[str, object]:
    if not LOCAL_WORKBOOK.exists():
        raise HTTPException(
            status_code=400, detail="Local workbook template does not exist."
        )
    backup = create_database_backup(LOCAL_DB)
    summary = import_workbook_to_database(LOCAL_DB, LOCAL_WORKBOOK)
    return {
        "status": "completed",
        "import": {
            "workbook_path": summary.workbook_path,
            "sync_run_id": summary.sync_run_id,
            "vehicles_created": summary.vehicles_created,
            "investors_created": summary.investors_created,
            "allocations_created": summary.allocations_created,
            "vehicle_expenses_created": summary.vehicle_expenses_created,
            "collection_jobs_created": summary.collection_jobs_created,
            "money_movements_created": summary.money_movements_created,
            "preserved_links_restored": summary.preserved_links_restored,
            "validation": summary.validation,
            "backup": (
                {
                    "filename": backup.filename,
                    "path": backup.backup_path,
                }
                if backup is not None
                else None
            ),
        },
    }


@app.get("/api/sync/runs")
def sync_runs(limit: int = 20) -> dict[str, object]:
    rows = list_workbook_sync_runs(LOCAL_DB, limit=max(1, min(limit, 100)))
    return {"items": rows, "count": len(rows)}


@app.get("/api/sync/exports/{filename}")
def download_export(filename: str) -> FileResponse:
    target = (EXPORT_ROOT / filename).resolve()
    exports_root = EXPORT_ROOT.resolve()
    if exports_root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Export not found.")
    return FileResponse(target, filename=target.name)


@app.get("/api/state")
def app_state() -> JSONResponse:
    state = build_app_state(LOCAL_DB)
    return JSONResponse(
        content=state,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/api/vehicles")
def vehicles() -> dict[str, object]:
    rows = list_vehicles(LOCAL_DB)
    return {"items": rows, "count": len(rows)}


@app.post("/api/vehicles")
def add_vehicle(payload: VehicleCreateRequest) -> dict[str, object]:
    try:
        vehicle = create_vehicle(
            plate=payload.plate,
            model=payload.model,
            source=payload.source,
            investor_name=payload.investor,
            purchase_price=payload.purchase_price,
            recon_cost=payload.recon_cost,
            notes=payload.notes,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"status": "created", "vehicle": vehicle}


@app.post("/api/finance/entries")
def add_finance_entry(payload: FinanceEntryCreateRequest) -> dict[str, object]:
    try:
        create_finance_entry(
            plate=payload.plate,
            category=payload.category,
            description=payload.description,
            amount=payload.amount,
            entry_date=payload.entry_date,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.post("/api/collections-deliveries")
def add_collection_delivery(
    payload: CollectionDeliveryCreateRequest,
) -> dict[str, object]:
    try:
        create_collection_delivery(
            job_type=payload.job_type,
            plate=payload.plate,
            date_won=payload.date_won,
            scheduled_date=payload.scheduled_date,
            address=payload.address,
            maps_place_id=payload.maps_place_id,
            maps_latitude=payload.maps_latitude,
            maps_longitude=payload.maps_longitude,
            status=payload.status,
            notes=payload.notes,
            driver=payload.driver,
            cost=payload.cost,
            linked_vehicles=payload.linked_vehicles,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.put("/api/investors/{investor_id}")
def update_investor_budget(
    investor_id: int, payload: InvestorBalanceUpdateRequest
) -> dict[str, object]:
    try:
        investor = update_investor_total_balance(
            investor_id=investor_id,
            total_balance=payload.total_balance,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "updated", "investor": investor}


@app.post("/api/dvsa/check/{stock_id}")
def check_vehicle_mot_by_stock_id(stock_id: str) -> dict[str, object]:
    try:
        result = check_vehicle_mot(stock_id=stock_id, db_path=LOCAL_DB)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "checked",
        "vehicle": {
            "stock_id": result.stock_id,
            "plate": result.plate,
            "mot_expiry": result.mot_expiry,
            "mot_status": result.mot_status,
            "mot_last_result": result.mot_last_result,
            "mot_last_checked": result.mot_last_checked,
            "mot_advisories": result.advisories,
        },
    }


@app.post("/api/dvsa/check-by-plate")
def check_vehicle_mot_by_plate(payload: DVSAPlateLookupRequest) -> dict[str, object]:
    try:
        result = check_vehicle_mot(plate=payload.plate, db_path=LOCAL_DB)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "status": "checked",
        "vehicle": {
            "stock_id": result.stock_id,
            "plate": result.plate,
            "mot_expiry": result.mot_expiry,
            "mot_status": result.mot_status,
            "mot_last_result": result.mot_last_result,
            "mot_last_checked": result.mot_last_checked,
            "mot_advisories": result.advisories,
        },
    }


@app.post("/api/dvsa/check-all")
def check_all_mot() -> dict[str, object]:
    try:
        result = check_all_vehicle_mot(db_path=LOCAL_DB)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "completed", **result}


@app.post("/api/sales/complete")
def finalize_sale(payload: SaleCompleteRequest) -> dict[str, object]:
    try:
        result = complete_sale(
            stock_id=payload.stock_id,
            sale_price=payload.sale_price,
            sale_date=payload.sale_date,
            investor_name=payload.investor,
            profit_share_percent=payload.profit_share_percent,
            html_snapshot=payload.html_snapshot,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "completed", **result}


@app.post("/api/service-records")
async def add_service_record(
    plate: str = Form(""),
    record_type: str = Form("Service"),
    service_date: str = Form(""),
    mileage: str = Form(""),
    stamps: str = Form(""),
    notes: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict[str, object]:
    try:
        mileage_value = int((mileage or "0").strip() or "0")
        stamps_value = int((stamps or "0").strip() or "0")
        create_service_record(
            plate=plate,
            record_type=record_type,
            service_date=service_date,
            mileage=mileage_value,
            stamps=stamps_value,
            notes=notes,
            file_name=file.filename if file else None,
            mime_type=file.content_type if file else None,
            content=await file.read() if file else None,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.post("/api/viewings")
def add_viewing(payload: ViewingCreateRequest) -> dict[str, object]:
    try:
        create_viewing(
            customer_name=payload.customer_name,
            phone=payload.phone,
            vehicle_label=payload.vehicle_label,
            viewing_date=payload.viewing_date,
            viewing_time=payload.viewing_time,
            notes=payload.notes,
            source=payload.source,
            finance=payload.finance,
            delivery=payload.delivery,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.patch("/api/viewings/{viewing_id}")
def patch_viewing_status(
    viewing_id: int, payload: StatusUpdateRequest
) -> dict[str, object]:
    try:
        update_viewing_status(
            viewing_id=viewing_id, status=payload.status, db_path=LOCAL_DB
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "updated"}


@app.post("/api/fines")
def add_fine(payload: FineCreateRequest) -> dict[str, object]:
    try:
        create_fine(
            plate=payload.plate,
            fine_type=payload.fine_type,
            fine_date=payload.fine_date,
            amount=payload.amount,
            due_date=payload.due_date,
            reference=payload.reference,
            notes=payload.notes,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.patch("/api/fines/{fine_id}")
def patch_fine_status(
    fine_id: int, payload: FineStatusUpdateRequest
) -> dict[str, object]:
    try:
        update_fine_status(fine_id=fine_id, status=payload.status, db_path=LOCAL_DB)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "updated"}


@app.post("/api/receipts")
async def add_receipt(
    plate: str = Form(""),
    category: str = Form("Other"),
    notes: str = Form(""),
    amount: float = Form(...),
    receipt_date: str = Form(""),
    file: UploadFile | None = File(None),
) -> dict[str, object]:
    try:
        create_receipt(
            plate=plate,
            category=category,
            notes=notes,
            amount=amount,
            receipt_date=receipt_date,
            file_name=file.filename if file else None,
            mime_type=file.content_type if file else None,
            content=await file.read() if file else None,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.post("/api/staff")
def add_staff_member(payload: StaffCreateRequest) -> dict[str, object]:
    try:
        create_staff_member(
            name=payload.name,
            role=payload.role,
            pay_type=payload.pay_type,
            rate=payload.rate,
            phone=payload.phone,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.post("/api/staff/{staff_id}/owed")
def add_staff_owed(staff_id: int, payload: StaffOwedUpdateRequest) -> dict[str, object]:
    try:
        adjust_staff_owed(
            staff_id=staff_id, amount_delta=payload.amount_delta, db_path=LOCAL_DB
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "updated"}


@app.post("/api/wage-payments")
def add_wage_payment(payload: WagePaymentCreateRequest) -> dict[str, object]:
    try:
        create_wage_payment(
            staff_id=payload.staff_id,
            amount=payload.amount,
            payment_date=payload.payment_date,
            period=payload.period,
            method=payload.method,
            notes=payload.notes,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.post("/api/custom-tasks")
def add_custom_task(payload: CustomTaskCreateRequest) -> dict[str, object]:
    try:
        create_custom_task(
            title=payload.title,
            due_date=payload.due_date,
            priority=payload.priority,
            notes=payload.notes,
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created"}


@app.patch("/api/custom-tasks/{task_id}")
def patch_custom_task(task_id: int, payload: StatusUpdateRequest) -> dict[str, object]:
    try:
        update_custom_task_status(
            task_id=task_id, status=payload.status, db_path=LOCAL_DB
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "updated"}


@app.delete("/api/custom-tasks/{task_id}")
def remove_custom_task(task_id: int) -> dict[str, object]:
    try:
        delete_custom_task(task_id=task_id, db_path=LOCAL_DB)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}


@app.get("/api/vehicles/{stock_id}/files")
def vehicle_files(stock_id: str, category: str | None = None) -> dict[str, object]:
    return {
        "items": list_vehicle_files(
            stock_id=stock_id, category=category, db_path=LOCAL_DB
        )
    }


@app.post("/api/vehicles/{stock_id}/files")
async def upload_vehicle_media(
    stock_id: str,
    file: UploadFile = File(...),
    category: str = Form("Documents"),
) -> dict[str, object]:
    try:
        payload = upload_vehicle_file(
            stock_id=stock_id,
            category=category,
            original_name=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            content=await file.read(),
            db_path=LOCAL_DB,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "created", "file": payload}


@app.get("/")
def root() -> FileResponse:
    return FileResponse(
        index_file,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/{full_path:path}")
def spa_fallback(full_path: str) -> FileResponse:
    requested_path = frontend_dir / full_path
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if requested_path.is_file():
        return FileResponse(requested_path, headers=no_cache_headers)
    return FileResponse(index_file, headers=no_cache_headers)
