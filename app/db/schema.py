from __future__ import annotations

from collections import OrderedDict


TABLE_DEFINITIONS: "OrderedDict[str, str]" = OrderedDict(
    [
        (
            "app_metadata",
            """
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        ),
        (
            "vehicles",
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stock_id TEXT NOT NULL UNIQUE,
                plate TEXT,
                plate_normalized TEXT,
                make TEXT,
                model TEXT,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'In Stock',
                source TEXT,
                date_acquired TEXT,
                date_listed TEXT,
                date_sold TEXT,
                mot_expiry TEXT,
                mot_status TEXT,
                mot_last_result TEXT,
                mot_last_checked TEXT,
                mot_advisories_json TEXT,
                purchase_price REAL NOT NULL DEFAULT 0,
                px_value REAL NOT NULL DEFAULT 0,
                reconditioning_costs REAL NOT NULL DEFAULT 0,
                total_cost_cached REAL NOT NULL DEFAULT 0,
                sold_price REAL NOT NULL DEFAULT 0,
                profit_total_cached REAL NOT NULL DEFAULT 0,
                customer_name TEXT,
                contact_info TEXT,
                warranty TEXT,
                autoguard_number TEXT,
                platform TEXT,
                invoice_number TEXT,
                notes TEXT,
                workbook_primary_sheet TEXT,
                workbook_row_ref TEXT,
                folder_path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "investors",
            """
            CREATE TABLE IF NOT EXISTS investors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                initial_balance REAL NOT NULL DEFAULT 0,
                capital_returned REAL NOT NULL DEFAULT 0,
                total_balance_cached REAL NOT NULL DEFAULT 0,
                purchased_total_cached REAL NOT NULL DEFAULT 0,
                profit_total_cached REAL NOT NULL DEFAULT 0,
                available_balance_cached REAL NOT NULL DEFAULT 0,
                notes TEXT,
                workbook_primary_sheet TEXT,
                workbook_row_ref TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "vehicle_investor_allocations",
            """
            CREATE TABLE IF NOT EXISTS vehicle_investor_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                investor_id INTEGER NOT NULL,
                allocation_role TEXT NOT NULL DEFAULT 'primary',
                capital_amount REAL NOT NULL DEFAULT 0,
                profit_share_percent REAL NOT NULL DEFAULT 0,
                investor_profit_amount REAL NOT NULL DEFAULT 0,
                company_profit_amount REAL NOT NULL DEFAULT 0,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE,
                FOREIGN KEY (investor_id) REFERENCES investors(id) ON DELETE CASCADE,
                UNIQUE (vehicle_id, investor_id, allocation_role)
            )
            """,
        ),
        (
            "vehicle_expenses",
            """
            CREATE TABLE IF NOT EXISTS vehicle_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                expense_scope TEXT NOT NULL DEFAULT 'vehicle',
                expense_type TEXT NOT NULL DEFAULT 'expense',
                category TEXT,
                description TEXT NOT NULL,
                vendor TEXT,
                amount REAL NOT NULL,
                payment_method TEXT,
                paid_by TEXT,
                expense_date TEXT,
                source_sheet TEXT,
                source_row_ref TEXT,
                workbook_detail_sheet TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
            )
            """,
        ),
        (
            "collections_deliveries",
            """
            CREATE TABLE IF NOT EXISTS collections_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER,
                job_type TEXT NOT NULL,
                source TEXT,
                date_won TEXT,
                scheduled_date TEXT,
                completed_date TEXT,
                address TEXT,
                maps_place_id TEXT,
                maps_latitude REAL,
                maps_longitude REAL,
                postcode TEXT,
                distance_note TEXT,
                contact_number TEXT,
                status TEXT NOT NULL DEFAULT 'Pending',
                notes TEXT,
                source_sheet TEXT,
                source_row_ref TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "money_movements",
            """
            CREATE TABLE IF NOT EXISTS money_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER,
                direction TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                movement_date TEXT,
                payment_method TEXT,
                counterparty TEXT,
                notes TEXT,
                source_sheet TEXT,
                source_row_ref TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "invoices",
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                invoice_type TEXT NOT NULL,
                invoice_number TEXT NOT NULL UNIQUE,
                invoice_date TEXT,
                customer_name TEXT,
                contact_info TEXT,
                warranty TEXT,
                autoguard_number TEXT,
                stock_id TEXT,
                amount_total REAL NOT NULL DEFAULT 0,
                profit_total REAL NOT NULL DEFAULT 0,
                investor_profit_amount REAL NOT NULL DEFAULT 0,
                company_profit_amount REAL NOT NULL DEFAULT 0,
                html_snapshot TEXT,
                file_path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
            )
            """,
        ),
        (
            "document_files",
            """
            CREATE TABLE IF NOT EXISTS document_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                vehicle_id INTEGER,
                investor_id INTEGER,
                invoice_id INTEGER,
                stock_id TEXT,
                category TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL,
                FOREIGN KEY (investor_id) REFERENCES investors(id) ON DELETE SET NULL,
                FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "workbook_sync_runs",
            """
            CREATE TABLE IF NOT EXISTS workbook_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                direction TEXT NOT NULL,
                status TEXT NOT NULL,
                source_path TEXT,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                summary_json TEXT,
                conflicts_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "service_records",
            """
            CREATE TABLE IF NOT EXISTS service_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER,
                plate TEXT,
                record_type TEXT NOT NULL,
                service_date TEXT,
                mileage INTEGER NOT NULL DEFAULT 0,
                stamps INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                photo_path TEXT,
                reference TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "viewings",
            """
            CREATE TABLE IF NOT EXISTS viewings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER,
                vehicle_plate TEXT,
                vehicle_label TEXT,
                customer_name TEXT NOT NULL,
                phone TEXT,
                viewing_date TEXT NOT NULL,
                viewing_time TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'Booked',
                source TEXT,
                finance TEXT,
                delivery TEXT,
                outcome TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "fines",
            """
            CREATE TABLE IF NOT EXISTS fines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER,
                plate TEXT,
                fine_type TEXT NOT NULL,
                fine_date TEXT,
                amount REAL NOT NULL DEFAULT 0,
                due_date TEXT,
                reference TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'Unpaid',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "receipts",
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER,
                plate TEXT,
                category TEXT NOT NULL,
                notes TEXT,
                amount REAL NOT NULL DEFAULT 0,
                receipt_date TEXT NOT NULL,
                image_path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
            )
            """,
        ),
        (
            "staff_members",
            """
            CREATE TABLE IF NOT EXISTS staff_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                role TEXT,
                pay_type TEXT NOT NULL,
                rate REAL NOT NULL DEFAULT 0,
                phone TEXT,
                owed_amount REAL NOT NULL DEFAULT 0,
                paid_total REAL NOT NULL DEFAULT 0,
                linked_plate TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
        (
            "wage_payments",
            """
            CREATE TABLE IF NOT EXISTS wage_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                staff_id INTEGER NOT NULL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                period TEXT,
                method TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (staff_id) REFERENCES staff_members(id) ON DELETE CASCADE
            )
            """,
        ),
        (
            "custom_tasks",
            """
            CREATE TABLE IF NOT EXISTS custom_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_date TEXT,
                priority TEXT NOT NULL DEFAULT 'Normal',
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'Pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ),
    ]
)


INDEX_DEFINITIONS = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_vehicles_stock_id ON vehicles(stock_id)",
    "CREATE INDEX IF NOT EXISTS idx_vehicles_plate_normalized ON vehicles(plate_normalized)",
    "CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_investors_name ON investors(name COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_allocations_vehicle_id ON vehicle_investor_allocations(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_allocations_investor_id ON vehicle_investor_allocations(investor_id)",
    "CREATE INDEX IF NOT EXISTS idx_vehicle_expenses_vehicle_id ON vehicle_expenses(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_vehicle_expenses_date ON vehicle_expenses(expense_date)",
    "CREATE INDEX IF NOT EXISTS idx_collections_vehicle_id ON collections_deliveries(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_collections_status ON collections_deliveries(status)",
    "CREATE INDEX IF NOT EXISTS idx_money_movements_vehicle_id ON money_movements(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_money_movements_date ON money_movements(movement_date)",
    "CREATE INDEX IF NOT EXISTS idx_invoices_vehicle_id ON invoices(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_invoices_stock_id ON invoices(stock_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_invoice_number ON invoices(invoice_number)",
    "CREATE INDEX IF NOT EXISTS idx_document_files_stock_id ON document_files(stock_id)",
    "CREATE INDEX IF NOT EXISTS idx_document_files_entity ON document_files(entity_type, entity_id)",
    "CREATE INDEX IF NOT EXISTS idx_workbook_sync_runs_direction ON workbook_sync_runs(direction)",
    "CREATE INDEX IF NOT EXISTS idx_service_records_vehicle_id ON service_records(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_service_records_date ON service_records(service_date)",
    "CREATE INDEX IF NOT EXISTS idx_viewings_vehicle_id ON viewings(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_viewings_date ON viewings(viewing_date)",
    "CREATE INDEX IF NOT EXISTS idx_fines_vehicle_id ON fines(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_fines_status ON fines(status)",
    "CREATE INDEX IF NOT EXISTS idx_receipts_vehicle_id ON receipts(vehicle_id)",
    "CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(receipt_date)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_staff_members_name ON staff_members(name COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_wage_payments_staff_id ON wage_payments(staff_id)",
    "CREATE INDEX IF NOT EXISTS idx_custom_tasks_status ON custom_tasks(status)",
]


def schema_table_names() -> list[str]:
    return list(TABLE_DEFINITIONS.keys())
