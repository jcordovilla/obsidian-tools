#!/usr/bin/env python3
"""Count the open tasks in every To-Do note under 1.PROYECTOS (read-only).

Until 15 October 2026 this script stamped task counts into each To-Do
note's frontmatter for a Bases dashboard (Tasks.base). Stored counts went
stale the moment a box was ticked, so the dashboard moved to a Dataview
table in "All To-Dos.md" that counts the checkboxes live, and the stamped
properties were removed. The script now only reads:

    python3 sync_todo_frontmatter.py           table of notes with open tasks
    python3 sync_todo_frontmatter.py --json    the same as JSON (work list for
                                               /jc:reconcile-todos)
    python3 sync_todo_frontmatter.py --all     include notes with nothing open

--strip removes the old stamped properties (project, tasks-open, tasks-done,
tasks-waiting, next-action, tasks-synced) from any note that still carries
them; add --dry-run to list them without writing.

Stdlib only; no venv needed.
"""

import argparse
import json
import re
import sys
from pathlib import Path

VAULT = Path.home() / "obsidian" / "JC"
SCAN_ROOT = VAULT / "1.PROYECTOS"
TODO_NAMES = {"01-To-Do.md", "To-Do.md"}
EXCLUDE_PARTS = {"Templates", "4.ARCHIVO", ".claude", ".obsidian"}

LEGACY_KEYS = {
    "project",
    "tasks-open",
    "tasks-done",
    "tasks-waiting",
    "next-action",
    "tasks-synced",
}

OPEN_RE = re.compile(r"^\s*- \[ \] ")
DONE_RE = re.compile(r"^\s*- \[[xX]\] ")
CODE_RE = re.compile(r"^((?:IA|OF|EOI|DI|WT|RL|SU|UR|HY|AI)\d+)\b")


def find_todo_files():
    for path in sorted(SCAN_ROOT.rglob("*.md")):
        if path.name not in TODO_NAMES:
            continue
        if EXCLUDE_PARTS & set(path.parts):
            continue
        yield path


def split_frontmatter(text):
    """Return (frontmatter_lines, body). frontmatter_lines is [] if absent."""
    if not text.startswith("---\n"):
        return [], text
    end = text.find("\n---", 4)
    if end == -1:
        return [], text
    fm = text[4:end].splitlines()
    body_start = end + len("\n---")
    if text[body_start : body_start + 1] == "\n":
        body_start += 1
    return fm, text[body_start:]


def count(body):
    open_count = done_count = 0
    for line in body.splitlines():
        if OPEN_RE.match(line):
            open_count += 1
        elif DONE_RE.match(line):
            done_count += 1
    return open_count, done_count


def strip_legacy(fm_lines):
    """Drop the legacy keys (and any indented continuation lines)."""
    kept = []
    skip_block = False
    for line in fm_lines:
        key_match = re.match(r"^([A-Za-z0-9_-]+):", line)
        if key_match:
            skip_block = key_match.group(1) in LEGACY_KEYS
        elif not line.startswith((" ", "\t")):
            skip_block = False
        if not skip_block:
            kept.append(line)
    return kept


def run_strip(dry_run):
    changed = scanned = 0
    for path in find_todo_files():
        scanned += 1
        text = path.read_text(encoding="utf-8")
        fm_lines, body = split_frontmatter(text)
        if not fm_lines:
            continue
        kept = strip_legacy(fm_lines)
        if kept == fm_lines:
            continue
        changed += 1
        new_text = ("---\n" + "\n".join(kept) + "\n---\n" if kept else "") + body
        print(f"{'DRY ' if dry_run else ''}strip: {path.relative_to(VAULT)}")
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
    print(f"Scanned {scanned} To-Do files, {'would strip' if dry_run else 'stripped'} {changed}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--strip", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.strip:
        run_strip(args.dry_run)
        return 0

    rows = []
    for path in find_todo_files():
        _, body = split_frontmatter(path.read_text(encoding="utf-8"))
        open_count, done_count = count(body)
        if open_count == 0 and not args.all:
            continue
        rel = str(path.relative_to(VAULT))
        code = CODE_RE.match(path.parent.name)
        rows.append({
            "project": path.parent.name,
            "code": code.group(1) if code else "",
            "path": rel,
            "open": open_count,
            "done": done_count,
            "offer": "03-Ofertas" in rel,
        })
    rows.sort(key=lambda r: -r["open"])

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for r in rows:
            print(f"{r['open']:4d}  {r['project']}")
        print(f"{sum(r['open'] for r in rows)} open tasks in {len(rows)} notes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
