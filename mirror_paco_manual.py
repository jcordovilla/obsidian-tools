#!/usr/bin/env python3
"""Mirror the PACO Manual chapters into the vault as read-only notes.

Master: ~/project-docs/PACO Manual/*.qmd (Quarto book). Mirror:
~/obsidian/JC/1.PROYECTOS/PACO/Manual/ as Obsidian notes, one-way.
Run after each render. Converts Quarto callouts to Obsidian callouts,
strips the enabler-mark spans to plain glyphs, and rewrites figures to
wikilinks with the PNGs copied alongside.

Usage: python3 mirror_paco_manual.py
"""
import re
import shutil
from datetime import date
from pathlib import Path

MASTER = Path.home() / "project-docs/PACO Manual"
MIRROR = Path.home() / "obsidian/JC/1.PROYECTOS/PACO/Manual"
FIGS = MIRROR / "figures"

TITLES = {"index": "Foreword"}


def convert(text: str) -> str:
    # Quarto callouts -> Obsidian callouts
    def callout(m):
        kind = m.group(1)
        body = m.group(2).strip("\n")
        lines = [f"> [!{kind}]"] + [f"> {l}" if l.strip() else ">" for l in body.split("\n")]
        return "\n".join(lines) + "\n"
    text = re.sub(r"::: \{\.callout-(\w+)[^\n]*\}\n(.*?)\n:::\n", callout, text, flags=re.S)
    # enabler mark spans -> plain glyph
    text = re.sub(r"\[([^\]]{1,3})\]\{\.en\d\}", r"\1", text)
    # figures -> wikilinks with caption
    def fig(m):
        cap, fname = m.group(1), Path(m.group(2)).name
        return f"![[{fname}]]\n*{cap}*"
    text = re.sub(r"!\[([^\]]*)\]\(figures/([^)]+)\)\{[^}]*\}", fig, text)
    return text


def main():
    MIRROR.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(exist_ok=True)
    for png in (MASTER / "figures").glob("*.png"):
        shutil.copy2(png, FIGS / png.name)
    written = 0
    for qmd in sorted(MASTER.glob("*.qmd")):
        stem = qmd.stem
        body = qmd.read_text()
        m = re.match(r"# (.+)\n", body)
        title = m.group(1) if m else stem
        title = re.sub(r"\[([^\]]{1,3})\]\{\.en\d\}", r"\1", title)
        num = "00" if stem == "index" else stem.split("-")[0]
        label = TITLES.get(stem, title)
        safe = re.sub(r'[\\/:*?"<>|]', "", label)
        safe = re.sub(r"^[■▲⬢✚◆★]\s*", "", safe)  # keep marks in headings, out of filenames
        out = MIRROR / f"PACO Manual {num} - {safe}.md"
        front = (
            "---\n"
            f'date: "{date.today().isoformat()}"\n'
            "type: reference\n"
            "tags:\n  - type/reference\n  - lang/en\n  - context/paco\n  - topic/ai\n"
            f'source: "~/project-docs/PACO Manual/{qmd.name}"\n'
            "mirror: true\n"
            "---\n\n"
            "> [!info] Read-only mirror of the PACO Manual master. Edit the Quarto source, then re-run `mirror_paco_manual.py`.\n\n"
        )
        out.write_text(front + convert(body))
        written += 1
    # remove stale mirror notes whose source disappeared
    keep = {f"PACO Manual {('00' if q.stem == 'index' else q.stem.split('-')[0])}" for q in MASTER.glob("*.qmd")}
    for note in MIRROR.glob("PACO Manual *.md"):
        if not any(note.name.startswith(k + " ") for k in keep):
            note.unlink()
    print(f"mirrored {written} chapters into {MIRROR}")


if __name__ == "__main__":
    main()
