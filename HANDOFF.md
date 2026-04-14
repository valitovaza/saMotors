# DealerOS Reviewer Runbook

This file is written for a reviewer who wants the shortest path to testing the local Mac build.

## 1. Start Here

Run these in order:

1. `./verify.command`
2. `./start.command`
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

If you want a completely fresh local state before testing:

1. `./reset_and_reseed.command`
2. `./start.command`

## 2. What The Commands Do

- `./start.command`
  Creates or reuses `.venv`, installs dependencies only if missing, prepares local data folders, seeds the SQLite DB from the workbook if empty, and runs the app.
- `./reset_and_reseed.command`
  Deletes the local DB/storage/backups and rebuilds from the workbook copy.
- `./verify.command`
  Runs an automated acceptance flow:
  - bootstrap
  - create a test vehicle
  - create and update a viewing
  - create and remove a task
  - complete a sale
  - confirm invoice/file creation
  - export workbook
  - confirm sync history
  - restore the DB snapshot afterward

## 3. Local Data Layout

- `data/dealeros.db`
  Live SQLite database
- `data/imports/Master_Spreadsheet_TRIAL_sanitised.xlsx`
  Local workbook copy used for import/export
- `data/exports/`
  Timestamped workbook exports
- `data/backups/`
  Timestamped pre-import database backups
- `data/storage/Cars/<STOCK_ID>/`
  Real vehicle file tree

## 4. Minimum Manual Check

After the app loads in the browser:

1. Open `Stock`
2. Add a vehicle
3. Confirm a new folder exists under `data/storage/Cars/<STOCK_ID>/`
4. Upload a photo or document
5. Refresh the page and confirm the upload still exists
6. Open `Service History`, add a service record with a file, and confirm the file lands under that vehicle’s `ServiceHistory` folder
7. Open `Viewings`, add a viewing, then update its status
8. Open `Tasks`, add a task, mark it done, reset it, then delete it
9. Open `Sell a Car`, complete a sale, and confirm invoice output appears
10. Open `Reports`, export the workbook, and confirm a file appears in `data/exports/`
11. Open `Reports`, re-import the workbook, and confirm sync history updates

## 5. MOT / DVSA Check

Open `MOT Tracker`.

- `Check All via DVSA` now shows a non-blocking inline loader.
- Each MOT card has:
  - `DVSA`
  - `GOV.UK`

Expected behavior:

- On a network where DVSA accepts the request, the backend updates MOT data in SQLite.
- On a network blocked by DVSA’s Imperva/Incapsula layer, the app shows a clear message instead of raw HTML, and the reviewer can use the `GOV.UK` button for a manual MOT lookup.

This upstream block is not a local app failure.

## 6. Google Maps Check

Open `Collections & Deliveries` or `Routes & Planning`.

Expected:

- saved jobs have `Map` / `Open Maps` buttons
- route-planning rows open Google Maps directly
- grouped region rows open Google Maps

Autocomplete note:

- Google Maps Places autocomplete is implemented, but it needs a real `GOOGLE_MAPS_API_KEY` in `.env` to be active.
- Route links still work without that key.

## 7. Excel Sync Model

- SQLite is the live source of truth
- the workbook is the import/export format
- `Export Excel` writes a new timestamped workbook copy into `data/exports/`
- `Re-import Excel` rebuilds workbook-backed records from the workbook copy
- a DB backup is created before re-import
- app-only operational records and invoice history are preserved where possible

## 8. What Is Working

- stock and sold flows
- `stock_id` as the main unique key
- investors and allocations
- finance entries
- collections and deliveries
- service history
- viewings
- fines
- receipts
- staff and wages
- tasks
- sales and invoice generation
- file storage to real folders
- workbook import/export
- MOT tracker with backend DVSA integration and GOV.UK fallback
- Google Maps route-opening flow

## 9. Known Scope Limits

- Google Maps autocomplete requires a real Maps key to be enabled
- DVSA can be blocked by the reviewer IP/network due to Imperva/Incapsula
- Instagram is intentionally left as a prototype/example
- Auto Trader and Barclays are intentionally not treated as live production integrations in the final reviewer flow
- unmanaged workbook areas such as `SOR` and per-vehicle detail sheets are preserved rather than fully regenerated

## 10. Troubleshooting

- If port `8000` is already in use, stop the other local process and rerun `./start.command`
- If you want to reset everything, run `./reset_and_reseed.command`
- If you want the fastest proof that the project boots and the core flow works, run `./verify.command`
