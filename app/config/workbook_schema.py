from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_WORKBOOK = PROJECT_ROOT / "Master_Spreadsheet_TRIAL_sanitised.xlsx"
LOCAL_WORKBOOK = PROJECT_ROOT / "data" / "imports" / SOURCE_WORKBOOK.name
LOCAL_DB = PROJECT_ROOT / "data" / "dealeros.db"
STORAGE_ROOT = PROJECT_ROOT / "data" / "storage"
EXPORT_ROOT = PROJECT_ROOT / "data" / "exports"
BACKUP_ROOT = PROJECT_ROOT / "data" / "backups"

SUPPORTED_SHEETS = {
    "Front Sheet": [
        "Month",
        "Cars Sold",
        "Total Revenue",
        "Total Gross Profit",
        "Company Expenses",
        "Total SA Gross Profit",
        "Investor Net Profit",
        "Investor Expense",
        "Company Fuel Costs",
        "Other Money In",
        "Other Money Out",
        "Net Profit Exc Investor",
        "Net Exc Investor",
        "Notes",
    ],
    "Sold Stock": [
        "Month",
        "Date Aquired",
        "Number Plate reference",
        "Make & Model",
        "SA/Investor Name",
        "Total Cost",
        "Sold",
        "Part Ex",
        "SA/Investor Profit Share",
        "Total Profit",
        "Investor Profit",
        "SA Profit",
        "Date Listed",
        "Date Sold",
        "Days to Sell",
        "Platfrom",
        "Invoice Number",
        "Customer Name",
        "Contact info",
        "Warranty",
        "AutoGuard Number",
    ],
    "Stock Data": [
        "Month",
        "Date Aquired",
        "Plate Number",
        "Make & Model",
        "Investor/SA",
        "Source",
        "PX Value",
        "Price",
        "Reconditioning costs",
        "Total Cost",
        "Sold",
        "Profit",
        "Status",
    ],
    "Collection": [
        "Source",
        "Date Won",
        "Plate Number",
        "Make & Model",
        "Location",
        "Post Code",
        "How Far?",
        "Collection Date",
        "Number",
        "Additional notes",
    ],
    "Investor Budget": [
        "Investors",
        "Initial Balance",
        "Capital Returned",
        "Total Balance",
        "Purchased",
        "Total Profit (since Nov-25)",
        "Available",
    ],
    "SOR": [
        "Month",
        "Date Aquired",
        "Number Plate reference",
        "Make & Model",
        "Seller Name",
        "Total Cost",
        "Sale Price",
        "Breakdown",
    ],
    "Investor Car Expense": [
        "Month",
        "Date",
        "Reason",
        "Amount",
        "Reg",
    ],
    "Expense": [
        "Month",
        "Date",
        "Category",
        "From",
        "Amount ",
        "Payment Method",
        "Paid By",
        "Notes",
    ],
    "Fuel Expense": [
        "Month",
        "Date",
        "Car",
        "Amount ",
    ],
    "Money in": [
        "Month",
        "Date",
        "Category",
        "Amount ",
        "Reg",
        "Notes",
    ],
    "Cash Spending": [
        "Month",
        "Amount ",
        "Cost Incurred on",
        "Reason",
    ],
    "Money Out": [
        "Month",
        "Date",
        "Category",
        "Amount ",
        "Notes",
    ],
}

VEHICLE_FOLDER_TEMPLATE = [
    "Photos",
    "Documents",
    "ServiceHistory",
    "MOT",
    "Purchase",
    "Sale",
    "Delivery",
    "Collection",
]

INVESTOR_FOLDER_TEMPLATE = [
    "Documents",
    "Statements",
    "Invoices",
]

INVOICE_FOLDER_TEMPLATE = [
    "Sales",
    "Service",
    "Investor",
]

WORKBOOK_TO_INTERNAL_FIELDS = {
    "Sold Stock": {
        "Month": "month",
        "Date Aquired": "date_acquired",
        "Number Plate reference": "plate",
        "Make & Model": "model",
        "SA/Investor Name": "investor_name",
        "Total Cost": "total_cost",
        "Sold": "sold_price",
        "Part Ex": "part_exchange_value",
        "SA/Investor Profit Share": "profit_share",
        "Total Profit": "profit_total",
        "Investor Profit": "investor_profit",
        "SA Profit": "company_profit",
        "Date Listed": "date_listed",
        "Date Sold": "date_sold",
        "Days to Sell": "days_to_sell",
        "Platfrom": "platform",
        "Invoice Number": "invoice_number",
        "Customer Name": "customer_name",
        "Contact info": "contact_info",
        "Warranty": "warranty",
        "AutoGuard Number": "autoguard_number",
        "Stock ID": "stock_id",
    },
    "Stock Data": {
        "Month": "month",
        "Date Aquired": "date_acquired",
        "Plate Number": "plate",
        "Make & Model": "model",
        "Investor/SA": "investor_name",
        "Source": "source",
        "PX Value": "px_value",
        "Price": "purchase_price",
        "Reconditioning costs": "reconditioning_costs",
        "Total Cost": "total_cost",
        "Sold": "sold_price",
        "Profit": "profit_total",
        "Status": "status",
        "Stock ID": "stock_id",
    },
    "Collection": {
        "Source": "source",
        "Date Won": "date_won",
        "Plate Number": "plate",
        "Make & Model": "model",
        "Location": "location",
        "Post Code": "postcode",
        "How Far?": "distance_note",
        "Collection Date": "collection_date",
        "Number": "contact_number",
        "Additional notes": "notes",
        "Stock ID": "stock_id",
    },
    "Investor Budget": {
        "Investors": "name",
        "Initial Balance": "initial_balance",
        "Capital Returned": "capital_returned",
        "Total Balance": "total_balance",
        "Purchased": "purchased_total",
        "Total Profit (since Nov-25)": "profit_total",
        "Available": "available_balance",
    },
    "SOR": {
        "Month": "month",
        "Date Aquired": "date_acquired",
        "Number Plate reference": "plate",
        "Make & Model": "model",
        "Seller Name": "seller_name",
        "Total Cost": "total_cost",
        "Sale Price": "sale_price",
        "Breakdown": "breakdown",
        "Stock ID": "stock_id",
    },
    "Investor Car Expense": {
        "Month": "month",
        "Date": "date",
        "Reason": "reason",
        "Amount": "amount",
        "Reg": "reg",
        "Stock ID": "stock_id",
    },
    "Expense": {
        "Month": "month",
        "Date": "date",
        "Category": "category",
        "From": "from_name",
        "Amount ": "amount",
        "Payment Method": "payment_method",
        "Paid By": "paid_by",
        "Notes": "notes",
        "Stock ID": "stock_id",
    },
    "Fuel Expense": {
        "Month": "month",
        "Date": "date",
        "Car": "car_label",
        "Amount ": "amount",
        "Stock ID": "stock_id",
    },
    "Money in": {
        "Month": "month",
        "Date": "date",
        "Category": "category",
        "Amount ": "amount",
        "Reg": "reg",
        "Notes": "notes",
        "Stock ID": "stock_id",
    },
    "Cash Spending": {
        "Month": "month",
        "Amount ": "amount",
        "Cost Incurred on": "cost_incurred_on",
        "Reason": "reason",
        "Stock ID": "stock_id",
    },
    "Money Out": {
        "Month": "month",
        "Date": "date",
        "Category": "category",
        "Amount ": "amount",
        "Notes": "notes",
        "Stock ID": "stock_id",
    },
}


@dataclass(frozen=True)
class WorkbookSchemaSummary:
    supported_sheet_count: int
    source_workbook: str
    local_workbook: str
    local_db: str
    storage_root: str
    export_root: str
    backup_root: str


def build_schema_summary() -> WorkbookSchemaSummary:
    return WorkbookSchemaSummary(
        supported_sheet_count=len(SUPPORTED_SHEETS),
        source_workbook=str(SOURCE_WORKBOOK),
        local_workbook=str(LOCAL_WORKBOOK),
        local_db=str(LOCAL_DB),
        storage_root=str(STORAGE_ROOT),
        export_root=str(EXPORT_ROOT),
        backup_root=str(BACKUP_ROOT),
    )
