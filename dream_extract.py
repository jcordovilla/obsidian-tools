#!/usr/bin/env python3
"""Corpus builder for /jc:dream (memory review from session transcripts).

Reads every Claude Code project under ~/.claude/projects/, keeps the user's
own typed turns since the last run (marker file), drops noise via
extract_session_prompts.py, and writes one plain-text corpus the /jc:dream
command reads. Sessions in excluded projects are skipped entirely.

Usage:
    python3 dream_extract.py                  # since last run (default 7 days on first run)
    python3 dream_extract.py --days 14        # override the window
    python3 dream_extract.py --out PATH       # corpus path (default: scratch in ~/.claude/dream/)
    python3 dream_extract.py --mark           # write the marker (call after the review ran)

No transcript content is written anywhere but the corpus file, which lives
outside every git repo.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_session_prompts import PROJECTS_ROOT, extract  # noqa: E402

DREAM_DIR = Path.home() / ".claude" / "dream"
MARKER = DREAM_DIR / "last-run"
DEFAULT_OUT = DREAM_DIR / "corpus.txt"
EXCLUDE = {"-Users-jose-mylab-ai-job-search"}
MIN_CHARS = 25  # "ok", "yes", "go" carry no memory signal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--mark", action="store_true")
    a = ap.parse_args()
    DREAM_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    if a.mark:
        MARKER.write_text(now.isoformat())
        print(f"marker set: {now.isoformat()}")
        return 0

    if a.days is not None:
        since = now - timedelta(days=a.days)
    elif MARKER.exists():
        since = datetime.fromisoformat(MARKER.read_text().strip())
    else:
        since = now - timedelta(days=7)

    rows = []
    for p in sorted(PROJECTS_ROOT.iterdir()):
        if not p.is_dir() or p.name in EXCLUDE:
            continue
        prompts, _ = extract(p, since=since)
        for pr in prompts:
            if pr["len"] >= MIN_CHARS:
                pr["project"] = p.name
                rows.append(pr)
    rows.sort(key=lambda r: r["ts"])

    with a.out.open("w") as f:
        f.write(f"# dream corpus, user turns since {since.isoformat()} ({len(rows)} turns)\n\n")
        for r in rows:
            f.write(f"=== {r['ts'][:16]} | {r['project']} | {r['sid'][:8]} ===\n")
            f.write(r["text"].strip()[:3000] + "\n\n")
    print(f"since: {since.isoformat()}")
    print(f"turns: {len(rows)}  chars: {sum(r['len'] for r in rows):,}")
    print(f"corpus: {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
