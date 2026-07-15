#!/usr/bin/env python3
"""Stamp task-tracking properties into To-Do note frontmatter.

Obsidian Bases can only display file-level properties, not individual
checkboxes. This script counts the checkboxes in every To-Do note under
1.PROYECTOS and writes the results into each note's frontmatter so the
vault-root Tasks.base (embedded in "All To-Dos.md") can show a live
per-project tracking table.

Stamped properties (owned by this script, safe to re-run):
    project        parent folder name (display label for the base)
    tasks-open     count of "- [ ]" checkboxes
    tasks-done     count of "- [x]" checkboxes
    tasks-waiting  count of lines mentioning "waiting on"
    next-action    text of the first open checkbox, cleaned and truncated
    tasks-synced   date of the last sync run

Usage:
    python3 sync_todo_frontmatter.py [--dry-run] [--verbose]

Stdlib only; no venv needed.
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

VAULT = Path.home() / "obsidian" / "JC"
SCAN_ROOT = VAULT / "1.PROYECTOS"
TODO_NAMES = {"01-To-Do.md", "To-Do.md"}
EXCLUDE_PARTS = {"Templates", "4.ARCHIVO", ".claude", ".obsidian"}

OWNED_KEYS = [
    "project",
    "tasks-open",
    "tasks-done",
    "tasks-waiting",
    "next-action",
    "tasks-synced",
]

OPEN_RE = re.compile(r"^\s*- \[ \] (.*)$")
DONE_RE = re.compile(r"^\s*- \[[xX]\] ")
WAITING_RE = re.compile(r"waiting on", re.IGNORECASE)


def find_todo_files():
    for path in sorted(SCAN_ROOT.rglob("*.md")):
        if path.name not in TODO_NAMES:
            continue
        if EXCLUDE_PARTS & set(path.parts):
            continue
        yield path


def clean_task_text(text, limit=110):
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", text)  # wikilinks
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # md links
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


def analyse_body(body):
    open_count = done_count = waiting_count = 0
    next_action = ""
    for line in body.splitlines():
        m = OPEN_RE.match(line)
        if m:
            open_count += 1
            if not next_action:
                next_action = clean_task_text(m.group(1))
        elif DONE_RE.match(line):
            done_count += 1
        if line.lstrip().startswith(("-", "*", ">")) and WAITING_RE.search(line):
            waiting_count += 1
    return {
        "tasks-open": open_count,
        "tasks-done": done_count,
        "tasks-waiting": waiting_count,
        "next-action": next_action,
    }


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


def yaml_value(value):
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def rebuild(fm_lines, stamped):
    owned = set(OWNED_KEYS)
    kept = []
    skip_block = False
    for line in fm_lines:
        key_match = re.match(r"^([A-Za-z0-9_-]+):", line)
        if key_match:
            skip_block = key_match.group(1) in owned
        if key_match is None and not line.startswith((" ", "\t")):
            skip_block = False
        if not skip_block:
            kept.append(line)
    new_lines = kept + [f"{k}: {yaml_value(v)}" for k, v in stamped.items()]
    return "---\n" + "\n".join(new_lines) + "\n---\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    today = datetime.date.today().isoformat()
    changed = scanned = 0
    for path in find_todo_files():
        scanned += 1
        text = path.read_text(encoding="utf-8")
        fm_lines, body = split_frontmatter(text)
        stats = analyse_body(body)
        stamped = {"project": path.parent.name, **stats, "tasks-synced": today}
        new_text = rebuild(fm_lines, stamped) + body
        # Ignore tasks-synced-only differences so re-runs stay quiet.
        strip_sync = lambda s: re.sub(r"^tasks-synced: .*$", "", s, flags=re.M)
        if strip_sync(new_text) == strip_sync(text):
            continue
        changed += 1
        rel = path.relative_to(VAULT)
        if args.verbose or args.dry_run:
            print(f"{'DRY ' if args.dry_run else ''}update: {rel} "
                  f"(open={stats['tasks-open']}, done={stats['tasks-done']})")
        if not args.dry_run:
            path.write_text(new_text, encoding="utf-8")
    print(f"Scanned {scanned} To-Do files, {'would update' if args.dry_run else 'updated'} {changed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
