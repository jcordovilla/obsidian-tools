#!/usr/bin/env python3
"""
Shared DOCX formatting/sanitation helpers for the obsidian-tools DOCX pipeline
(fill_template.py and export_to_docx.py).

Purpose: make generated TYPSA documents come out clean by default, without a
manual post-processing pass. Fixes the recurring bugs seen in practice:

  - double heading indices (Word auto-numbering + a manual "N." in the text),
  - empty paragraphs and stray empty bullets left by cleared template slots,
  - tables that do not span the text width, with mis-proportioned columns,
    justified cells with large gaps, and rows that split across pages.

All functions operate on a python-docx Document in place.
"""

import re

from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Column-width fractions of the usable text width, keyed by column count.
# Tuned for the two RRAM minutes tables (participants: org/name/function;
# actions: ref/owner/action/timing). Any other column count splits evenly.
DEFAULT_TABLE_FRACTIONS = {
    3: [0.24, 0.30, 0.46],
    4: [0.07, 0.17, 0.56, 0.20],
}


def strip_leading_number(text):
    """Drop a leading manual section number ("1. ", "10.2 ", "3) ") so it does
    not double up with Word's heading auto-numbering."""
    if not text:
        return text
    return re.sub(r'^\s*\d+([.)]\d+)*[.)]\s+', '', text)


def _paragraph_is_empty(p):
    """True only for a genuinely empty paragraph: no text and no drawing,
    picture or break (page breaks and images must be preserved)."""
    if p.text.strip():
        return False
    for tag in ('w:drawing', 'w:pict', 'w:br', 'w:object'):
        if p._p.findall('.//' + qn(tag)):
            return False
    return True


def remove_empty_paragraphs(doc):
    """Delete empty body paragraphs (blank lines and emptied bullet slots)."""
    removed = 0
    for p in list(doc.paragraphs):
        if _paragraph_is_empty(p):
            p._p.getparent().remove(p._p)
            removed += 1
    return removed


def disable_paragraph_numbering(p):
    """Force numId 0 (no list) on a paragraph, overriding any style- or
    direct-numbering it would otherwise inherit."""
    pPr = p._p.get_or_add_pPr()
    for np in pPr.findall(qn('w:numPr')):
        pPr.remove(np)
    numPr = OxmlElement('w:numPr')
    for tag, val in (('w:ilvl', '0'), ('w:numId', '0')):
        e = OxmlElement(tag)
        e.set(qn('w:val'), val)
        numPr.append(e)
    pStyle = pPr.find(qn('w:pStyle'))
    if pStyle is not None:
        pStyle.addnext(numPr)
    else:
        pPr.insert(0, numPr)


def disable_heading_autonumber(doc):
    """Turn off inherited heading/title auto-numbering across the document.
    Use for free-form prose exports where numbered headings are unwanted."""
    for p in doc.paragraphs:
        name = (p.style.name or '') if p.style else ''
        if name.startswith('Heading') or name == 'Title':
            disable_paragraph_numbering(p)


def _usable_twips(section):
    return int((section.page_width - section.left_margin - section.right_margin) / 635)


def _set_table_cell_margins(table, top=28, bottom=28, left=90, right=90):
    tblPr = table._tbl.tblPr
    old = tblPr.find(qn('w:tblCellMar'))
    if old is not None:
        tblPr.remove(old)
    mar = OxmlElement('w:tblCellMar')
    for side, val in (('top', top), ('bottom', bottom), ('left', left), ('right', right)):
        e = OxmlElement('w:' + side)
        e.set(qn('w:w'), str(val))
        e.set(qn('w:type'), 'dxa')
        mar.append(e)
    tblPr.append(mar)


def _set_fixed_layout(table, total):
    tblPr = table._tbl.tblPr
    for tag in ('w:tblW', 'w:tblLayout'):
        e = tblPr.find(qn(tag))
        if e is not None:
            tblPr.remove(e)
    tblW = OxmlElement('w:tblW')
    tblW.set(qn('w:w'), str(total))
    tblW.set(qn('w:type'), 'dxa')
    tblPr.append(tblW)
    lay = OxmlElement('w:tblLayout')
    lay.set(qn('w:type'), 'fixed')
    tblPr.append(lay)


def normalize_tables(doc, fractions=None):
    """Give every table a full-width fixed layout with proportional columns,
    left-aligned cells, tight cell margins, and rows that do not split across
    pages. Removes empty leading/trailing paragraphs inside cells."""
    fractions = fractions or DEFAULT_TABLE_FRACTIONS
    usable = _usable_twips(doc.sections[0])

    for t in doc.tables:
        ncols = len(t.columns)
        fr = fractions.get(ncols, [1.0 / ncols] * ncols)
        widths = [int(f * usable) for f in fr]
        widths[-1] = usable - sum(widths[:-1])  # keep the exact total

        _set_fixed_layout(t, usable)
        _set_table_cell_margins(t)

        grid = t._tbl.find(qn('w:tblGrid'))
        if grid is not None:
            for c in grid.findall(qn('w:gridCol')):
                grid.remove(c)
            for w in widths:
                gc = OxmlElement('w:gridCol')
                gc.set(qn('w:w'), str(w))
                grid.append(gc)

        for row in t.rows:
            trPr = row._tr.get_or_add_trPr()
            if trPr.find(qn('w:cantSplit')) is None:
                trPr.append(OxmlElement('w:cantSplit'))
            for i, cell in enumerate(row.cells):
                tcPr = cell._tc.get_or_add_tcPr()
                tcW = tcPr.find(qn('w:tcW'))
                if tcW is None:
                    tcW = OxmlElement('w:tcW')
                    tcPr.append(tcW)
                tcW.set(qn('w:w'), str(widths[i] if i < len(widths) else widths[-1]))
                tcW.set(qn('w:type'), 'dxa')
                cps = cell.paragraphs
                for p in cps:
                    if len(cps) > 1 and _paragraph_is_empty(p):
                        p._p.getparent().remove(p._p)
                for p in cell.paragraphs:
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    pf = p.paragraph_format
                    pf.space_before = Pt(0)
                    pf.space_after = Pt(1)


# ---------------------------------------------------------------------------
# Content-aware table layout (opt-in from export_to_docx.py --fit-tables)
# ---------------------------------------------------------------------------
import copy as _copy

_TWIPS_PER_CM = 567


def _sectPr_usable_twips(sectPr):
    pgSz = sectPr.find(qn('w:pgSz')); pgMar = sectPr.find(qn('w:pgMar'))
    w = int(pgSz.get(qn('w:w'))); l = int(pgMar.get(qn('w:left'))); r = int(pgMar.get(qn('w:right')))
    return w - l - r


def _make_sectPr(base_sectPr, landscape):
    """Copy a sectPr, force a next-page break and the requested orientation."""
    sp = _copy.deepcopy(base_sectPr)
    pgSz = sp.find(qn('w:pgSz'))
    w, h = int(pgSz.get(qn('w:w'))), int(pgSz.get(qn('w:h')))
    is_land = pgSz.get(qn('w:orient')) == 'landscape'
    if landscape != is_land:
        pgSz.set(qn('w:w'), str(h)); pgSz.set(qn('w:h'), str(w))
    if landscape:
        pgSz.set(qn('w:orient'), 'landscape')
    elif qn('w:orient') in pgSz.attrib:
        del pgSz.attrib[qn('w:orient')]
    typ = sp.find(qn('w:type'))
    if typ is None:
        typ = OxmlElement('w:type'); sp.insert(0, typ)
    typ.set(qn('w:val'), 'nextPage')
    # page numbering continues across the inserted sections
    pg = sp.find(qn('w:pgNumType'))
    if pg is not None and qn('w:start') in pg.attrib:
        del pg.attrib[qn('w:start')]
    # the first-page header/footer variant applies to the document's first page only
    tp = sp.find(qn('w:titlePg'))
    if tp is not None:
        sp.remove(tp)
    return sp


def _section_break_paragraph(sectPr):
    p = OxmlElement('w:p'); pPr = OxmlElement('w:pPr')
    sz = OxmlElement('w:rPr'); s = OxmlElement('w:sz'); s.set(qn('w:val'), '2'); sz.append(s)
    spacing = OxmlElement('w:spacing'); spacing.set(qn('w:before'), '0'); spacing.set(qn('w:after'), '0'); spacing.set(qn('w:line'), '20'); spacing.set(qn('w:lineRule'), 'exact')
    pPr.append(spacing); pPr.append(sz); pPr.append(sectPr); p.append(pPr)
    return p


def _is_heading(p_el):
    pPr = p_el.find(qn('w:pPr'))
    if pPr is None: return False
    ps = pPr.find(qn('w:pStyle'))
    return ps is not None and ps.get(qn('w:val'), '').lower().startswith(('heading', 'title'))


def _cell_text_len(cell):
    return max((len(p.text) for p in cell.paragraphs), default=0)


def fit_tables_to_content(doc, font_size_pt=None, landscape_min_cols=8, landscape_min_chars=250,
                          cap_chars=140, min_col_cm=1.6, header_fill='E7E6E6'):
    """Size every table's columns to its content, shrink the table font, shade and
    repeat the header row, and move wide tables into their own landscape section
    (the section starts at the preceding heading when one sits within two blocks).
    Call after normalize_tables(); it overrides the widths that pass set."""
    body = doc.element.body
    final_sectPr = body.find(qn('w:sectPr'))
    portrait_usable = _sectPr_usable_twips(final_sectPr)
    land_sectPr_model = _make_sectPr(final_sectPr, landscape=True)
    landscape_usable = _sectPr_usable_twips(land_sectPr_model)
    report = []

    for t in doc.tables:
        ncols = len(t.columns)
        if ncols == 0: continue
        # content weights per column
        lens = []
        for i in range(ncols):
            col_max = 0
            for r in t.rows:
                if i < len(r.cells):
                    col_max = max(col_max, _cell_text_len(r.cells[i]))
            lens.append(col_max)
        capped = [max(4, min(l, cap_chars)) for l in lens]
        wide = ncols >= landscape_min_cols or sum(capped) >= landscape_min_chars
        usable = landscape_usable if wide else portrait_usable

        # widths: proportional to capped length with a floor, renormalised
        min_w = int(min_col_cm * _TWIPS_PER_CM)
        raw = [c / sum(capped) * usable for c in capped]
        widths = [max(min_w, int(x)) for x in raw]
        excess = sum(widths) - usable
        if excess > 0:
            flex = [i for i, w in enumerate(widths) if w > min_w]
            flex_total = sum(widths[i] - min_w for i in flex) or 1
            for i in flex:
                widths[i] -= int(excess * (widths[i] - min_w) / flex_total)
        widths[-1] += usable - sum(widths)

        _set_fixed_layout(t, usable)
        grid = t._tbl.find(qn('w:tblGrid'))
        if grid is not None:
            for c in grid.findall(qn('w:gridCol')): grid.remove(c)
            for w in widths:
                gc = OxmlElement('w:gridCol'); gc.set(qn('w:w'), str(w)); grid.append(gc)
        for ri, row in enumerate(t.rows):
            trPr = row._tr.get_or_add_trPr()
            if ri == 0 and trPr.find(qn('w:tblHeader')) is None:
                trPr.append(OxmlElement('w:tblHeader'))
            for i, cell in enumerate(row.cells):
                tcPr = cell._tc.get_or_add_tcPr()
                tcW = tcPr.find(qn('w:tcW'))
                if tcW is None:
                    tcW = OxmlElement('w:tcW'); tcPr.append(tcW)
                tcW.set(qn('w:w'), str(widths[min(i, ncols - 1)])); tcW.set(qn('w:type'), 'dxa')
                if ri == 0 and header_fill:
                    old = tcPr.find(qn('w:shd'))
                    if old is not None: tcPr.remove(old)
                    shd = OxmlElement('w:shd'); shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), header_fill)
                    tcPr.append(shd)
                for p in cell.paragraphs:
                    if ri == 0:
                        p.paragraph_format.keep_with_next = True
                    if font_size_pt:
                        for run in p.runs:
                            run.font.size = Pt(font_size_pt)
                        if not p.runs:
                            p.style = p.style  # no-op, keeps paragraph
        # landscape wrapping
        if wide:
            tbl = t._tbl
            start = tbl
            prev = tbl.getprevious()
            if prev is not None and prev.tag == qn('w:p'):
                if _is_heading(prev):
                    start = prev
                else:
                    prev2 = prev.getprevious()
                    if prev2 is not None and prev2.tag == qn('w:p') and _is_heading(prev2):
                        start = prev2
            start.addprevious(_section_break_paragraph(_make_sectPr(final_sectPr, landscape=False)))
            tbl.addnext(_section_break_paragraph(_make_sectPr(final_sectPr, landscape=True)))
        # keep the paragraph before the table with it
        prev = t._tbl.getprevious()
        if prev is not None and prev.tag == qn('w:p'):
            pPr = prev.find(qn('w:pPr'))
            if pPr is None:
                pPr = OxmlElement('w:pPr'); prev.insert(0, pPr)
            if pPr.find(qn('w:keepNext')) is None:
                pPr.append(OxmlElement('w:keepNext'))
        report.append((ncols, len(t.rows), 'landscape' if wide else 'portrait', [round(w / _TWIPS_PER_CM, 1) for w in widths]))
    if any(r[2] == 'landscape' for r in report):
        # the document's closing section must not restart page numbering or reapply a first-page variant
        pg = final_sectPr.find(qn('w:pgNumType'))
        if pg is not None and qn('w:start') in pg.attrib:
            del pg.attrib[qn('w:start')]
        tp = final_sectPr.find(qn('w:titlePg'))
        if tp is not None:
            final_sectPr.remove(tp)
    return report


def set_page_size(doc, size='A4', margins_cm=(2.5, 2.5, 2.2, 2.2)):
    """Set every section's page size (A4 or Letter) and margins (top, bottom, left, right) in cm.
    Keeps landscape orientation where a section already has it."""
    sizes = {'A4': (11906, 16838), 'LETTER': (12240, 15840)}
    w, h = sizes[size.upper()]
    top, bottom, left, right = [int(x * _TWIPS_PER_CM) for x in margins_cm]
    for sectPr in doc.element.body.iter(qn('w:sectPr')):
        pgSz = sectPr.find(qn('w:pgSz'))
        if pgSz is None:
            pgSz = OxmlElement('w:pgSz'); sectPr.insert(0, pgSz)
        land = pgSz.get(qn('w:orient')) == 'landscape'
        pgSz.set(qn('w:w'), str(h if land else w)); pgSz.set(qn('w:h'), str(w if land else h))
        pgMar = sectPr.find(qn('w:pgMar'))
        if pgMar is None:
            pgMar = OxmlElement('w:pgMar'); sectPr.append(pgMar)
        pgMar.set(qn('w:top'), str(top)); pgMar.set(qn('w:bottom'), str(bottom))
        pgMar.set(qn('w:left'), str(left)); pgMar.set(qn('w:right'), str(right))
        for k in ('header', 'footer'):
            if pgMar.get(qn('w:' + k)) is None: pgMar.set(qn('w:' + k), '709')
        if pgMar.get(qn('w:gutter')) is None: pgMar.set(qn('w:gutter'), '0')


def set_running_header(doc, text=None, page_numbers=False, font_size_pt=8):
    """Replace every header's text with `text` (or clear it) and, if asked, put a
    centred "Page X of Y" field in every footer. Covers first-page and even-page parts."""
    def _field(paragraph, instr):
        r = paragraph.add_run()
        b = OxmlElement('w:fldChar'); b.set(qn('w:fldCharType'), 'begin'); r._r.append(b)
        it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve'); it.text = instr; r._r.append(it)
        e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); r._r.append(e)
        r.font.size = Pt(font_size_pt)
    for section in doc.sections:
        for part in (section.header, section.first_page_header, section.even_page_header):
            for p in list(part.paragraphs)[1:]:
                p._p.getparent().remove(p._p)
            p = part.paragraphs[0] if part.paragraphs else part.add_paragraph()
            for r in list(p.runs): r._r.getparent().remove(r._r)
            if text:
                run = p.add_run(text); run.font.size = Pt(font_size_pt); run.italic = True
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        if page_numbers:
            for part in (section.footer, section.first_page_footer, section.even_page_footer):
                for p in list(part.paragraphs)[1:]:
                    p._p.getparent().remove(p._p)
                p = part.paragraphs[0] if part.paragraphs else part.add_paragraph()
                for r in list(p.runs): r._r.getparent().remove(r._r)
                run = p.add_run('Page '); run.font.size = Pt(font_size_pt)
                _field(p, ' PAGE ')
                run = p.add_run(' of '); run.font.size = Pt(font_size_pt)
                _field(p, ' NUMPAGES ')
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
