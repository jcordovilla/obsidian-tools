#!/usr/bin/env python3
"""LinkedIn posts register: JSON canon + curated vault selection.

The canonical store is a JSON file outside the vault holding the full post
history from the LinkedIn data export. The vault note carries only the curated
selection (authored posts) for voice analysis, reuse, and engagement ranking.

The export does not carry the manual `theme:`, `engagement:`, language, or
selection fields, so those live in the JSON and are preserved across syncs,
keyed by post URL.

Subcommands (all mutating ones dry-run by default, like the other obsidian-tools):

    sync   --shares Shares.csv   Update the JSON canon from a data export.
    render                       Write the authored selection into the vault note.
    pull                         Read manual theme/engagement from the vault note back into the JSON.
    rank   [N]                   List selected posts by engagement, highest first.

Typical quarterly flow:
    linkedin_register.py sync --shares ~/Downloads/Shares.csv --no-dry-run
    linkedin_register.py render --no-dry-run
    # ... review the note in Obsidian, fill theme/engagement ...
    linkedin_register.py pull --no-dry-run
"""

import argparse
import csv
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

VAULT = Path.home() / "obsidian" / "JC"
REGISTER = VAULT / "1.PROYECTOS" / "Professional" / "Professional Profile" / "Linkedin Posts.md"
JSON_CANON = Path.home() / "mylab" / "paco" / "data" / "linkedin" / "posts.json"
MARKER = "<!-- linkedin_register.py renders the authored selection below. Canon: posts.json. -->"
LEGACY_HEADING = "## Legacy archive (pre-2026, unstructured)"

# Spanish-language signals for the EN/ES guess. Strong: Spanish-only characters.
# Weak: common words (some overlap English, so weighted lower).
ES_STRONG = re.compile(r"[¿¡áéíóúñü]")
ES_WEAK = re.compile(r"\b(que|los|las|para|con|una|del|por|como|este|son|también|más)\b", re.IGNORECASE)


def guess_lang(text: str) -> str:
    strong = len(ES_STRONG.findall(text))
    weak = len(ES_WEAK.findall(text))
    if strong >= 2 or (strong >= 1 and weak >= 1) or weak >= 3:
        return "ES"
    return "EN"


def norm_date(raw: str) -> str:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw or "undated"


def pick(row: dict, *names: str) -> str:
    for n in names:
        for key in row:
            if key and key.strip().lower() == n.lower() and (row[key] or "").strip():
                return row[key].strip()
    return ""


def clean_text(text: str) -> str:
    """Strip the CSV title/body quote-mash from old shares and normalise unicode."""
    t = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [ln.strip() for ln in t.split("\n")]
    lines = [ln for ln in lines if ln.strip('"').strip()]          # drop quote-only lines
    lines = [re.sub(r'"+$', "", re.sub(r'^"+', "", ln)).strip() for ln in lines]
    return "\n".join(l for l in lines if l).strip()


def urn_type(url: str) -> str:
    m = re.search(r"urn%3Ali%3A(\w+)%3A|urn:li:(\w+):", url or "")
    return (m.group(1) or m.group(2)) if m else "none"


def classify(url: str, shared_url: str, cleaned: str) -> str:
    """authored | group_post | link_share. Authored is the vault selection."""
    if urn_type(url) == "groupPost":
        return "group_post"
    if shared_url.strip() and len(cleaned) < 80:
        return "link_share"
    return "authored"


# ---- JSON canon -----------------------------------------------------------

def load_canon(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {e["url"]: e for e in data if e.get("url")}


def save_canon(path: Path, by_url: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(by_url.values(), key=lambda e: (e.get("date", ""), e.get("url", "")))
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---- vault note parsing ---------------------------------------------------

ENTRY_RE = re.compile(
    r"^### (?P<date>\S+) · (?P<lang>\w+) · \[post\]\((?P<url>[^)]*)\)[^\n]*$"
    r"(?:\ntheme: ?(?P<theme>[^\n]*))?"
    r"(?:\nengagement: ?(?P<eng>[^\n]*))?"
    r"\n+(?P<text>[\s\S]+?)(?=\n### |\n## |\Z)",
    re.MULTILINE,
)


def structured_section(content: str) -> str:
    return content.split("## Structured entries", 1)[-1].split(LEGACY_HEADING, 1)[0]


def render_entry(e: dict) -> str:
    lang = e.get("lang") or guess_lang(e["text"])
    link = f"[post]({e['url']})" if e.get("url") else "[post](unknown-url)"
    return (f"### {e['date']} · {lang} · {link}\n"
            f"theme: {e.get('theme', '')}\nengagement: {e.get('engagement', '')}\n\n{e['text']}\n")


# ---- commands -------------------------------------------------------------

def cmd_sync(args) -> None:
    if not args.shares.exists():
        raise SystemExit(f"Shares file not found: {args.shares}")
    canon = load_canon(args.json)
    rows = list(csv.DictReader(args.shares.open(encoding="utf-8-sig", newline="")))
    seen, new, updated = set(), 0, 0
    for row in rows:
        raw = pick(row, "ShareCommentary", "Commentary", "Text")
        url = pick(row, "ShareLink", "Share Link", "Url", "URL")
        if not raw or not url:
            continue
        seen.add(url)
        cleaned = clean_text(raw)
        kind = classify(url, pick(row, "SharedUrl", "Shared Url"), cleaned)
        date = norm_date(pick(row, "Date", "Created Date"))
        if url in canon:
            e = canon[url]
            e.update(date=date, text=cleaned, kind=kind)  # manual fields untouched
            updated += 1
        else:
            canon[url] = {
                "url": url, "date": date, "kind": kind, "lang": guess_lang(cleaned),
                "text": cleaned, "theme": "", "engagement": "", "selected": kind == "authored",
            }
            new += 1
    orphans = [u for u in canon if u not in seen]

    from collections import Counter
    kinds = Counter(e["kind"] for e in canon.values())
    selected = sum(1 for e in canon.values() if e.get("selected"))
    print(f"Export rows with commentary+URL: {len(seen)}")
    print(f"Canon: {len(canon)} posts ({new} new, {updated} updated, {len(orphans)} not in this export)")
    print(f"By kind: {dict(kinds)} | selected for vault: {selected}")
    if orphans:
        print(f"  ({len(orphans)} posts kept from prior syncs but absent here, e.g. deleted on LinkedIn)")
    if not args.no_dry_run:
        print("\nDry run. Re-run with --no-dry-run to write the JSON canon.")
        return
    save_canon(args.json, canon)
    print(f"\nWrote {args.json}")


def cmd_render(args) -> None:
    canon = load_canon(args.json)
    if not canon:
        raise SystemExit(f"Canon is empty or missing: {args.json}. Run `sync` first.")
    content = args.register.read_text(encoding="utf-8")
    if MARKER not in content or LEGACY_HEADING not in content:
        raise SystemExit("Register is missing the render marker or the Legacy archive heading.")
    selected = sorted((e for e in canon.values() if e.get("selected")), key=lambda e: e["date"])

    before, _, tail = content.partition(LEGACY_HEADING)
    header, _, _old = before.partition(MARKER)
    block = "\n\n" + "\n".join(render_entry(e) for e in selected) + "\n\n"
    updated = header + MARKER + block + LEGACY_HEADING + tail

    scored = sum(1 for e in selected if re.search(r"\d", e.get("engagement", "")))
    print(f"Selected (authored) posts to render: {len(selected)} | already engagement-scored: {scored}")
    if not args.no_dry_run:
        print("\nDry run. Re-run with --no-dry-run to rewrite the vault note's Structured entries.")
        return
    args.register.write_text(updated, encoding="utf-8")
    print(f"\nRendered {len(selected)} entries into {args.register}")


def cmd_pull(args) -> None:
    canon = load_canon(args.json)
    if not canon:
        raise SystemExit(f"Canon is empty or missing: {args.json}.")
    section = structured_section(args.register.read_text(encoding="utf-8"))
    changed = []
    for m in ENTRY_RE.finditer(section):
        url = (m.group("url") or "").strip()
        if url not in canon:
            continue
        theme, eng = (m.group("theme") or "").strip(), (m.group("eng") or "").strip()
        e = canon[url]
        if theme != e.get("theme", "") or eng != e.get("engagement", ""):
            changed.append((url, e.get("theme", ""), theme, e.get("engagement", ""), eng))
            e["theme"], e["engagement"] = theme, eng
    print(f"Manual fields changed in the note since last pull: {len(changed)}")
    for url, ot, nt, oe, ne in changed[:30]:
        print(f"  {url.split(':')[-1][:18]:18}  theme '{ot}'->'{nt}'  eng '{oe}'->'{ne}'")
    if len(changed) > 30:
        print(f"  ... and {len(changed) - 30} more")
    if not changed:
        print("Nothing to pull.")
        return
    if not args.no_dry_run:
        print("\nDry run. Re-run with --no-dry-run to write the JSON canon.")
        return
    save_canon(args.json, canon)
    print(f"\nUpdated {args.json}")


def cmd_rank(args) -> None:
    canon = load_canon(args.json)
    ranked, unscored = [], 0
    for e in canon.values():
        if not e.get("selected"):
            continue
        num = re.search(r"\d[\d,]*", e.get("engagement", ""))
        if num:
            snippet = " ".join(e["text"].split())[:70]
            ranked.append((int(num.group().replace(",", "")), e["date"], e.get("theme", ""), snippet))
        else:
            unscored += 1
    ranked.sort(key=lambda r: r[0], reverse=True)
    if not ranked:
        print("No selected entries carry an engagement number yet. Fill them in the note, then `pull`.")
        return
    print(f"Top {min(args.n, len(ranked))} selected posts by engagement ({unscored} unscored):\n")
    for eng, date, theme, snippet in ranked[:args.n]:
        tag = f" [{theme}]" if theme else ""
        print(f"  {eng:>6}  {date}{tag}  {snippet}...")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", type=Path, default=JSON_CANON, help="JSON canon path")
    ap.add_argument("--register", type=Path, default=REGISTER, help="Vault register note")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sync", help="Update JSON canon from a LinkedIn data export")
    sp.add_argument("--shares", required=True, type=Path, help="Path to Shares.csv")
    sp.add_argument("--no-dry-run", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("render", help="Render authored selection into the vault note")
    sp.add_argument("--no-dry-run", action="store_true")
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("pull", help="Read manual theme/engagement from the note into the canon")
    sp.add_argument("--no-dry-run", action="store_true")
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("rank", help="List selected posts by engagement")
    sp.add_argument("n", nargs="?", type=int, default=20)
    sp.set_defaults(func=cmd_rank)

    args = ap.parse_args()
    if not args.register.exists() and args.cmd in ("render", "pull"):
        raise SystemExit(f"Register note not found: {args.register}")
    args.func(args)


if __name__ == "__main__":
    main()
