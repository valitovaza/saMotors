# Workbook Schema Lock

This document locks the external workbook schema for DealerOS so the implementation follows the workbook's field names and structure instead of inventing new business terminology.

## Rules

- workbook sheet names remain the external integration contract
- workbook column names remain the export contract
- internal database names may be normalized only through explicit mappings
- `stock_id` is the only required business identifier added across supported sheets

## Supported Sheets

### Front Sheet

- `Month`
- `Cars Sold`
- `Total Revenue`
- `Total Gross Profit`
- `Company Expenses`
- `Total SA Gross Profit`
- `Investor Net Profit`
- `Investor Expense`
- `Company Fuel Costs`
- `Other Money In`
- `Other Money Out`
- `Net Profit Exc Investor`
- `Net Exc Investor`
- `Notes`

### Sold Stock

- `Month`
- `Date Aquired`
- `Number Plate reference`
- `Make & Model`
- `SA/Investor Name`
- `Total Cost`
- `Sold`
- `Part Ex`
- `SA/Investor Profit Share`
- `Total Profit`
- `Investor Profit`
- `SA Profit`
- `Date Listed`
- `Date Sold`
- `Days to Sell`
- `Platfrom`
- `Invoice Number`
- `Customer Name`
- `Contact info`
- `Warranty`
- `AutoGuard Number`
- `Stock ID` (new)

### Stock Data

- `Month`
- `Date Aquired`
- `Plate Number`
- `Make & Model`
- `Investor/SA`
- `Source`
- `PX Value`
- `Price`
- `Reconditioning costs`
- `Total Cost`
- `Sold`
- `Profit`
- `Status`
- `Stock ID` (new)

### Collection

- `Source`
- `Date Won`
- `Plate Number`
- `Make & Model`
- `Location`
- `Post Code`
- `How Far?`
- `Collection Date`
- `Number`
- `Additional notes`
- `Stock ID` (new)

### Investor Budget

- `Investors`
- `Initial Balance`
- `Capital Returned`
- `Total Balance`
- `Purchased`
- `Total Profit (since Nov-25)`
- `Available`

### SOR

- `Month`
- `Date Aquired`
- `Number Plate reference`
- `Make & Model`
- `Seller Name`
- `Total Cost`
- `Sale Price`
- `Breakdown`
- `Stock ID` (new)

### Investor Car Expense

- `Month`
- `Date`
- `Reason`
- `Amount`
- `Reg`
- `Stock ID` (new)

### Expense

- `Month`
- `Date`
- `Category`
- `From`
- `Amount `
- `Payment Method`
- `Paid By`
- `Notes`
- `Stock ID` (new where a vehicle link exists)

### Fuel Expense

- `Month`
- `Date`
- `Car`
- `Amount `
- `Stock ID` (new where a vehicle link exists)

### Money in

- `Month`
- `Date`
- `Category`
- `Amount `
- `Reg`
- `Notes`
- `Stock ID` (new where a vehicle link exists)

### Cash Spending

- `Month`
- `Amount `
- `Cost Incurred on`
- `Reason`
- `Stock ID` (new where a vehicle link exists)

### Money Out

- `Month`
- `Date`
- `Category`
- `Amount `
- `Notes`
- `Stock ID` (new where a vehicle link exists)

## Notes

- per-vehicle sheets remain part of the import/export strategy because they carry real cost breakdown data
- internal models may use normalized names like `date_acquired`, but export must restore workbook names exactly
- no extra business-facing fields should be introduced unless the workbook clearly lacks them
