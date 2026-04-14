# Workbook Export Strategy

## Export Model

- SQLite remains the live source of truth
- the workbook is regenerated as a copied export file from the preserved workbook template
- managed sheets are rewritten from the database using the original workbook column names
- unmanaged sheets remain untouched in the exported workbook so workbook-only data is not lost

## Managed Sheets

- `Front Sheet`
- `Stock Data`
- `Sold Stock`
- `Collection`
- `Investor Budget`
- `Expense`
- `Fuel Expense`
- `Investor Car Expense`
- `Money in`
- `Cash Spending`
- `Money Out`

## Unmanaged Sheets In This Phase

- `SOR`
- per-vehicle detail sheets

These are preserved from the template copy for now instead of being regenerated from SQLite.

## Export Output

- exports are written to `data/exports/`
- each export creates a new timestamped workbook file
- each run is recorded in `workbook_sync_runs` with `direction = export`

## Sync Surface

- `POST /api/sync/export-workbook` generates a new workbook export
- `POST /api/sync/import-workbook` rebuilds workbook-backed tables from the current local workbook copy
- imports create a timestamped SQLite backup first and preserve app-only operational records plus invoice history where possible
- `GET /api/sync/runs` returns recent import/export history for UI reporting
