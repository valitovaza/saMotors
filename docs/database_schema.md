# Database Schema

This schema is the internal source of truth for DealerOS. Excel remains the import and export contract, but the live application state will be stored in SQLite.

## Design Rules

- `stock_id` is the primary vehicle identity across the system
- `plate` is a normal mutable vehicle field, not the system key
- workbook-facing names stay in the import/export layer
- all operational tables reference the internal vehicle row through foreign keys
- source workbook sheet and row metadata are preserved where round-trip sync will need them

## Tables

### `vehicles`

- one row per vehicle
- unique `stock_id`
- cached sale and profit fields for fast UI reads
- workbook origin metadata

### `investors`

- one row per investor
- cached balance fields aligned to the `Investor Budget` workbook

### `vehicle_investor_allocations`

- links vehicles to investors
- stores capital allocation and profit split

### `vehicle_expenses`

- normalized per-vehicle cost ledger
- supports workbook main-sheet rows and per-vehicle detail-sheet rows

### `collections_deliveries`

- tracks collection and delivery operations
- links back to vehicles when matched

### `money_movements`

- normalized finance movement log
- supports money in, money out, and related finance sheets

### `invoices`

- generated invoice records with printable HTML snapshot and stored file path

### `document_files`

- tracks files saved to real folders on disk
- can link to vehicles, investors, and invoices

### `workbook_sync_runs`

- audit log for workbook imports and exports

## Next Phase

The next step after this schema is the importer that reads the workbook, generates `stock_id` values, resolves duplicates, and populates these tables.
