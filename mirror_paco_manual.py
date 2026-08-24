#!/usr/bin/env python3
"""Mirror the PACO Manual chapters into the vault as read-only notes.

Master: ~/mylab/paco-manual/*.qmd (git repo). Mirror:
~/obsidian/JC/1.PROYECTOS/PACO/Manual/ as Obsidian notes, one-way.
Run after each render. Converts Quarto callouts to Obsidian callouts,
strips the enabler-mark spans to plain glyphs, and rewrites figures to
wikilinks. The PNGs go to the vault's Attachments folder under a
paco-manual- prefix, the way every other vault image is stored.

Usage: python3 mirror_paco_manual.py
"""
import re
import shutil
from datetime import date
from pathlib import Path

VAULT = Path.home() / "obsidian/JC"
MASTER = Path.home() / "mylab/paco-manual"
MIRROR = VAULT / "1.PROYECTOS/PACO/Manual"
DESIGN_MIRROR = VAULT / "1.PROYECTOS/PACO/Manual Design"
FIGS = VAULT / "Attachments"
FIG_PREFIX = "paco-manual-"

TITLES = {"index": "Cover"}
TITLES_ES = {"index": "Portada"}


def convert(text: str, notes: dict) -> str:
    # Quarto callouts -> Obsidian callouts
    def callout(m):
        kind = m.group(1)
        body = m.group(2).strip("\n")
        lines = [f"> [!{kind}]"] + [f"> {l}" if l.strip() else ">" for l in body.split("\n")]
        return "\n".join(lines) + "\n"
    text = re.sub(r"::: \{\.callout-(\w+)[^\n]*\}\n(.*?)\n:::\n", callout, text, flags=re.S)
    # Quarto fence attributes -> plain fences for Obsidian
    text = text.replace("```{.text .sourceCode}", "```text")
    # html-only blocks (cover card grid) dropped; print-only blocks unwrapped
    text = re.sub(r"::: \{\.content-visible when-format=\"html\"\}\n.*?\n:::\n:::\n", "", text, flags=re.S)
    text = re.sub(r"::: \{\.content-visible unless-format=\"html\"\}\n(.*?)\n:::\n", r"\1\n", text, flags=re.S)
    text = re.sub(r"::: \{\.cover-promise\}\n(.*?)\n:::\n", r"> \1\n", text, flags=re.S)
    # case labels -> bold
    text = re.sub(r"^(You say|You get|Why this works):", r"**\1:**", text, flags=re.M)
    # enabler mark spans -> plain glyph
    text = re.sub(r"\[([^\]]{1,3})\]\{\.en\d\}", r"\1", text)
    # figures -> wikilinks with caption
    def fig(m):
        cap, fname = m.group(1), Path(m.group(2)).name
        return f"![[{FIG_PREFIX}{fname}]]\n*{cap}*"
    # the trailing attribute block is optional: not every figure line carries {width=100%}
    text = re.sub(r"!\[([^\]]*)\]\(figures/([^)]+)\)(?:\{[^}]*\})?", fig, text)
    # chapter links -> wikilinks
    def link(mm):
        label, stem = mm.group(1), mm.group(2)
        return f"[[{notes[stem][:-3]}|{label}]]" if stem in notes else mm.group(0)
    text = re.sub(r"\[([^\]]+)\]\((\d\d-[a-z-]+)\.(?:qmd|html)\)", link, text)
    return text


def main():
    MIRROR.mkdir(parents=True, exist_ok=True)
    DESIGN_MIRROR.mkdir(parents=True, exist_ok=True)
    FIGS.mkdir(exist_ok=True)
    masters = {FIG_PREFIX + png.name: png for png in (MASTER / "figures").glob("*.png")}
    for name, png in masters.items():
        shutil.copy2(png, FIGS / name)
    # only prefixed files are ours: never touch the rest of Attachments
    for old in FIGS.glob(FIG_PREFIX + "*.png"):
        if old.name not in masters:
            old.unlink()
    written = 0
    notes = {}
    for qmd in sorted(MASTER.glob("*.qmd")):
        stem = qmd.stem
        body = re.sub(r"\A---\n.*?\n---\n\n?", "", qmd.read_text(), flags=re.S)
        m = re.search(r"^# (.+)$", body, flags=re.M)
        title = re.sub(r"\[([^\]]{1,3})\]\{\.en\d\}", r"\1", m.group(1) if m else stem)
        base = stem[:-3] if stem.endswith(".es") else stem
        num = "00" if base == "index" else ("00a" if base == "00-foreword" else base.split("-")[0])
        if stem.endswith(".es"):
            num = "ES " + num
        safe = re.sub(r'[\\/:*?"<>|]', "", (TITLES_ES if stem.endswith(".es") else TITLES).get(base, title))
        safe = re.sub(r"^[■▲⬢✚◆★]\s*", "", safe)  # keep marks in headings, out of filenames
        notes[stem] = f"PACO Manual {num} - {safe}.md"
    for qmd in sorted(MASTER.glob("*.qmd")):
        stem = qmd.stem
        body = re.sub(r"\A---\n.*?\n---\n\n?", "", qmd.read_text(), flags=re.S)
        m = re.search(r"^# (.+)$", body, flags=re.M)
        title = m.group(1) if m else stem
        if stem == "index":
            body = "# The PACO Manual\n\n" + body
        if stem == "index.es":
            body = "# El manual de PACO\n\n" + body
        title = re.sub(r"\[([^\]]{1,3})\]\{\.en\d\}", r"\1", title)
        out = MIRROR / notes[stem]
        front = (
            "---\n"
            f'date: "{date.today().isoformat()}"\n'
            "type: reference\n"
            f"tags:\n  - type/reference\n  - lang/{'es' if stem.endswith('.es') else 'en'}\n"
            "  - context/paco\n  - topic/ai\n"
            f'source: "~/mylab/paco-manual/{qmd.name}"\n'
            "mirror: true\n"
            # the mirror is a target, never a weave source: keep the skip-flag durable
            "links_woven: true\n"
            "---\n\n"
            "> [!info] Read-only mirror of the PACO Manual master. Edit the Quarto source, then re-run `mirror_paco_manual.py`.\n\n"
        )
        out.write_text(front + convert(body, notes))
        written += 1
    # remove stale mirror notes whose source disappeared
    keep = set(notes.values())
    for note in MIRROR.glob("PACO Manual *.md"):
        if note.name not in keep:
            note.unlink()
    # design artifacts (diagram briefs) mirror into the manual's production folder
    design = MASTER / "design"
    for src, lang, name in (("diagram-briefs.qmd", "en", "PACO Manual Design - Diagram briefs (EN).md"),
                            ("diagram-briefs.es.qmd", "es", "PACO Manual Design - Diagram briefs (ES).md")):
        if (design / src).exists():
            front = ("---\n" f'date: "{date.today().isoformat()}"\n' "type: reference\n"
                     f"tags:\n  - type/reference\n  - lang/{lang}\n  - context/paco\n  - topic/ai\n"
                     f'source: "~/mylab/paco-manual/design/{src}"\n' "mirror: true\n---\n\n"
                     "> [!info] Read-only mirror of the design briefs kept in the manual repository (`design/`). Edit the source, then re-run `mirror_paco_manual.py`.\n\n")
            (DESIGN_MIRROR / name).write_text(front + convert((design / src).read_text(), notes))
    print(f"mirrored {written} chapters into {MIRROR}")


if __name__ == "__main__":
    main()
