#!/usr/bin/env python3
"""Extract highlights and notes from annotated PDFs, and check them against the vault.

Reads the PDF annotation layer written by PDF Expert, Preview, Acrobat, Zotero and
most other readers, recovers the text sitting under each highlight, and reports
which of those passages already appear somewhere in the Obsidian vault.

Useful for triaging a reading backlog, and for documents received from other
people, where their highlights show what they thought mattered.

Read-only: it never writes to the vault, only to the output directory.

Usage:
    python extract_pdf_annotations.py --source ~/Documents/papers
    python extract_pdf_annotations.py --source ./papers --out ./annots --no-coverage
    python extract_pdf_annotations.py --source ./papers --vault ~/obsidian/JC

Output in the target directory:
    <name>.json    one file per annotated PDF, every annotation with page and type
    _index.json    per-file counts
    _coverage.json coverage results, when the vault check runs
    digest.md      readable digest of everything marked, grouped by document
"""

import argparse
import json
import os
import re
import sys
import unicodedata

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("PyMuPDF is required: pip install pymupdf")

DEFAULT_VAULT = "/Users/jose/obsidian/JC"

# Annotation subtypes that carry a text selection.
MARKUP = {8: "Highlight", 9: "Underline", 10: "Squiggly", 11: "StrikeOut"}
# Annotation subtypes worth keeping that sit over a region instead.
REGION = {0: "Text", 2: "FreeText", 15: "Ink", 4: "Square", 5: "Circle",
          3: "Line", 6: "Polygon", 7: "PolyLine", 12: "Stamp", 13: "Caret",
          17: "FileAttachment"}
SKIP = {1, 16}  # Link, Popup

# Probe settings for the vault coverage check.
PROBE_WORDS = 8
MIN_WORDS = 6

_WORDCACHE = {}


def clean(text):
    """Normalise extracted text into a single readable line."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("­", "")               # soft hyphen
    text = re.sub(r"-\n(?=[a-zà-ÿ])", "", text)     # de-hyphenate line breaks
    text = re.sub(r"\s*\n\s*", " ", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def words_of(page):
    """Word tuples for a page, cached.

    Keyed on page number only. The cache is cleared for every document:
    keying on id(page.parent) is unsafe because CPython reuses object ids
    once a document is closed, which silently mixes pages between PDFs.
    """
    if page.number not in _WORDCACHE:
        # (x0, y0, x1, y1, word, block_no, line_no, word_no)
        _WORDCACHE[page.number] = page.get_text("words")
    return _WORDCACHE[page.number]


def words_in(page, rect):
    """Words whose centre falls inside rect, in reading order.

    Sorting by (block, line, word) stops a selection that spans two columns
    from coming back interleaved, which is what page.get_textbox() does.
    """
    found = []
    for w in words_of(page):
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1:
            found.append(w)
    found.sort(key=lambda w: (w[5], w[6], w[7]))
    return found


def selected_text(page, annot):
    """Recover the text a markup annotation covers, via its quadpoints."""
    vertices = annot.vertices
    rects = []
    if vertices:
        # Quadpoints arrive in groups of four points, one group per line.
        for i in range(0, len(vertices), 4):
            quad = vertices[i:i + 4]
            if len(quad) < 4:
                break
            rects.append(fitz.Quad(quad).rect)
    else:
        rects = [annot.rect]

    seen, out = set(), []
    for r in rects:
        padded = fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)
        for w in words_in(page, padded):
            key = (w[5], w[6], w[7])
            if key not in seen:
                seen.add(key)
                out.append(w)
    out.sort(key=lambda w: (w[5], w[6], w[7]))
    return clean(" ".join(w[4] for w in out))


def extract_one(path):
    """Return (annotations, counts, metadata) for a single PDF."""
    doc = fitz.open(path)
    _WORDCACHE.clear()
    items, counts = [], {}

    for pno in range(doc.page_count):
        page = doc[pno]
        for annot in page.annots() or []:
            subtype = annot.type[0]
            if subtype in SKIP:
                continue
            kind = (MARKUP.get(subtype) or REGION.get(subtype)
                    or annot.type[1] or f"type{subtype}")
            info = annot.info or {}
            record = {
                "page": pno + 1,
                "kind": kind,
                "author": info.get("title", "") or "",
                "note": clean(info.get("content", "")),
                "date": info.get("modDate", "") or info.get("creationDate", ""),
            }
            if subtype in MARKUP:
                record["text"] = selected_text(page, annot)
            elif kind in ("Ink", "Square", "Circle", "Line", "Polygon"):
                record["text"] = clean(
                    " ".join(w[4] for w in words_in(page, annot.rect)))[:600]
            else:
                record["text"] = ""

            if not record["text"] and not record["note"]:
                continue
            counts[kind] = counts.get(kind, 0) + 1
            items.append(record)

    meta = doc.metadata or {}
    doc.close()
    return items, counts, meta


def norm_for_match(text):
    """Aggressively normalise text so probes survive formatting differences."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("’", "'").replace("‐", "-")
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_vault(vault):
    """Concatenate every markdown note into one normalised blob."""
    chunks, count = [], 0
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs
                   if d not in (".git", ".obsidian", "node_modules", ".trash")]
        for fn in files:
            if not fn.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, fn), encoding="utf-8",
                          errors="ignore") as f:
                    chunks.append(norm_for_match(f.read()))
                count += 1
            except OSError:
                pass
    return " \n ".join(chunks), count


def check_coverage(results, vault_text):
    """For each document, what share of its marked passages is already in the vault."""
    rows = []
    for res in results:
        tested = matched = 0
        misses = []
        for a in res["annots"]:
            words = norm_for_match(a.get("text", "")).split()
            if len(words) < MIN_WORDS:
                continue
            tested += 1
            starts = {0,
                      max(0, (len(words) - PROBE_WORDS) // 2),
                      max(0, len(words) - PROBE_WORDS)}
            probes = [" ".join(words[s:s + PROBE_WORDS]) for s in starts]
            if any(p in vault_text for p in probes):
                matched += 1
            else:
                misses.append({"page": a["page"], "text": a["text"][:200]})
        rows.append({
            "file": res["file"],
            "total_annotations": len(res["annots"]),
            "tested": tested,
            "matched": matched,
            "pct": round(100 * matched / tested, 1) if tested else None,
            "misses": misses,
        })
    return rows


def write_digest(path, results, coverage):
    """Write a readable markdown digest of every marked passage."""
    cov = {c["file"]: c for c in (coverage or [])}
    lines = ["# PDF annotation digest", ""]
    total = sum(len(r["annots"]) for r in results)
    lines.append(f"{len(results)} annotated documents, {total} annotations.")
    lines.append("")

    if coverage:
        lines.append("## Coverage against the vault")
        lines.append("")
        lines.append("| Already in vault | Matched / tested | All marks | Document |")
        lines.append("|---|---|---|---|")
        for c in sorted(coverage, key=lambda x: (x["pct"] is None, x["pct"] or 0)):
            pct = "n/a" if c["pct"] is None else f"{c['pct']:.0f}%"
            lines.append(f"| {pct} | {c['matched']}/{c['tested']} | "
                         f"{c['total_annotations']} | {c['file']} |")
        lines.append("")

    for res in sorted(results, key=lambda r: -len(r["annots"])):
        lines.append(f"## {res['file']}")
        lines.append("")
        bits = ", ".join(f"{v} {k.lower()}" for k, v in sorted(res["counts"].items()))
        c = cov.get(res["file"])
        if c and c["pct"] is not None:
            bits += f" | {c['pct']:.0f}% already in the vault"
        lines.append(f"*{bits}*")
        lines.append("")
        for a in res["annots"]:
            if a["text"]:
                lines.append(f"- **p{a['page']}** ({a['kind'].lower()}) {a['text']}")
            else:
                lines.append(f"- **p{a['page']}** ({a['kind'].lower()})")
            if a["note"]:
                lines.append(f"    - *Note by {a['author'] or 'reader'}:* {a['note']}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(
        description="Extract PDF highlights and notes, and check them against an "
                    "Obsidian vault.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True,
                    help="Folder containing the PDFs (searched recursively)")
    ap.add_argument("--out", default=None,
                    help="Output directory (default: ./pdf-annotations)")
    ap.add_argument("--vault", default=DEFAULT_VAULT,
                    help=f"Vault to check against (default: {DEFAULT_VAULT})")
    ap.add_argument("--no-coverage", action="store_true",
                    help="Skip the vault coverage check")
    ap.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = ap.parse_args()

    source = os.path.expanduser(args.source)
    if not os.path.isdir(source):
        sys.exit(f"Source folder not found: {source}")
    out = os.path.expanduser(args.out or "./pdf-annotations")
    os.makedirs(out, exist_ok=True)

    pdfs = []
    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.lower().endswith(".pdf"):
                pdfs.append(os.path.join(root, fn))
    pdfs.sort()
    if not pdfs:
        sys.exit(f"No PDFs found under {source}")

    results, index = [], []
    for path in pdfs:
        rel = os.path.relpath(path, source)
        try:
            items, counts, meta = extract_one(path)
        except Exception as exc:                      # noqa: BLE001
            index.append({"file": rel, "error": str(exc)})
            if not args.quiet:
                print(f"  failed: {rel}: {exc}", file=sys.stderr)
            continue

        if not items:
            index.append({"file": rel, "n": 0, "counts": {}})
            continue

        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", rel)[:120]
        payload = {"file": rel, "path": path, "title": meta.get("title", ""),
                   "counts": counts, "annots": items}
        with open(os.path.join(out, stem + ".json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        results.append(payload)
        index.append({"file": rel, "n": len(items), "counts": counts,
                      "pages": len({i["page"] for i in items}),
                      "notes": sum(1 for i in items if i["note"])})

    with open(os.path.join(out, "_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    coverage = None
    if not args.no_coverage:
        vault = os.path.expanduser(args.vault)
        if not os.path.isdir(vault):
            print(f"Vault not found, skipping coverage: {vault}", file=sys.stderr)
        else:
            if not args.quiet:
                print("Loading vault for the coverage check...", file=sys.stderr)
            vault_text, n_notes = load_vault(vault)
            if not args.quiet:
                print(f"  {n_notes} notes, {len(vault_text) / 1e6:.1f}M characters",
                      file=sys.stderr)
            coverage = check_coverage(results, vault_text)
            with open(os.path.join(out, "_coverage.json"), "w",
                      encoding="utf-8") as f:
                json.dump(coverage, f, ensure_ascii=False, indent=1)

    write_digest(os.path.join(out, "digest.md"), results, coverage)

    if not args.quiet:
        total = sum(len(r["annots"]) for r in results)
        print(f"\n{len(pdfs)} PDFs scanned, {len(results)} annotated, "
              f"{total} annotations.")
        if coverage:
            print(f"\n{'in vault':>9}  {'matched':>12}  {'marks':>5}  document")
            for c in sorted(coverage, key=lambda x: (x["pct"] is None,
                                                     x["pct"] or 0)):
                pct = "n/a" if c["pct"] is None else f"{c['pct']:.0f}%"
                print(f"{pct:>9}  {c['matched']:>5}/{c['tested']:<6}  "
                      f"{c['total_annotations']:>5}  {c['file']}")
        print(f"\nWritten to {out} (see digest.md)")


if __name__ == "__main__":
    main()
