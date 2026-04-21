"""Generic note triage app for an Obsidian vault.

Review notes one at a time with keyboard-driven actions. Configurable source
folders, target folders, and filter criteria via CLI args. Preserves the
distilled-artefact lineage (type inferred from parent folder) while also
working for plain notes (INBOX triage, etc.).

Usage:
    # Default: triage distilled artefacts in _Uncategorized
    cd ~/mylab/obsidian-tools && ./venv/bin/python -m triage_app

    # Custom source folder (e.g. INBOX)
    ./venv/bin/python -m triage_app --source "0.INBOX"

    # Multiple sources
    ./venv/bin/python -m triage_app --source "0.INBOX" --source "Ideas"

    # Only notes tagged status/review (default)
    # --filter-tag status/review

    # No tag filter: show every note in the source folder(s)
    ./venv/bin/python -m triage_app --no-filter

    # Different port
    ./venv/bin/python -m triage_app --port 8095

State:
    triage_app/state.json — undo stack + per-source session skips.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
import uvicorn


# --- Defaults -------------------------------------------------------------

DEFAULT_VAULT = Path("/Users/jose/obsidian/JC")
DEFAULT_SOURCE = "3.RECURSOS/Domain Knowledge/_Uncategorized"
DEFAULT_ARCHIVE = "4.ARCHIVO/ChatGPT Distilled - Archived"
DEFAULT_FILTER_TAG = "status/review"

STATE_FILE = Path(__file__).parent / "state.json"
STATIC_DIR = Path(__file__).parent / "static"

# Target folders: vault-relative path under 3.RECURSOS/, with a 1-8 shortcut.
# Each triage session can override via --target "Label|path|key" repeated.
DEFAULT_TARGETS = [
    ("PPPs",                         "Domain Knowledge/PPPs",                        "1"),
    ("Digital Transformation",       "Domain Knowledge/Digital Transformation",      "2"),
    ("Infrastructure Investment",    "Domain Knowledge/Infrastructure Investment",   "3"),
    ("Infrastructure Policy",        "Domain Knowledge/Infrastructure Policy",       "4"),
    ("Risk Management",              "Domain Knowledge/Risk Management",             "5"),
    ("Sustainability",               "Domain Knowledge/Sustainability",              "6"),
    ("Professional Dev",             "Professional Dev",                             "7"),
    ("Engineering",                  "Engineering",                                  "8"),
]

TYPE_SUBFOLDERS = {"framework": "Frameworks", "playbook": "Playbooks", "claim": "Claims"}


@dataclass
class Config:
    """Runtime configuration. Mutated at startup by main()."""
    vault: Path = DEFAULT_VAULT
    sources: list[Path] = field(default_factory=list)
    archive_base: Path = DEFAULT_VAULT / DEFAULT_ARCHIVE
    filter_tag: Optional[str] = DEFAULT_FILTER_TAG
    targets: list[tuple[str, str, str]] = field(default_factory=lambda: list(DEFAULT_TARGETS))


CFG = Config()


# --- State ----------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"undo_stack": [], "session_skips": []}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


STATE = _load_state()


# --- Artefact discovery ---------------------------------------------------

def _artefact_type(path: Path) -> str:
    """Infer artefact type from the parent directory name."""
    parent = path.parent.name.lower()
    if parent.startswith("framework"):
        return "framework"
    if parent.startswith("playbook"):
        return "playbook"
    if parent.startswith("claim"):
        return "claim"
    return "note"


def _matches_filter(path: Path) -> bool:
    """Return True if the note passes the filter (e.g. has the required tag)."""
    if not CFG.filter_tag:
        return True
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:1500]
    except Exception:
        return False
    return CFG.filter_tag in head


def _list_pending() -> list[Path]:
    """All notes in any configured source folder that match the filter and
    haven't been skipped in the current session."""
    skipped = set(STATE.get("session_skips", []))
    items: list[Path] = []
    for src in CFG.sources:
        if not src.exists():
            continue
        # If the source is a "distilled" layout with Frameworks/Playbooks/Claims
        # subfolders, scan those. Otherwise scan *.md directly (one level deep).
        subdirs = [src / s for s in ("Frameworks", "Playbooks", "Claims")
                   if (src / s).exists()]
        if subdirs:
            for folder in subdirs:
                for p in sorted(folder.glob("*.md")):
                    if str(p) in skipped:
                        continue
                    if _matches_filter(p):
                        items.append(p)
        else:
            # Flat folder (e.g. INBOX): scan *.md files directly
            for p in sorted(src.glob("*.md")):
                if str(p) in skipped:
                    continue
                if _matches_filter(p):
                    items.append(p)
    return items


def _total_on_disk() -> int:
    """Count all notes currently reachable by the scan (ignores skips).
    Used for the progress display."""
    total = 0
    for src in CFG.sources:
        if not src.exists():
            continue
        subdirs = [src / s for s in ("Frameworks", "Playbooks", "Claims")
                   if (src / s).exists()]
        if subdirs:
            for folder in subdirs:
                total += sum(1 for _ in folder.glob("*.md"))
        else:
            total += sum(1 for _ in src.glob("*.md"))
    return total


def _parse_artefact(path: Path) -> dict:
    """Extract title, source, tags, body from a note."""
    content = path.read_text(encoding="utf-8", errors="ignore")

    # Frontmatter parse
    fm: dict = {}
    body = content
    if content.startswith("---"):
        end = content.find("\n---\n", 3)
        if end > 0:
            fm_raw = content[3:end]
            body = content[end + 5:]
            for line in fm_raw.strip().splitlines():
                if ":" in line and not line.strip().startswith("-"):
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')

    # Title
    title_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    # Source conversation wikilink (distilled notes have this)
    conv_match = re.search(r'source_conversation:\s*"?\[\[([^\]]+)\]\]"?', content)
    source_conv = conv_match.group(1).strip() if conv_match else fm.get("source_conversation", "")

    # Tags (multi-line YAML list)
    tags: list[str] = []
    tag_match = re.search(r"^tags:\s*\n((?:\s*-\s*.+\n)+)", content, re.MULTILINE)
    if tag_match:
        for line in tag_match.group(1).strip().splitlines():
            t = line.strip().lstrip("-").strip().strip('"\'')
            if t:
                tags.append(t)

    # Trimmed body (everything after the H1)
    body_after_h1 = body
    if title_match:
        body_after_h1 = body[title_match.end():].lstrip()

    return {
        "path": str(path),
        "rel": str(path.relative_to(CFG.vault)),
        "type": _artefact_type(path),
        "title": title,
        "source_conv": source_conv,
        "score": fm.get("distilled_from_score", ""),
        "tags": tags,
        "date": fm.get("date", ""),
        "body_md": body_after_h1.strip(),
    }


# --- Actions --------------------------------------------------------------

def _move_artefact(path: Path, target_subpath: str) -> Path:
    """Move artefact under 3.RECURSOS/{target_subpath}/. If the note has a
    recognisable type (framework/playbook/claim), place it in the corresponding
    subfolder; otherwise place it directly in the target folder."""
    atype = _artefact_type(path)
    base_dir = CFG.vault / "3.RECURSOS" / target_subpath
    if atype in TYPE_SUBFOLDERS:
        dest_dir = base_dir / TYPE_SUBFOLDERS[atype]
    else:
        dest_dir = base_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name

    if dest.exists():
        stem, ext = dest.stem, dest.suffix
        dest = dest_dir / f"{stem}__dup-{datetime.now().strftime('%H%M%S')}{ext}"

    shutil.move(str(path), str(dest))
    return dest


def _archive_artefact(path: Path) -> Path:
    """Move under the archive base. Typed notes go to subfolder by type."""
    atype = _artefact_type(path)
    if atype in TYPE_SUBFOLDERS:
        dest_dir = CFG.archive_base / TYPE_SUBFOLDERS[atype]
    else:
        dest_dir = CFG.archive_base
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        stem, ext = dest.stem, dest.suffix
        dest = dest_dir / f"{stem}__dup-{datetime.now().strftime('%H%M%S')}{ext}"
    shutil.move(str(path), str(dest))
    return dest


def _mark_reviewed(path: Path) -> Path:
    """Replace the filter tag in frontmatter so future scans skip this note.
    If no filter tag is set, appends a status/reviewed tag instead."""
    content = path.read_text(encoding="utf-8", errors="ignore")
    if CFG.filter_tag and CFG.filter_tag in content[:1500]:
        # Replace the first occurrence of the filter tag
        new_tag = "status/reviewed" if "status/" in CFG.filter_tag else CFG.filter_tag + "-reviewed"
        new_content = content.replace(CFG.filter_tag, new_tag, 1)
        path.write_text(new_content, encoding="utf-8")
    elif "status/review" in content[:1500]:
        # Fallback for legacy distilled artefacts
        new_content = content.replace("status/review", "status/reviewed", 1)
        path.write_text(new_content, encoding="utf-8")
    return path


def _undo_last(state: dict) -> Optional[str]:
    """Revert the most recent action. Returns a user-facing message."""
    if not state.get("undo_stack"):
        return None
    entry = state["undo_stack"].pop()
    action = entry["action"]
    if action in ("move", "archive"):
        dest = Path(entry["dest"])
        source = Path(entry["source"])
        if dest.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(source))
            _save_state(state)
            return f"Undone: restored {source.name}"
    elif action == "keep":
        # Revert the status tag
        path = Path(entry["source"])
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="ignore")
            # Reverse the substitution done by _mark_reviewed
            if CFG.filter_tag:
                reviewed_tag = "status/reviewed" if "status/" in CFG.filter_tag else CFG.filter_tag + "-reviewed"
                new_content = content.replace(reviewed_tag, CFG.filter_tag, 1)
            else:
                new_content = content.replace("status/reviewed", "status/review", 1)
            path.write_text(new_content, encoding="utf-8")
            _save_state(state)
            return f"Undone: unmarked {path.name}"
    elif action == "skip":
        # Remove the last skip entry
        if entry["source"] in state.get("session_skips", []):
            state["session_skips"].remove(entry["source"])
            _save_state(state)
            return f"Undone: un-skipped {Path(entry['source']).name}"
    _save_state(state)
    return None


# --- Rendering ------------------------------------------------------------

def _md_to_html(md: str) -> str:
    """Very lightweight markdown rendering (headings, lists, emphasis, wikilinks)."""
    s = escape(md)
    # Headings
    s = re.sub(r"^###\s+(.+)$", r'<h3>\1</h3>', s, flags=re.MULTILINE)
    s = re.sub(r"^##\s+(.+)$", r'<h2>\1</h2>', s, flags=re.MULTILINE)
    s = re.sub(r"^#\s+(.+)$", r'<h1>\1</h1>', s, flags=re.MULTILINE)
    # Bold + italic (order matters: bold first)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    # Wikilinks (unclickable — just styled)
    s = re.sub(r"\[\[([^\]]+)\]\]", r'<span class="wikilink">\1</span>', s)
    # Blockquotes
    s = re.sub(r"^&gt;\s+(.+)$", r"<blockquote>\1</blockquote>", s, flags=re.MULTILINE)
    # Unordered lists (- ..) — wrap consecutive - lines in <ul>
    def _ul_sub(match):
        items = re.findall(r"^\s*-\s+(.+)$", match.group(0), flags=re.MULTILINE)
        return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"
    s = re.sub(r"(?:^\s*-\s+.+\n?)+", _ul_sub, s, flags=re.MULTILINE)
    # Ordered lists (1. ..)
    def _ol_sub(match):
        items = re.findall(r"^\s*\d+\.\s+(.+)$", match.group(0), flags=re.MULTILINE)
        return "<ol>" + "".join(f"<li>{item}</li>" for item in items) + "</ol>"
    s = re.sub(r"(?:^\s*\d+\.\s+.+\n?)+", _ol_sub, s, flags=re.MULTILINE)
    # Paragraphs (double newlines → <p>, single → <br>)
    parts = [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]
    out_parts = []
    for p in parts:
        if p.startswith(("<h", "<ul", "<ol", "<blockquote")):
            out_parts.append(p)
        else:
            out_parts.append(f"<p>{p.replace(chr(10), '<br>')}</p>")
    return "\n".join(out_parts)


def _render_artefact(item: dict, remaining: int, total: int) -> str:
    """Render the triage view for one artefact."""
    progress_pct = int(100 * (total - remaining) / total) if total else 100
    buttons_html = ""
    for label, subpath, key in CFG.targets:
        buttons_html += (
            f'<form method="post" action="/action" class="btn-form">'
            f'<input type="hidden" name="kind" value="move">'
            f'<input type="hidden" name="target" value="{escape(subpath)}">'
            f'<button class="btn btn-target" data-key="{key}" type="submit">'
            f'<span class="btn-key">[{key}]</span>'
            f'<span class="btn-label">{escape(label)}</span>'
            f'</button></form>\n'
        )

    type_badge = f'<span class="type-badge type-{item["type"]}">{item["type"].upper()}</span>'
    meta_parts = []
    if item.get("source_conv"):
        meta_parts.append(f'<span class="meta-item">From <code>{escape(item["source_conv"])}</code></span>')
    if item.get("score"):
        meta_parts.append(f'<span class="meta-item">Score {escape(str(item["score"]))}</span>')
    if item.get("date"):
        meta_parts.append(f'<span class="meta-item">Date {escape(str(item["date"]))}</span>')
    if item.get("tags"):
        tag_chips = " ".join(
            f'<span class="tag-chip">{escape(t)}</span>'
            for t in item["tags"][:6]
        )
        meta_parts.append(f'<span class="meta-item">{tag_chips}</span>')
    meta_parts.append(f'<span class="meta-item"><code>{escape(item["rel"])}</code></span>')
    meta_html = "\n      ".join(meta_parts)

    undo_available = bool(STATE.get("undo_stack"))
    undo_disabled = "" if undo_available else "disabled"

    body_html = _md_to_html(item["body_md"])

    source_summary = " / ".join(
        str(s.relative_to(CFG.vault)) if s.is_relative_to(CFG.vault) else str(s)
        for s in CFG.sources
    )
    filter_summary = f"filter: {CFG.filter_tag}" if CFG.filter_tag else "no filter"

    # Build target-key legend for the sticky top
    target_legend = " &middot; ".join(
        f'<span class="key-hint"><kbd>{key}</kbd> {escape(label)}</span>'
        for label, _, key in CFG.targets
    )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Triage — {escape(item['title'])[:60]}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="sticky-top">
  <div class="top-bar">
    <div class="top-progress">
      <div class="progress-text">
        <span class="progress-count">{total - remaining} / {total}</span>
        <span class="progress-remaining">{remaining} left</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" style="width: {progress_pct}%"></div>
      </div>
    </div>
    <div class="top-source">
      <span class="top-source-label">{escape(source_summary)}</span>
      <span class="top-filter">· {escape(filter_summary)}</span>
    </div>
    <form method="post" action="/shutdown" class="shutdown-form">
      <button type="submit" class="shutdown-btn">Quit</button>
    </form>
  </div>
  <div class="shortcut-bar">
    <span class="shortcut-group">{target_legend}</span>
    <span class="shortcut-sep">|</span>
    <span class="key-hint"><kbd>a</kbd> Archive</span>
    <span class="key-hint"><kbd>k</kbd> Keep here</span>
    <span class="key-hint"><kbd>s</kbd> Skip</span>
    <span class="key-hint"><kbd>z</kbd> Undo</span>
  </div>
</div>

<div class="main">
  <div class="artefact-card">
    <div class="artefact-head">
      {type_badge}
      <h2 class="artefact-title">{escape(item['title'])}</h2>
    </div>
    <div class="artefact-meta">
      {meta_html}
    </div>
    <div class="artefact-body">{body_html}</div>
  </div>

  <div class="decision-bar">
    <div class="btn-group btn-group-primary">
      {buttons_html}
    </div>
    <div class="btn-group btn-group-secondary">
      <form method="post" action="/action" class="btn-form">
        <input type="hidden" name="kind" value="archive">
        <button class="btn btn-archive" data-key="a" type="submit">
          <span class="btn-key">[a]</span><span class="btn-label">Archive</span>
        </button>
      </form>
      <form method="post" action="/action" class="btn-form">
        <input type="hidden" name="kind" value="keep">
        <button class="btn btn-keep" data-key="k" type="submit">
          <span class="btn-key">[k]</span><span class="btn-label">Keep here</span>
        </button>
      </form>
      <form method="post" action="/action" class="btn-form">
        <input type="hidden" name="kind" value="skip">
        <button class="btn btn-skip" data-key="s" type="submit">
          <span class="btn-key">[s]</span><span class="btn-label">Skip</span>
        </button>
      </form>
      <form method="post" action="/undo" class="btn-form">
        <button class="btn btn-undo" data-key="z" type="submit" {undo_disabled}>
          <span class="btn-key">[z]</span><span class="btn-label">Undo</span>
        </button>
      </form>
    </div>
  </div>

</div>

<script>
  document.addEventListener('keydown', (e) => {{
    if (e.target.matches('input, textarea')) return;
    const btn = document.querySelector(`button[data-key="${{e.key.toLowerCase()}}"]:not([disabled])`);
    if (btn) {{
      e.preventDefault();
      btn.closest('form').submit();
    }}
  }});
</script>
</body>
</html>"""


def _render_done(total: int) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Triage complete</title>
<link rel="stylesheet" href="/static/style.css">
</head><body>
<div class="header"><h1>Triage complete</h1></div>
<div class="main" style="text-align: center; padding-top: 4rem;">
  <h2 style="color: var(--signal-ok); margin-bottom: 1rem;">All {total} artefacts reviewed.</h2>
  <p style="color: var(--text-2);">Nothing left in _Uncategorized that needs attention.</p>
  <form method="post" action="/shutdown" style="margin-top: 2rem;">
    <button class="btn btn-target" type="submit">Shut down</button>
  </form>
</div></body></html>"""


# --- Routes ---------------------------------------------------------------

async def home(request: Request):
    items = _list_pending()
    total = _total_on_disk()
    if not items:
        return HTMLResponse(_render_done(total))
    item = _parse_artefact(items[0])
    html = _render_artefact(item, remaining=len(items), total=total)
    return HTMLResponse(html)


async def action(request: Request):
    form = await request.form()
    kind = form.get("kind", "")
    items = _list_pending()
    if not items:
        return RedirectResponse("/", status_code=303)
    current = items[0]

    if kind == "move":
        target = form.get("target", "")
        if not target:
            return RedirectResponse("/", status_code=303)
        new_path = _move_artefact(current, target)
        STATE["undo_stack"].append({
            "action": "move", "source": str(current), "dest": str(new_path),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
    elif kind == "archive":
        new_path = _archive_artefact(current)
        STATE["undo_stack"].append({
            "action": "archive", "source": str(current), "dest": str(new_path),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
    elif kind == "keep":
        _mark_reviewed(current)
        STATE["undo_stack"].append({
            "action": "keep", "source": str(current),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })
    elif kind == "skip":
        STATE.setdefault("session_skips", []).append(str(current))
        STATE["undo_stack"].append({
            "action": "skip", "source": str(current),
            "ts": datetime.now().isoformat(timespec="seconds"),
        })

    # Keep undo stack bounded
    STATE["undo_stack"] = STATE["undo_stack"][-20:]
    _save_state(STATE)
    return RedirectResponse("/", status_code=303)


async def undo(request: Request):
    _undo_last(STATE)
    return RedirectResponse("/", status_code=303)


async def shutdown(request: Request):
    def _kill():
        os.kill(os.getpid(), signal.SIGTERM)
    # Return response first, then kill
    import threading
    threading.Timer(0.3, _kill).start()
    return HTMLResponse("<h1>Bye.</h1>")


async def stats(request: Request):
    pending = len(_list_pending())
    return JSONResponse({
        "pending": pending,
        "undo_stack_size": len(STATE.get("undo_stack", [])),
        "session_skips": len(STATE.get("session_skips", [])),
    })


# --- App wiring -----------------------------------------------------------

STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = Starlette(routes=[
    Route("/", home),
    Route("/action", action, methods=["POST"]),
    Route("/undo", undo, methods=["POST"]),
    Route("/shutdown", shutdown, methods=["POST"]),
    Route("/stats", stats),
    Mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static"),
])


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Obsidian vault note triage app",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--vault", type=Path, default=DEFAULT_VAULT,
        help=f"Obsidian vault root (default: {DEFAULT_VAULT})",
    )
    parser.add_argument(
        "--source", action="append", default=[],
        help=("Source folder relative to vault root, repeatable. "
              f"Default: {DEFAULT_SOURCE}"),
    )
    parser.add_argument(
        "--archive", default=DEFAULT_ARCHIVE,
        help=f"Archive subfolder relative to vault (default: {DEFAULT_ARCHIVE})",
    )
    parser.add_argument(
        "--filter-tag", default=DEFAULT_FILTER_TAG,
        help=("Only show notes containing this tag in their frontmatter. "
              f"Default: {DEFAULT_FILTER_TAG}"),
    )
    parser.add_argument(
        "--no-filter", action="store_true",
        help="Disable tag filter; show every note in the source folder(s).",
    )
    parser.add_argument(
        "--target", action="append", default=[],
        help=("Add a custom target folder as 'Label|vault-relative-path|key'. "
              "Repeat for multiple. When provided, REPLACES the default targets."),
    )
    parser.add_argument(
        "--port", type=int, default=8090,
        help="Port to serve on (default: 8090)",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Do not auto-open the browser",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    CFG.vault = args.vault.resolve()
    sources = args.source if args.source else [DEFAULT_SOURCE]
    CFG.sources = [CFG.vault / s for s in sources]
    CFG.archive_base = CFG.vault / args.archive
    CFG.filter_tag = None if args.no_filter else args.filter_tag

    if args.target:
        CFG.targets = []
        for spec in args.target:
            parts = spec.split("|")
            if len(parts) != 3:
                print(f"ERROR: --target must be 'Label|path|key', got: {spec}")
                sys.exit(2)
            label, path, key = [p.strip() for p in parts]
            CFG.targets.append((label, path, key))

    # Validate sources
    for src in CFG.sources:
        if not src.exists():
            print(f"ERROR: source folder does not exist: {src}")
            sys.exit(1)

    pending = len(_list_pending())
    print(f"Triage app starting on http://localhost:{args.port}")
    print(f"  Vault:    {CFG.vault}")
    print(f"  Sources:  {', '.join(str(s.relative_to(CFG.vault)) for s in CFG.sources)}")
    print(f"  Archive:  {CFG.archive_base.relative_to(CFG.vault)}")
    print(f"  Filter:   {CFG.filter_tag or '(none)'}")
    print(f"  Targets:  {len(CFG.targets)} folders (keys: {' '.join(k for _,_,k in CFG.targets)})")
    print(f"  Pending:  {pending}")
    print()
    print("Browser shortcuts:")
    print(f"  {' '.join(k for _, _, k in CFG.targets)} → route to target folder")
    print("  a → archive")
    print("  k → keep (mark reviewed, stays in source)")
    print("  s → skip for this session")
    print("  z → undo last action")
    print()

    if not args.no_browser:
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{args.port}")).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
