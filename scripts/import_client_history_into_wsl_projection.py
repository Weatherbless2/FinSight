#!/usr/bin/env python3
"""Import a trusted client Codex history snapshot into WSL's live SQLite projection.

The script uses SQLite transactions and a pre-write database backup. It imports
only IDs present in WSL's merged session index, preserves WSL-native records,
and rewrites copied rollout paths to the WSL session store.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path


def rows_from_index(path: Path) -> dict[str, dict]:
    return {item["id"]: item for item in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())}


def rollout_paths(root: Path, ids: set[str]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for path in (root / "sessions").rglob("*.jsonl"):
        for session_id in ids:
            if path.name.endswith(f"{session_id}.jsonl"):
                paths[session_id] = path
                break
    return paths


def insert_rows(target: sqlite3.Connection, source: sqlite3.Connection, table: str, where: str = "", values: tuple = ()) -> int:
    columns = [row[1] for row in target.execute(f"PRAGMA table_info({table})")]
    if not columns:
        return 0
    source_columns = {row[1] for row in source.execute(f"PRAGMA table_info({table})")}
    available_columns = [column for column in columns if column in source_columns]
    column_sql = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    query = f"SELECT {', '.join(available_columns)} FROM {table}" + (f" WHERE {where}" if where else "")
    raw_rows = source.execute(query, values).fetchall()
    rows = [
        tuple(row[available_columns.index(column)] if column in source_columns else None for column in columns)
        for row in raw_rows
    ]
    target.executemany(f"INSERT OR IGNORE INTO {table} ({column_sql}) VALUES ({placeholders})", rows)
    return len(rows)


def session_meta(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.loads(handle.readline())["payload"]


def epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def add_missing_thread(target: sqlite3.Connection, item: dict, path: Path) -> None:
    meta = session_meta(path)
    created_at = epoch_seconds(meta["timestamp"])
    title = item["thread_name"]
    target.execute(
        """
        INSERT INTO threads (
          id, rollout_path, created_at, updated_at, source, model_provider, cwd,
          title, sandbox_policy, approval_mode, cli_version, first_user_message,
          memory_mode, model, reasoning_effort, created_at_ms, updated_at_ms,
          thread_source, preview, recency_at, recency_at_ms, history_mode,
          is_pinned, originator
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'enabled', ?, ?, ?, ?, ?, '', ?, ?, 'legacy', 0, ?)
        """,
        (
            item["id"], str(path), created_at, epoch_seconds(item["updated_at"]),
            meta.get("source", "vscode"), meta.get("model_provider", "cherry"), meta.get("cwd", ""),
            title, '{"type":"disabled"}', "never", meta.get("cli_version", ""),
            meta.get("model"), meta.get("reasoning_effort"),
            created_at * 1000, epoch_seconds(item["updated_at"]) * 1000,
            meta.get("thread_source"), epoch_seconds(item["updated_at"]),
            epoch_seconds(item["updated_at"]) * 1000, meta.get("originator"),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl-root", type=Path, required=True)
    parser.add_argument("--client-state", type=Path, required=True)
    parser.add_argument("--client-history", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()

    wsl_root = arguments.wsl_root.resolve()
    state_path = wsl_root / "state_5.sqlite"
    history_path = wsl_root / "thread_history_1.sqlite"
    index = rows_from_index(wsl_root / "session_index.jsonl")
    index_ids = set(index)
    paths = rollout_paths(wsl_root, index_ids)
    missing_rollouts = sorted(index_ids - set(paths))
    arguments.backup_dir.mkdir(parents=True, exist_ok=True)

    state = sqlite3.connect(state_path, timeout=30)
    history = sqlite3.connect(history_path, timeout=30)
    client_state = sqlite3.connect(arguments.client_state)
    client_history = sqlite3.connect(arguments.client_history)
    for connection in (state, history):
        connection.execute("PRAGMA busy_timeout = 30000")
    state.backup(sqlite3.connect(arguments.backup_dir / "wsl-state-before-projection-import.sqlite"))
    history.backup(sqlite3.connect(arguments.backup_dir / "wsl-history-before-projection-import.sqlite"))

    source_ids = {row[0] for row in client_state.execute("SELECT id FROM threads")}
    import_ids = sorted(index_ids & source_ids)
    placeholders = ",".join("?" for _ in import_ids)
    state.execute("BEGIN IMMEDIATE")
    history.execute("BEGIN IMMEDIATE")
    try:
        for table in ("projects", "project_roots", "project_idempotency_keys"):
            insert_rows(state, client_state, table)
        imported_threads = insert_rows(state, client_state, "threads", f"id IN ({placeholders})", tuple(import_ids))
        for table in ("thread_artifacts", "thread_dynamic_tools"):
            insert_rows(state, client_state, table, f"thread_id IN ({placeholders})", tuple(import_ids))
        insert_rows(state, client_state, "thread_spawn_edges", f"parent_thread_id IN ({placeholders}) AND child_thread_id IN ({placeholders})", tuple(import_ids + import_ids))

        existing_ids = {row[0] for row in state.execute("SELECT id FROM threads")}
        synthesized = []
        for session_id in sorted(index_ids - existing_ids):
            if session_id not in paths:
                continue
            add_missing_thread(state, index[session_id], paths[session_id])
            synthesized.append(session_id)
        for session_id, item in index.items():
            state.execute("UPDATE threads SET title = ?, name = COALESCE(name, ?) WHERE id = ?", (item["thread_name"], item["thread_name"], session_id))
            if session_id in paths:
                state.execute("UPDATE threads SET rollout_path = ? WHERE id = ?", (str(paths[session_id]), session_id))

        for table in ("thread_history_projection_state", "thread_items", "thread_realtime_items", "thread_turns"):
            insert_rows(history, client_history, table, f"thread_id IN ({placeholders})", tuple(import_ids))
        state.commit()
        history.commit()
    except Exception:
        state.rollback()
        history.rollback()
        raise
    finally:
        state.close()
        history.close()
        client_state.close()
        client_history.close()

    state_check = sqlite3.connect(state_path)
    history_check = sqlite3.connect(history_path)
    projected_ids = {row[0] for row in state_check.execute("SELECT id FROM threads")}
    report = {
        "index_ids": len(index_ids),
        "imported_client_threads": imported_threads,
        "synthesized_threads": synthesized,
        "wsl_threads_after": len(projected_ids),
        "index_ids_missing_from_wsl_threads": sorted(index_ids - projected_ids),
        "index_ids_without_rollouts": missing_rollouts,
        "wsl_history_items_after": history_check.execute("SELECT count(*) FROM thread_items").fetchone()[0],
        "completed_at": int(time.time()),
    }
    state_check.close()
    history_check.close()
    arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["index_ids_missing_from_wsl_threads"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
