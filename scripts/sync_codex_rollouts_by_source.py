#!/usr/bin/env python3
"""Sync rollout files for sessions whose metadata identifies a source host."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def metadata(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.loads(handle.readline()).get("payload", {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--cwd-prefix", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    target_root = args.target_root.resolve()
    copied = []
    unchanged = []
    conflicts = []
    for source in sorted((source_root / "sessions").rglob("*.jsonl")):
        payload = metadata(source)
        if not str(payload.get("cwd", "")).lower().startswith(args.cwd_prefix.lower()):
            continue
        session_id = payload.get("session_id") or payload.get("id")
        if not session_id:
            continue
        target_matches = list((target_root / "sessions").rglob(f"*{session_id}.jsonl"))
        target = target_matches[0] if target_matches else target_root / "sessions" / source.relative_to(source_root / "sessions")
        if target.exists() and digest(source) == digest(target):
            unchanged.append(session_id)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append({"id": session_id, "source": str(source), "target": str(target)})

    report = {"copied": copied, "unchanged": unchanged, "conflicts": conflicts}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"copied": len(copied), "unchanged": len(unchanged), "conflicts": len(conflicts), "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
