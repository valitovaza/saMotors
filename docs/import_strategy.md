# Workbook Import Strategy

## Current Import Scope

- `Stock Data` and `Sold Stock` become normalized vehicle records
- `Investor Budget` becomes investor records
- `Collection` becomes collection jobs
- `Expense`, `Fuel Expense`, and `Investor Car Expense` become vehicle expenses when a vehicle link is resolvable
- `Money in`, `Money Out`, and `Cash Spending` become normalized money movements
- per-vehicle sheets become detail-sheet vehicle expenses when a vehicle can be matched

## `stock_id` Generation

- `stock_id` is generated deterministically from a vehicle fingerprint
- the fingerprint uses plate, display name, acquisition date, sold date, month, source sheet, and row reference
- this avoids using plate as the identity while remaining stable for repeated imports of the same workbook layout

## Validation Behavior

The importer records:

- duplicate plate candidates
- ambiguous plate references from supporting sheets
- unmatched detail sheets that could not be linked to a vehicle

## Known Limitations In This Phase

- duplicate or low-quality workbook rows are reported, not auto-merged beyond the current fingerprint strategy
- ambiguous expense rows that only contain weak text references are skipped instead of guessed
- invoice and file records are not created from workbook sheets because the workbook does not contain proper backend file metadata
- invoice history and linked file records created inside the app are preserved across workbook re-import where possible
