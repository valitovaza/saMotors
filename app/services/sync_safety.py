from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import shutil

from app.config.workbook_schema import BACKUP_ROOT, LOCAL_DB


@dataclass(frozen=True)
class DatabaseBackupSummary:
    backup_path: str
    filename: str


def create_database_backup(db_path: Path = LOCAL_DB) -> DatabaseBackupSummary | None:
    if not db_path.exists():
        return None

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_filename = f"{db_path.stem}_pre_import_{timestamp}{db_path.suffix}"
    backup_path = BACKUP_ROOT / backup_filename
    shutil.copy2(db_path, backup_path)
    return DatabaseBackupSummary(backup_path=str(backup_path), filename=backup_filename)
