# extract_pdf_annotations.py

Pull the highlights and margin notes out of a folder of annotated PDFs, and find out how much of that content the vault already holds.

The annotations live in the PDF's own annotation layer, which is what PDF Expert, Preview, Acrobat, Zotero and most other readers write to. The script reads that layer directly, so nothing has to be exported from the reader first.

Read-only with respect to the vault. It writes only to the output directory.

## Why

Two cases.

**Your own reading backlog.** Highlights are a record of what you thought mattered at the time, and they are usually the last thing to make it into notes. The coverage check separates the documents you already wrote up from the ones still sitting unprocessed.

**Documents from other people.** A marked-up PDF that arrives from a colleague, a client or a reviewer carries their judgement about which passages matter. Pulling those out gives you the reading in a few minutes, and the `author` field on each annotation preserves who made which mark when a document has been round several people.

## Usage

```bash
source venv/bin/activate

# Extract and check against the default vault
python extract_pdf_annotations.py --source ~/Documents/papers

# Extraction only, no vault check
python extract_pdf_annotations.py --source ./inbox --out ./annots --no-coverage

# A different vault
python extract_pdf_annotations.py --source ./papers --vault ~/obsidian/Other
```

| Flag | Meaning |
|------|---------|
| `--source` | Folder holding the PDFs, searched recursively. Required |
| `--out` | Output directory. Default `./pdf-annotations` |
| `--vault` | Vault to check against. Default `/Users/jose/obsidian/JC` |
| `--no-coverage` | Skip the vault check |
| `--quiet` | Suppress progress output |

## Output

| File | Contents |
|------|----------|
| `digest.md` | Readable digest: coverage table, then every marked passage grouped by document, with page numbers and any written notes. Start here |
| `<name>.json` | One per annotated PDF: each annotation with page, type, recovered text, the reader's note, author and date |
| `_index.json` | Per-file counts of annotations, pages touched and written notes |
| `_coverage.json` | Per-file match rates plus the full list of passages **not** found in the vault |

The `misses` list in `_coverage.json` is the useful part: those are the marked passages with no equivalent anywhere in the vault.

## Reading the coverage figure

Each marked passage is normalised (accents stripped, punctuation removed, case folded) and three eight-word windows are tested against every markdown note in the vault. A passage counts as present if any window is found.

- **95% or more** means the document is already written up. Nothing to do
- **Under about 20%** means the marked content is not in the vault
- **Anything between** usually means a partial note exists, or the passages are short and generic enough to match by coincidence. Check `misses` before concluding

Passages shorter than six words are skipped, because a three-word highlight will match something somewhere by chance. They still appear in `digest.md` and the per-file JSON.

Note that running the script again after writing notes from the digest will show high coverage, because the new notes are themselves in the vault. That is a useful way to confirm the quotes landed faithfully.

## Annotation types handled

Text selections (highlight, underline, squiggly, strikeout) yield the text underneath, recovered from the annotation's quadpoints.

Region marks (square, circle, ink, line, polygon) yield whatever text sits inside the marked rectangle, capped at 600 characters. These are how figures and tables usually get flagged.

Sticky notes and free text yield the written comment. Links and popups are skipped.

An annotation with no text and no comment is dropped.

## Two things that were got wrong first time

Both are fixed, and both are worth knowing if this code is ever extended.

**Column interleaving.** Using `page.get_textbox()` on a highlight rectangle returns text in layout order, so a highlight spanning a two-column journal page comes back with the columns interleaved into nonsense. The fix is to collect words whose centre falls inside the rectangle and sort them by `(block, line, word)`, which is true reading order.

**Cross-document contamination.** The page-text cache was originally keyed on `id(page.parent)`. CPython reuses object ids once a document is closed, so a later document could hit a cache entry belonging to an earlier one, and passages from one PDF appeared under another PDF's page numbers. The cache is now keyed on page number and cleared for every document. Any caching added here must be per-document, and must not trust `id()` to be unique across a run.

## Requirements

`pymupdf`, already in `requirements.txt`.
