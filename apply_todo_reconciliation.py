#!/usr/bin/env python3
"""Apply the reconcile-todos workflow output to the vault's To-Do notes.

Reads the JSON report produced by the `reconcile-todos` workflow
(.claude/workflows/reconcile-todos.js) and ticks the checkboxes of tasks whose
completion survived adversarial verification.

Deliberately conservative:
  - Only acts on tasks with verdict "done" or "superseded". Anything the
    verifier refuted has already been rewritten to "still-open" upstream and is
    never touched here.
  - Matches the checkbox line verbatim. No fuzzy matching: if the text does not
    match exactly (or matches more than one line), the task is skipped and
    reported, never guessed at.
  - Only ever flips "- [ ]" to "- [x]" and appends an evidence clause. Never
    deletes or reorders a line.
  - Dry-run by default. Requires --apply to write.

Optional, off by default:
  --rewrite      also apply proposed re-wordings of still-open stale tasks
  --add-missing  append commitments found in logs/email that the list lacks

Usage:
    python3 apply_todo_reconciliation.py report.json [--apply] [--rewrite] [--add-missing]

Stdlib only; no venv needed.
"""

import argparse
import json
import re
import sys
from pathlib import Path

VAULT = Path.home() / "obsidian" / "JC"
OPEN_RE = re.compile(r"^(\s*)- \[ \] (.*?)\s*$")
MAX_EVIDENCE = 200


def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def shorten(s, limit=MAX_EVIDENCE):
    s = norm(s)
    s = re.sub(r"\s*—\s*", ", ", s)  # style invariant: no em-dashes
    s = re.sub(r"\s*–\s*", "-", s)  # nor en-dashes
    if len(s) > limit:
        s = s[: limit - 3].rstrip(" ,;.") + "..."
    return s


def find_line(lines, text):
    """Return the single index of the open checkbox matching text, or None."""
    target = norm(text)
    hits = [
        i for i, line in enumerate(lines)
        if (m := OPEN_RE.match(line)) and norm(m.group(2)) == target
    ]
    if len(hits) == 1:
        return hits[0]
    return None if not hits else "ambiguous"


def close_line(line, task):
    indent, text = OPEN_RE.match(line).groups()
    label = "Done" if task["verdict"] == "done" else "Superseded"
    date = task.get("date") or ""
    ev = shorten(task.get("evidence"))
    stamp = f"{label}{' ' + date if date and date != 'none' else ''}: {ev}" if ev else label
    return f"{indent}- [x] {text.rstrip('.')}. {stamp}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report", type=Path)
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--rewrite", action="store_true", help="also apply re-wordings of still-open tasks")
    ap.add_argument("--add-missing", action="store_true", help="append missing commitments")
    args = ap.parse_args()

    data = json.loads(args.report.read_text(encoding="utf-8"))
    projects = data.get("projects", data if isinstance(data, list) else [])

    closed = rewritten = added = skipped = 0
    for proj in projects:
        path = VAULT / proj["path"]
        if not path.exists():
            print(f"  !! missing file: {proj['path']}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        actions = []

        for task in proj.get("tasks", []):
            verdict = task.get("verdict")
            if verdict in ("done", "superseded"):
                idx = find_line(lines, task["text"])
                if idx is None or idx == "ambiguous":
                    skipped += 1
                    actions.append(("SKIP", f"no unique match: {shorten(task['text'], 70)}"))
                    continue
                lines[idx] = close_line(lines[idx], task)
                closed += 1
                actions.append(("CLOSE", shorten(task["text"], 70)))
            elif args.rewrite and norm(task.get("replacement")):
                idx = find_line(lines, task["text"])
                if idx is None or idx == "ambiguous":
                    skipped += 1
                    actions.append(("SKIP", f"no unique match: {shorten(task['text'], 70)}"))
                    continue
                indent = OPEN_RE.match(lines[idx]).group(1)
                lines[idx] = f"{indent}- [ ] {norm(task['replacement'])}"
                rewritten += 1
                actions.append(("REWRITE", shorten(task["replacement"], 70)))

        missing = proj.get("missing_tasks") or []
        if args.add_missing and missing:
            block = ["", "## Added by reconciliation (2026-07-14)", ""]
            for m in missing:
                block.append(f"- [ ] {norm(m['text'])} ({shorten(m['evidence'], 120)})")
                added += 1
                actions.append(("ADD", shorten(m["text"], 70)))
            lines.extend(block)

        if actions:
            print(f"\n{proj['project']}")
            for kind, detail in actions:
                print(f"  {kind:8} {detail}")
            if args.apply:
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verb = "Applied" if args.apply else "Would apply"
    print(
        f"\n{verb}: {closed} closed, {rewritten} reworded, {added} added, {skipped} skipped (no unique match)."
    )
    if not args.apply:
        print("Dry run. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
