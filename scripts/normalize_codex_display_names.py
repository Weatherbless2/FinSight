#!/usr/bin/env python3
"""Make Codex local list labels match the source-prefixed session index."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-root", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    root = args.codex_root.resolve()
    state_path = root / "state_5.sqlite"
    args.backup.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(state_path, timeout=30)
    source.execute("PRAGMA busy_timeout = 30000")
    destination = sqlite3.connect(args.backup)
    source.backup(destination)
    destination.close()

    labels = {
        item["id"]: item["thread_name"]
        for item in (
            json.loads(line)
            for line in (root / "session_index.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    source.execute("BEGIN IMMEDIATE")
    try:
        for session_id, label in labels.items():
            source.execute("UPDATE threads SET title = ?, name = ? WHERE id = ?", (label, label, session_id))
        source.commit()
    except Exception:
        source.rollback()
        raise
    finally:
        source.close()

    check = sqlite3.connect(state_path)
    rows = check.execute("SELECT id, title, name FROM threads WHERE id IN ({})".format(",".join("?" * len(labels))), tuple(labels)).fetchall()
    check.execute("PRAGMA quick_check")
    check.close()
    mismatches = [row[0] for row in rows if row[1] != labels[row[0]] or row[2] != labels[row[0]]]
    report = {
        "indexed_sessions": len(labels),
        "updated_rows": len(rows),
        "mismatches": mismatches,
        "backup": str(args.backup),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
