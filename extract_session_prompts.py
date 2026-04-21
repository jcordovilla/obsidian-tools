#!/usr/bin/env python3
"""Extract user-typed prompts from Claude Code session JSONL logs.

Reads .jsonl files under ~/.claude/projects/<project>/ and emits a
filtered, chronologically sorted corpus of the user's actual prompts —
stripping tool results, system reminders, slash-command echoes, bash
input/output blocks, and other noise.

Useful for self-reflection exercises (extracting a corpus to summarise
what you've been asking Claude to do over a period).

Outputs (in the chosen output directory):
- all_prompts.jsonl        : every user message that survived the filter
- substantive_prompts.jsonl: filtered to those above --threshold characters
- substantive_prompts.txt  : human-readable plain-text version of the above

Default project: the JC vault (`-Users-jose-obsidian-JC`).
Default output: /tmp/jc_prompts/

Usage:
    python extract_session_prompts.py
    python extract_session_prompts.py --project -Users-jose-mylab-paco
    python extract_session_prompts.py --output ~/Desktop/prompts --threshold 200
    python extract_session_prompts.py --since 2026-04-01 --until 2026-04-19
    python extract_session_prompts.py --list   # list available projects
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECTS_ROOT = Path.home() / ".claude" / "projects"
DEFAULT_PROJECT = "-Users-jose-obsidian-JC"
DEFAULT_OUTPUT = Path("/tmp/jc_prompts")
DEFAULT_THRESHOLD = 80

NOISE_PATTERNS = [
    re.compile(r"^<command-name>", re.S),
    re.compile(r"^<local-command-", re.S),
    re.compile(r"^<bash-input>", re.S),
    re.compile(r"^<bash-stdout>", re.S),
    re.compile(r"^<bash-stderr>", re.S),
    re.compile(r"^\[Request interrupted", re.S),
    re.compile(r"^<system-reminder>", re.S),
    re.compile(r"^Caveat:", re.S),
    re.compile(r"^This session is being continued", re.S),
    re.compile(r"^Tool loaded\.", re.S),
]


def is_noise(text: str) -> bool:
    if not text or len(text.strip()) < 3:
        return True
    return any(p.match(text.lstrip()) for p in NOISE_PATTERNS)


def extract_text(content) -> list[str]:
    out = []
    if isinstance(content, str):
        if not is_noise(content):
            out.append(content)
    elif isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                t = item.get("text", "")
                if not is_noise(t):
                    out.append(t)
    return out


def parse_iso(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def list_projects() -> int:
    if not PROJECTS_ROOT.is_dir():
        print(f"No projects directory at {PROJECTS_ROOT}", file=sys.stderr)
        return 1
    rows = []
    for p in sorted(PROJECTS_ROOT.iterdir()):
        if not p.is_dir():
            continue
        files = list(p.glob("*.jsonl"))
        n = len(files)
        size = sum(f.stat().st_size for f in files)
        rows.append((p.name, n, size))
    if not rows:
        print("No projects found", file=sys.stderr)
        return 1
    print(f"{'PROJECT':<48} {'SESSIONS':>10} {'SIZE':>12}")
    for name, n, size in rows:
        mb = size / (1024 * 1024)
        print(f"{name:<48} {n:>10} {mb:>10.1f} MB")
    return 0


def extract(project_dir: Path, since=None, until=None):
    prompts = []
    bad = 0
    for jf in sorted(project_dir.glob("*.jsonl")):
        sid = jf.stem
        try:
            with jf.open() as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except Exception:
                        bad += 1
                        continue
                    if obj.get("type") != "user":
                        continue
                    msg = obj.get("message") or {}
                    if msg.get("role") != "user":
                        continue
                    ts = obj.get("timestamp", "")
                    if since or until:
                        dt = parse_iso(ts)
                        if dt is None:
                            continue
                        if since and dt < since:
                            continue
                        if until and dt > until:
                            continue
                    for t in extract_text(msg.get("content")):
                        prompts.append({"ts": ts, "sid": sid, "len": len(t), "text": t})
        except Exception as e:
            print(f"err reading {jf.name}: {e}", file=sys.stderr)
    prompts.sort(key=lambda p: p["ts"])
    return prompts, bad


def write_outputs(prompts, output_dir: Path, threshold: int):
    output_dir.mkdir(parents=True, exist_ok=True)
    all_path = output_dir / "all_prompts.jsonl"
    sub_jsonl = output_dir / "substantive_prompts.jsonl"
    sub_txt = output_dir / "substantive_prompts.txt"

    with all_path.open("w") as f:
        for p in prompts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    substantive = [p for p in prompts if p["len"] >= threshold]
    with sub_jsonl.open("w") as f:
        for p in substantive:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with sub_txt.open("w") as f:
        for p in substantive:
            f.write(f"=== {p['ts']} ({p['len']} chars) ===\n")
            f.write(p["text"].strip() + "\n\n")

    return all_path, sub_jsonl, sub_txt, substantive


def print_stats(prompts, substantive, threshold: int) -> None:
    total = len(prompts)
    total_chars = sum(p["len"] for p in prompts)
    print(f"Total prompts: {total}")
    print(f"Total chars:   {total_chars:,}")
    print(f"Avg length:    {total_chars/max(total,1):.0f} chars")

    buckets = {"≤50": 0, "51-200": 0, "201-1000": 0, "1001-5000": 0, ">5000": 0}
    for p in prompts:
        n = p["len"]
        if n <= 50:
            buckets["≤50"] += 1
        elif n <= 200:
            buckets["51-200"] += 1
        elif n <= 1000:
            buckets["201-1000"] += 1
        elif n <= 5000:
            buckets["1001-5000"] += 1
        else:
            buckets[">5000"] += 1
    print("Length distribution:")
    for k, v in buckets.items():
        print(f"  {k:>10}: {v}")

    by_week = defaultdict(int)
    for p in prompts:
        dt = parse_iso(p["ts"])
        if not dt:
            continue
        iy, iw, _ = dt.isocalendar()
        by_week[f"{iy}-W{iw:02d}"] += 1
    if by_week:
        print("\nPrompts by ISO week:")
        for wk in sorted(by_week.keys()):
            print(f"  {wk}: {by_week[wk]}")

    print(f"\nSubstantive (≥{threshold} chars): {len(substantive)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--project",
        default=DEFAULT_PROJECT,
        help=f"Claude Code project directory under {PROJECTS_ROOT} (default: {DEFAULT_PROJECT})",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    ap.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Substantive-prompt char threshold (default: {DEFAULT_THRESHOLD})",
    )
    ap.add_argument(
        "--since",
        type=str,
        help="ISO date or datetime; only include prompts on/after this (UTC)",
    )
    ap.add_argument(
        "--until",
        type=str,
        help="ISO date or datetime; only include prompts on/before this (UTC)",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="List available projects under ~/.claude/projects/ and exit",
    )
    args = ap.parse_args()

    if args.list:
        return list_projects()

    project_dir = PROJECTS_ROOT / args.project
    if not project_dir.is_dir():
        print(f"Project directory not found: {project_dir}", file=sys.stderr)
        return 2

    since = parse_iso(args.since) if args.since else None
    until = parse_iso(args.until) if args.until else None
    if args.since and since is None:
        print(f"Could not parse --since: {args.since}", file=sys.stderr)
        return 2
    if args.until and until is None:
        print(f"Could not parse --until: {args.until}", file=sys.stderr)
        return 2
    if since and since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    if until and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)

    print(f"Reading from: {project_dir}")
    prompts, bad = extract(project_dir, since=since, until=until)
    if bad:
        print(f"({bad} JSONL lines failed to parse)", file=sys.stderr)

    all_path, sub_jsonl, sub_txt, substantive = write_outputs(
        prompts, args.output, args.threshold
    )
    print_stats(prompts, substantive, args.threshold)
    print("\nFiles written:")
    for f in (all_path, sub_jsonl, sub_txt):
        print(f"  {f}  {f.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
