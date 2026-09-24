#!/usr/bin/env python3
"""One-time, non-destructive merge for separate Codex session stores.

This script deliberately handles only the portable historical session data:
session rollouts, attachments, and session_index.jsonl. It never copies
credentials or overwrites an existing file with different content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


CLIENT_PREFIX = "<客户端>"
WSL_PREFIX = "<wsl>"


@dataclass(frozen=True)
class Session:
    session_id: str
    source: str
    title: str
    updated_at: str
    rollout: Path | None

    @property
    def display_title(self) -> str:
        prefix = CLIENT_PREFIX if self.source == "client" else WSL_PREFIX
        return f"{prefix} {unprefixed_title(self.title)}"


def unprefixed_title(title: str) -> str:
    for known_prefix in (CLIENT_PREFIX, WSL_PREFIX):
        if title.startswith(known_prefix):
            return title[len(known_prefix) :].lstrip()
    return title


def source_from_title(title: str) -> str | None:
    if title.startswith(CLIENT_PREFIX):
        return "client"
    if title.startswith(WSL_PREFIX):
        return "wsl"
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_sessions(root: Path, source: str) -> tuple[dict[str, Session], list[str]]:
    index_path = root / "session_index.jsonl"
    sessions: dict[str, Session] = {}
    issues: list[str] = []

    for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            session_id = item["id"]
            title = item["thread_name"]
            updated_at = item["updated_at"]
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            issues.append(f"{source}: invalid index line {line_number}: {error}")
            continue
        if session_id in sessions:
            issues.append(f"{source}: duplicate index id {session_id}")
            continue
        matches = list((root / "sessions").rglob(f"*{session_id}.jsonl"))
        if len(matches) > 1:
            issues.append(f"{source}: multiple rollout files for {session_id}")
            rollout = None
        elif matches:
            rollout = matches[0]
        else:
            issues.append(f"{source}: index id has no rollout file: {session_id}")
            rollout = None
        sessions[session_id] = Session(session_id, source_from_title(title) or source, title, updated_at, rollout)
    return sessions, issues


def copy_tree(source_root: Path, target_root: Path, report: dict, apply: bool) -> None:
    if not source_root.exists():
        return
    for source_path in sorted(path for path in source_root.rglob("*") if path.is_file()):
        if source_path.name == "pasted-text-attachments.json":
            continue
        relative = source_path.relative_to(source_root)
        target_path = target_root / relative
        entry = {"source": str(source_path), "target": str(target_path)}
        if target_path.exists():
            if sha256(source_path) == sha256(target_path):
                report["unchanged_files"].append(entry)
                continue
            entry["reason"] = "same relative path has different content"
            report["conflicts"].append(entry)
            continue
        report["copied_files"].append(entry)
        if apply:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def attachment_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    marker = "/attachments/"
    if marker in normalized:
        return normalized.split(marker, 1)[1]
    return normalized.rsplit("/", 1)[-1]


def attachment_display_path(root: Path, relative: str) -> str:
    if root.as_posix().startswith("/mnt/c/"):
        windows_root = "C:\\Users\\weath\\.codex"
        return f"{windows_root}/attachments/{relative}"
    return f"{root.as_posix()}/attachments/{relative}"


def merge_attachment_manifests(source_root: Path, target_root: Path, report: dict, apply: bool) -> None:
    source_path = source_root / "attachments" / "pasted-text-attachments.json"
    target_path = target_root / "attachments" / "pasted-text-attachments.json"
    manifests = []
    for path in (target_path, source_path):
        if path.exists():
            manifests.append(json.loads(path.read_text(encoding="utf-8")))
    if not manifests:
        return

    paths: dict[str, str] = {}
    excerpts: dict[str, str] = {}
    pending: set[str] = set()
    for manifest in manifests:
        for value in manifest.get("attachmentPaths", []):
            relative = attachment_relative_path(value)
            paths.setdefault(relative, attachment_display_path(target_root, relative))
        for value in manifest.get("pendingRemovalPaths", []):
            pending.add(attachment_display_path(target_root, attachment_relative_path(value)))
        for value, excerpt in manifest.get("textExcerptsByPath", {}).items():
            relative = attachment_relative_path(value)
            if relative in excerpts and excerpts[relative] != excerpt:
                report["conflicts"].append({
                    "source": str(source_path),
                    "target": str(target_path),
                    "reason": f"different text excerpts for attachment {relative}",
                })
            excerpts.setdefault(relative, excerpt)
    merged = {
        "attachmentPaths": sorted(paths.values()),
        "pendingRemovalPaths": sorted(pending),
        "textExcerptsByPath": {
            attachment_display_path(target_root, relative): excerpt
            for relative, excerpt in sorted(excerpts.items())
        },
    }
    report["attachment_manifests"][str(target_path)] = {
        "attachment_count": len(merged["attachmentPaths"]),
        "excerpt_count": len(merged["textExcerptsByPath"]),
    }
    if not apply:
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_name(f".{target_path.name}.merge-tmp")
    temporary_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_path, target_path)


def write_index(root: Path, sessions: dict[str, Session], report: dict, apply: bool) -> None:
    entries = [
        {"id": session.session_id, "thread_name": session.display_title, "updated_at": session.updated_at}
        for session in sorted(sessions.values(), key=lambda session: (session.updated_at, session.session_id))
    ]
    content = "".join(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n" for entry in entries)
    index_path = root / "session_index.jsonl"
    report["indexes"][str(index_path)] = {"entries": len(entries), "sha256": hashlib.sha256(content.encode()).hexdigest()}
    if not apply:
        return
    temporary_path = index_path.with_name(f".{index_path.name}.merge-tmp")
    temporary_path.write_text(content, encoding="utf-8")
    os.replace(temporary_path, index_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-root", type=Path, required=True)
    parser.add_argument("--wsl-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="write copies and merged indexes")
    arguments = parser.parse_args()

    client_root = arguments.client_root.resolve()
    wsl_root = arguments.wsl_root.resolve()
    report = {
        "mode": "apply" if arguments.apply else "dry-run",
        "client_root": str(client_root),
        "wsl_root": str(wsl_root),
        "issues": [],
        "conflicts": [],
        "copied_files": [],
        "unchanged_files": [],
        "indexes": {},
        "attachment_manifests": {},
    }

    client_sessions, client_issues = load_sessions(client_root, "client")
    wsl_sessions, wsl_issues = load_sessions(wsl_root, "wsl")
    report["issues"].extend(client_issues + wsl_issues)
    overlap = sorted(set(client_sessions) & set(wsl_sessions))
    for session_id in overlap:
        client_session = client_sessions[session_id]
        wsl_session = wsl_sessions[session_id]
        same_title = unprefixed_title(client_session.title) == unprefixed_title(wsl_session.title)
        same_timestamp = client_session.updated_at == wsl_session.updated_at
        same_rollout = False
        if client_session.rollout and wsl_session.rollout:
            same_rollout = sha256(client_session.rollout) == sha256(wsl_session.rollout)
        elif client_session.rollout is None and wsl_session.rollout is None:
            same_rollout = True
        if not (same_title and same_timestamp and same_rollout):
            report["conflicts"].append({"session_id": session_id, "reason": "same id has different source records"})

    merged = {**client_sessions, **wsl_sessions}
    for session in merged.values():
        if session.rollout is None:
            continue
        source_root = client_root if session.rollout.is_relative_to(client_root) else wsl_root
        target_root = wsl_root if session.source == "client" else client_root
        if target_root == source_root:
            target_root = wsl_root if source_root == client_root else client_root
        relative = session.rollout.relative_to(source_root / "sessions")
        source_path = source_root / "sessions" / relative
        target_path = target_root / "sessions" / relative
        if target_path.exists():
            if sha256(source_path) == sha256(target_path):
                report["unchanged_files"].append({"source": str(source_path), "target": str(target_path)})
            else:
                report["conflicts"].append({"source": str(source_path), "target": str(target_path), "reason": "rollout path has different content"})
        else:
            report["copied_files"].append({"source": str(source_path), "target": str(target_path)})
            if arguments.apply:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)

    copy_tree(client_root / "attachments", wsl_root / "attachments", report, arguments.apply)
    copy_tree(wsl_root / "attachments", client_root / "attachments", report, arguments.apply)
    merge_attachment_manifests(client_root, wsl_root, report, arguments.apply)
    merge_attachment_manifests(wsl_root, client_root, report, arguments.apply)
    write_index(client_root, merged, report, arguments.apply)
    write_index(wsl_root, merged, report, arguments.apply)

    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "mode": report["mode"],
        "merged_session_count": len(merged),
        "copied_files": len(report["copied_files"]),
        "unchanged_files": len(report["unchanged_files"]),
        "issues": len(report["issues"]),
        "conflicts": len(report["conflicts"]),
        "report": str(arguments.report),
    }, ensure_ascii=False))
    return 1 if report["conflicts"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
