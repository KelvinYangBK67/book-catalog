from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import database_path
from app.tag_taxonomy import apply_main_tag_taxonomy


def backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="備份資料庫後，安裝可重複執行的藏書標籤主樹。"
    )
    parser.add_argument("--database", type=Path, default=database_path())
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    source = args.database.resolve()
    backup = args.backup or source.parent / "backups" / (
        f"{source.stem}-before-tag-tree-{datetime.now():%Y%m%d-%H%M%S}{source.suffix}"
    )
    backup = backup.resolve()
    backup_database(source, backup)
    report = apply_main_tag_taxonomy(source)
    print(json.dumps({
        "database": str(source),
        "backup": str(backup),
        "created_count": len(report["created"]),
        "moved_count": len(report["moved"]),
        "reused_count": len(report["reused"]),
        "node_ids": report["node_ids"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
