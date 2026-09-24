#!/usr/bin/env python3
"""Restore immutable client/WSL title labels from pre-merge indexes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


CLIENT_PREFIX = "<客户端>"
WSL_PREFIX = "<wsl>"


def index_ids(path: Path) -> set[str]:
    return {json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def bare_title(title: str) -> str:
    for prefix in (CLIENT_PREFIX, WSL_PREFIX):
        if title.startswith(prefix):
            return title[len(prefix) :].lstrip()
    return title


def session_cwd(roots: list[Path], session_id: str) -> str | None:
    for root in roots:
        matches = list((root / "sessions").rglob(f"*{session_id}.jsonl"))
        for rollout in matches:
            with rollout.open(encoding="utf-8") as handle:
                first_line = handle.readline()
            try:
                return json.loads(first_line)["payload"].get("cwd")
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", type=Path, required=True)
    parser.add_argument("--wsl-root", type=Path, required=True)
    parser.add_argument("--original-client-index", type=Path, required=True)
    parser.add_argument("--original-wsl-index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()

    client_ids = index_ids(arguments.original_client_index)
    wsl_ids = index_ids(arguments.original_wsl_index)
    if client_ids & wsl_ids:
        raise SystemExit("original indexes contain overlapping IDs")

    roots = [arguments.client_root, arguments.wsl_root]
    current = {}
    for root in roots:
        for line in (root / "session_index.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                current.setdefault(item["id"], item)

    inferred = []
    unresolved = []
    entries = []
    for session_id, item in current.items():
        if session_id in client_ids:
            source = "client"
        elif session_id in wsl_ids:
            source = "wsl"
        else:
            cwd = session_cwd(roots, session_id)
            if cwd is None:
                unresolved.append(session_id)
                continue
            source = "client" if cwd.lower().startswith("c:\\") else "wsl"
            inferred.append({"id": session_id, "source": source, "cwd": cwd})
        prefix = CLIENT_PREFIX if source == "client" else WSL_PREFIX
        entries.append({
            "id": session_id,
            "thread_name": f"{prefix} {bare_title(item['thread_name'])}",
            "updated_at": item["updated_at"],
        })
    entries.sort(key=lambda item: (item["updated_at"], item["id"]))
    content = "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in entries)
    for root in roots:
        target = root / "session_index.jsonl"
        temporary = target.with_name(f".{target.name}.labels-tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, target)
    report = {
        "sessions": len(entries),
        "client_sessions": sum(item["thread_name"].startswith(CLIENT_PREFIX) for item in entries),
        "wsl_sessions": sum(item["thread_name"].startswith(WSL_PREFIX) for item in entries),
        "inferred_after_backup": inferred,
        "unresolved": unresolved,
    }
    arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
