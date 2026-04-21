# Triage App

One-at-a-time review of notes in an Obsidian vault with keyboard-driven
routing, archive, keep-here (mark reviewed) and skip actions. Survives
interruption: persistent state, undo stack.

## Quick start

```bash
cd ~/mylab/obsidian-tools
./venv/bin/python -m triage_app
```

Opens a browser at `http://localhost:8090`. Default behaviour: triage
distilled artefacts in `3.RECURSOS/Domain Knowledge/_Uncategorized/` that
carry `status/review` in frontmatter.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `1`-`8` | Route to target folder (labels shown on buttons) |
| `a` | Archive → `4.ARCHIVO/ChatGPT Distilled - Archived/` |
| `k` | Keep here — flip the filter tag to `status/reviewed` so future scans skip |
| `s` | Skip — defer in this session (shown again next launch unless kept/archived) |
| `z` | Undo last action |

## CLI

```
--vault PATH             Override vault root (default: ~/obsidian/JC)
--source PATH            Source folder relative to vault. Repeat for multiple
                         sources. Default: 3.RECURSOS/Domain Knowledge/_Uncategorized
--archive PATH           Archive destination relative to vault.
                         Default: 4.ARCHIVO/ChatGPT Distilled - Archived
--filter-tag TAG         Show only notes containing this tag in frontmatter.
                         Default: status/review
--no-filter              Disable tag filter — show every note in source folder(s)
--target "Label|path|key"  Replace default target folders. Repeat for each.
                         Example: --target "Ideas|1.PROYECTOS/Writings/Ideas|1"
--port N                 Default: 8090
--no-browser             Don't auto-open browser
```

## Common use cases

### Triage distilled residuals (default)

```bash
./venv/bin/python -m triage_app
```

### Process INBOX

```bash
./venv/bin/python -m triage_app --source "0.INBOX" --no-filter
```

(All INBOX notes, no tag filter.)

### Review only notes tagged `status/draft` across Writings

```bash
./venv/bin/python -m triage_app \
    --source "1.PROYECTOS/Writings/Drafts" \
    --filter-tag "status/draft"
```

### Custom target folders for an INBOX triage

```bash
./venv/bin/python -m triage_app \
    --source "0.INBOX" --no-filter \
    --target "Writings Ideas|1.PROYECTOS/Writings/Ideas|1" \
    --target "TYPSA|1.PROYECTOS/TYPSA|2" \
    --target "Domain Knowledge|3.RECURSOS/Domain Knowledge|3" \
    --target "AI & ML|3.RECURSOS/AI & ML|4"
```

## How routing works

- If the source folder has `Frameworks/`, `Playbooks/`, `Claims/` subfolders,
  the app scans those and infers type from the parent folder. Moves preserve
  the subfolder structure in the target (e.g. an artefact in `Frameworks/`
  moves to `target/Frameworks/`).
- Otherwise (flat folder like INBOX), the app scans `*.md` at the top level
  and moves directly into the target folder.

## State

- `state.json` in the app folder stores the undo stack (last 20 actions)
  and session skips. Delete this file to reset.
- Skips are per-launch: skipped notes reappear in the next session.
- `keep here` flips the filter tag in the note itself, so the filter will
  exclude it on future scans (permanent until you edit the note).

## Architecture

Single-file Starlette app, server-side rendered HTML, minimal JS for the
keyboard shortcut handler. Reuses the paco dashboard colour palette (dark
industrial). No build step, no framework.
