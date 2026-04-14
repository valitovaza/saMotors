# DealerOS Trial Delivery

This repository is packaged for local Mac testing with a project-local Python virtual environment so reviewers do not need to install anything globally.

## Fastest Review Path

1. Run `./verify.command`
2. Run `./start.command`
3. Open [http://127.0.0.1:8000](http://127.0.0.1:8000)
4. Follow the manual checks in `HANDOFF.md`

## Commands

- `./start.command`
  Creates or reuses the local `.venv`, installs Python dependencies only if missing, bootstraps the local DB/workbook/storage, and starts the app on `127.0.0.1:8000`.
- `./reset_and_reseed.command`
  Rebuilds the local database and storage from the workbook copy. Use this when you want a fresh reviewer state.
- `./verify.command`
  Runs the packaged automated acceptance check and restores the DB snapshot afterward.

## Reviewer Notes

- The app is designed to run locally on macOS with no global Python package changes.
- The virtual environment is inside the repo at `.venv/`.
- The local database is `data/dealeros.db`.
- The local workbook copy is `data/imports/Master_Spreadsheet_TRIAL_sanitised.xlsx`.
- Vehicle files are written to real folders under `data/storage/Cars/<STOCK_ID>/`.

## Core Delivered Scope

- Preserved existing HTML UI and navigation while moving core flows to a local backend
- `stock_id` as the system-wide unique key
- SQLite-backed stock, sold vehicles, investors, finance, collections/deliveries, service history, viewings, fines, receipts, wages, tasks, invoices, and file storage
- Real folder creation for vehicles and persisted file uploads
- Workbook import/export and sync history
- One-command local startup for reviewers

## Important Integration Notes

- DVSA is wired through the backend and defaults to the provided credentials.
- Some networks are blocked upstream by DVSA’s Imperva/Incapsula layer. In that case the app shows a clear fallback message and reviewers can use the `GOV.UK` button on the MOT card instead.
- Google Maps route links work without extra setup.
- Google Maps autocomplete is code-complete but requires a real `GOOGLE_MAPS_API_KEY` to be placed in `.env` if live autocomplete is desired.
- Instagram remains intentionally marked as a prototype/example.
- Auto Trader and Barclays are intentionally not exposed as live reviewer-critical flows.

## Handoff

Read `HANDOFF.md` for:

- step-by-step reviewer instructions
- manual QA checklist
- sync behavior
- known scope limits
