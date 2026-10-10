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
from docx.shared import Pt, RGBColor
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
    for side, val in (('top', top), ('left', left), ('bottom', bottom), ('right', right)):  # schema order
        e = OxmlElement('w:' + side)
        e.set(qn('w:w'), str(val))
        e.set(qn('w:type'), 'dxa')
        mar.append(e)
    tblPr.append(mar)
    _order_tblpr(tblPr)


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
    _order_tblpr(tblPr)


def _order_tblpr(tblPr):
    """Put the table properties in the order the WordprocessingML schema requires
    (tblLook last). Appending tblW, tblLayout or tblCellMar after an existing tblLook
    makes Word report unreadable content."""
    order = ['tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize', 'tblStyleColBandSize',
             'tblW', 'jc', 'tblCellSpacing', 'tblInd', 'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook']
    kids = sorted(list(tblPr), key=lambda e: order.index(e.tag.split('}')[1]) if e.tag.split('}')[1] in order else 99)
    for e in kids:
        tblPr.remove(e)
    for e in kids:
        tblPr.append(e)


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
from docx.text.paragraph import Paragraph as _Paragraph

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


def _cell_longest_word(cell):
    """Length of the longest unbreakable run of characters in a cell (breaks at spaces and hyphens)."""
    best = 0
    for p in cell.paragraphs:
        for w in re.split(r'[ \t\n\-]+', p.text):
            best = max(best, len(w))
    return best


_NOTE_RE = re.compile(r'^(Sources?|Notes?|Reading|Fuentes?|Notas?)\b\s*[:.]', re.I)
_NUM_RE = re.compile(r'^[\-+]?[\d.,]*\d%?(\s*\(.*\))?$')
_NUM_BLANKS = {'', 'n.s.', 'n.c.', 'n.a.', '-'}


def _p_text(p_el):
    return ''.join(t.text or '' for t in p_el.iter(qn('w:t')))


def _is_caption(p_el, max_chars=300):
    """A short paragraph whose text runs are all bold: the usual table title."""
    text = _p_text(p_el).strip()
    if not text or len(text) > max_chars:
        return False
    runs = [r for r in p_el.iter(qn('w:r')) if ''.join(t.text or '' for t in r.iter(qn('w:t'))).strip()]
    if not runs:
        return False
    for r in runs:
        rPr = r.find(qn('w:rPr'))
        b = rPr.find(qn('w:b')) if rPr is not None else None
        if b is None or b.get(qn('w:val')) in ('0', 'false'):
            return False
    return True


def _ends_landscape_section(p_el):
    """True for a section-break paragraph that closes a landscape section."""
    if p_el is None or p_el.tag != qn('w:p'):
        return False
    pPr = p_el.find(qn('w:pPr'))
    sp = pPr.find(qn('w:sectPr')) if pPr is not None else None
    if sp is None:
        return False
    pgSz = sp.find(qn('w:pgSz'))
    return pgSz is not None and pgSz.get(qn('w:orient')) == 'landscape'


def _trailing_notes(tbl, max_notes=3):
    """Paragraphs right after a table that are its source, note or reading lines."""
    notes = []
    nxt = tbl.getnext()
    while nxt is not None and nxt.tag == qn('w:p') and len(notes) < max_notes and _NOTE_RE.match(_p_text(nxt).strip()):
        notes.append(nxt)
        nxt = nxt.getnext()
    return notes


_TBLPR_ORDER = ['tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize', 'tblStyleColBandSize',
                'tblW', 'jc', 'tblCellSpacing', 'tblInd', 'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook']


def _border(tag, sz, color, val='single'):
    e = OxmlElement(f'w:{tag}')
    e.set(qn('w:val'), val); e.set(qn('w:sz'), str(sz)); e.set(qn('w:space'), '0'); e.set(qn('w:color'), color)
    return e


def _rule_table(t, notes, line='7F7F7F', hair='D9D9D9'):
    """Report-style table: a firm rule above and below, a rule under the header, hairlines between rows,
    no vertical lines, a little more room in the cells, and space around the table and its title."""
    tblPr = t._tbl.tblPr
    for tag in ('w:tblBorders', 'w:tblCellMar'):
        e = tblPr.find(qn(tag))
        if e is not None: tblPr.remove(e)
    b = OxmlElement('w:tblBorders')
    b.append(_border('top', 8, line)); b.append(_border('left', 0, 'auto', 'nil')); b.append(_border('bottom', 8, line))
    b.append(_border('right', 0, 'auto', 'nil')); b.append(_border('insideH', 4, hair)); b.append(_border('insideV', 0, 'auto', 'nil'))
    tblPr.append(b)
    m = OxmlElement('w:tblCellMar')
    for side, w in (('top', 36), ('left', 90), ('bottom', 36), ('right', 90)):
        e = OxmlElement(f'w:{side}'); e.set(qn('w:w'), str(w)); e.set(qn('w:type'), 'dxa'); m.append(e)
    tblPr.append(m)
    kids = sorted(list(tblPr), key=lambda e: _TBLPR_ORDER.index(e.tag.split('}')[1]) if e.tag.split('}')[1] in _TBLPR_ORDER else 99)
    for e in kids: tblPr.remove(e)
    for e in kids: tblPr.append(e)
    for cell in t.rows[0].cells:
        tcPr = cell._tc.get_or_add_tcPr()
        old = tcPr.find(qn('w:tcBorders'))
        if old is not None: tcPr.remove(old)
        tb = OxmlElement('w:tcBorders'); tb.append(_border('bottom', 8, line))
        tcW = tcPr.find(qn('w:tcW'))
        if tcW is not None: tcW.addnext(tb)
        else: tcPr.insert(0, tb)
    for row in t.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(0)
    prev = t._tbl.getprevious()
    if prev is not None and prev.tag == qn('w:p') and _is_caption(prev):
        cp = _Paragraph(prev, None)
        cp.paragraph_format.space_before = Pt(0 if cp.paragraph_format.page_break_before else 14)
        cp.paragraph_format.space_after = Pt(5)
        cp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if not notes:
        nxt = t._tbl.getnext()
        if nxt is not None and nxt.tag == qn('w:p') and nxt.find(qn('w:pPr') + '/' + qn('w:sectPr')) is None and not _is_heading(nxt):
            _Paragraph(nxt, None).paragraph_format.space_before = Pt(16)


def fit_tables_to_content(doc, font_size_pt=None, landscape_min_cols=8, landscape_min_chars=250,
                          cap_chars=140, min_col_cm=1.6, header_fill='E7E6E6', ruled=False, keep_whole=False, flow_captions=()):
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
        # per-column floor: wide enough for the longest word, so no word is split mid-word
        min_w = int(min_col_cm * _TWIPS_PER_CM)
        char_cm = 0.0215 * (font_size_pt or 10)
        words = []
        for i in range(ncols):
            words.append(max((_cell_longest_word(r.cells[i]) for r in t.rows if i < len(r.cells)), default=0))
        floors = [max(min_w, int((w * char_cm + 0.45) * _TWIPS_PER_CM)) for w in words]
        # a column of phrases needs room for two or three words a line
        phrase = [max(f, int(2.6 * _TWIPS_PER_CM)) if lens[i] > 30 else f for i, f in enumerate(floors)]
        if sum(phrase) <= portrait_usable or sum(floors) > portrait_usable * 1.09:
            floors = phrase
        # the estimate is cautious: a table within 6 percent of the portrait width stays portrait
        wide = (ncols >= landscape_min_cols or sum(capped) >= landscape_min_chars
                or sum(floors) > portrait_usable * 1.09)
        usable = landscape_usable if wide else portrait_usable
        tbl_font = font_size_pt
        if sum(floors) > usable and font_size_pt and font_size_pt > 7:
            # too many columns for the page: one point smaller for this table
            tbl_font = font_size_pt - 1
            floors = [max(min_w, int((w * 0.0215 * tbl_font + 0.4) * _TWIPS_PER_CM)) for w in words]
        if sum(floors) > usable:
            k = usable / sum(floors)
            floors = [int(f * k) for f in floors]

        # widths: proportional to capped length with the floor, renormalised
        raw = [c / sum(capped) * usable for c in capped]
        widths = [max(floors[i], int(x)) for i, x in enumerate(raw)]
        excess = sum(widths) - usable
        if excess > 0:
            flex = [i for i, w in enumerate(widths) if w > floors[i]]
            flex_total = sum(widths[i] - floors[i] for i in flex) or 1
            for i in flex:
                widths[i] -= int(excess * (widths[i] - floors[i]) / flex_total)
        widest = max(range(ncols), key=lambda i: widths[i])
        widths[widest] += usable - sum(widths)

        # numeric columns read better right-aligned
        numeric_cols = set()
        for i in range(ncols):
            vals = [r.cells[i].text.strip() for r in list(t.rows)[1:] if i < len(r.cells)]
            nums = [v for v in vals if _NUM_RE.match(v)]
            if nums and all(_NUM_RE.match(v) or v.lower() in _NUM_BLANKS for v in vals):
                numeric_cols.add(i)

        # columns of marks or one-word answers (X, Yes, No) read better centred
        mark_cols = set()
        if ruled:
            for i in range(1, ncols):
                if i in numeric_cols: continue
                vals = [r.cells[i].text.strip() for r in list(t.rows)[1:] if i < len(r.cells)]
                short = [v for v in vals if len(v) <= 3]
                if vals and len(short) >= 0.8 * len(vals) and any(vals) and all(len(v) <= 14 for v in vals):
                    mark_cols.add(i)

        _set_fixed_layout(t, usable)
        grid = t._tbl.find(qn('w:tblGrid'))
        if grid is not None:
            for c in grid.findall(qn('w:gridCol')): grid.remove(c)
            for w in widths:
                gc = OxmlElement('w:gridCol'); gc.set(qn('w:w'), str(w)); grid.append(gc)
        for ri, row in enumerate(t.rows):
            trPr = row._tr.get_or_add_trPr()
            if trPr.find(qn('w:cantSplit')) is None:
                trPr.insert(0, OxmlElement('w:cantSplit'))
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
                        if header_fill:
                            # the light fill replaces the style's dark header, so its white text must go dark too
                            for run in p.runs:
                                run.font.color.rgb = RGBColor(0, 0, 0)
                    if i in numeric_cols:
                        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                    elif i in mark_cols:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    if tbl_font:
                        mark = p.text.strip() in ('\u25cf', '\u25cb', '\u25d0')
                        for run in p.runs:
                            run.font.size = Pt(tbl_font + 3 if mark else tbl_font)
                        if not p.runs:
                            p.style = p.style  # no-op, keeps paragraph
        # a short table of short cells stays whole on one page
        _prev = t._tbl.getprevious()
        _cap = _p_text(_prev).strip() if _prev is not None and _prev.tag == qn('w:p') else ''
        _flow = any(_cap.startswith(c) for c in flow_captions if c)
        if (keep_whole and not _flow) or (len(t.rows) <= 8 and sum(capped) < 420 and not wide):
            for row in list(t.rows)[:-1]:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.keep_with_next = True
        # the table's own source, note and reading lines: small type, kept close to the table
        notes = _trailing_notes(t._tbl)
        if ruled:
            _rule_table(t, notes)
        if notes:
            # a note never lands on a page without at least the table's last row
            for cell in t.rows[-1].cells:
                for p_ in cell.paragraphs:
                    p_.paragraph_format.keep_with_next = True
        for n_el in notes:
            n_par = _Paragraph(n_el, None)
            n_par.paragraph_format.space_before = Pt(5 if ruled and n_el is notes[0] else 3)
            n_par.paragraph_format.space_after = Pt((16 if ruled else 10) if n_el is notes[-1] else 2)
            n_par.alignment = WD_ALIGN_PARAGRAPH.LEFT
            if font_size_pt:
                for run in n_par.runs:
                    run.font.size = Pt(font_size_pt)
        # landscape wrapping: the section takes the title before the table and the notes after it
        if wide:
            tbl = t._tbl
            start = tbl
            prev = tbl.getprevious()
            if prev is not None and prev.tag == qn('w:p'):
                if _is_heading(prev) or _is_caption(prev):
                    start = prev
                prev2 = prev.getprevious()
                if prev2 is not None and prev2.tag == qn('w:p') and _is_heading(prev2):
                    start = prev2
            inside = [n for n in notes if len(_p_text(n)) <= 420] if all(len(_p_text(n)) <= 420 for n in notes) else []
            end = inside[-1] if inside else tbl
            before = start.getprevious()
            if _ends_landscape_section(before):
                # the previous block is already landscape: run on in the same section
                before.getparent().remove(before)
            else:
                start.addprevious(_section_break_paragraph(_make_sectPr(final_sectPr, landscape=False)))
            end.addnext(_section_break_paragraph(_make_sectPr(final_sectPr, landscape=True)))
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


def set_project_footer(doc, line1_left, line2_left, font_size_pt=8):
    """Two-line project footer on every footer part (default, first page, even pages):
    line 1 `line1_left` and, flush right, the document name (FILENAME field); line 2 `line2_left`
    and, flush right, "Page X of Y" (PAGE and NUMPAGES fields). The RRAM footer standard."""
    def _field(paragraph, instr):
        r = paragraph.add_run()
        b = OxmlElement('w:fldChar'); b.set(qn('w:fldCharType'), 'begin'); r._r.append(b)
        it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve'); it.text = instr; r._r.append(it)
        e = OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'), 'end'); r._r.append(e)
        r.font.size = Pt(font_size_pt)
    def _right_tab(paragraph, twips):
        pPr = paragraph._p.get_or_add_pPr()
        tabs = OxmlElement('w:tabs'); tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), 'right'); tab.set(qn('w:pos'), str(twips)); tabs.append(tab); pPr.append(tabs)
    for section in doc.sections:
        width = int((section.page_width - section.left_margin - section.right_margin) / 635)  # EMU to twips
        for part in (section.footer, section.first_page_footer, section.even_page_footer):
            for p in list(part.paragraphs):
                p._p.getparent().remove(p._p)
            for t in list(part._element.findall(qn('w:tbl'))):
                part._element.remove(t)
            p1 = part.add_paragraph(); _right_tab(p1, width)
            r = p1.add_run(line1_left + '\t'); r.font.size = Pt(font_size_pt)
            _field(p1, ' FILENAME ')
            p2 = part.add_paragraph(); _right_tab(p2, width)
            r = p2.add_run(line2_left + '\tPage '); r.font.size = Pt(font_size_pt)
            _field(p2, ' PAGE ')
            r = p2.add_run(' of '); r.font.size = Pt(font_size_pt)
            _field(p2, ' NUMPAGES ')
            for q in (p1, p2):
                q.alignment = WD_ALIGN_PARAGRAPH.LEFT
                q.paragraph_format.space_before = Pt(0); q.paragraph_format.space_after = Pt(0)


def keep_headings_with_next(doc, page_break_level1=False):
    """Keep every heading on the page of the text that follows it; optionally start
    each level-1 heading after the first on a new page."""
    seen_h1 = False
    for p in doc.element.body.iter(qn('w:p')):
        if not _is_heading(p):
            continue
        par = _Paragraph(p, None)
        par.paragraph_format.keep_with_next = True
        style = p.find(qn('w:pPr')).find(qn('w:pStyle')).get(qn('w:val'), '').lower()
        if page_break_level1 and style in ('heading1', 'heading 1'):
            if seen_h1:
                par.paragraph_format.page_break_before = True
            seen_h1 = True


def annex_page_numbering(doc, pattern=r'^(Annex [A-Z])\b', separator=' - '):
    """Give each annex its own page numbering: every level-1 heading matching `pattern` opens a new section whose
    pages count from 1 and whose footers print the annex label before the number ("Annex A - 1"). The body before
    the first annex keeps the plain number. Call after fit_tables_to_content(), which adds the landscape sections."""
    body = doc.element.body
    final_sectPr = body.find(qn('w:sectPr'))
    rx = re.compile(pattern)

    def h1_label(el):
        if el.tag != qn('w:p') or not _is_heading(el):
            return None
        style = el.find(qn('w:pPr')).find(qn('w:pStyle')).get(qn('w:val'), '').lower().replace(' ', '')
        m = rx.match(_p_text(el).strip()) if style == 'heading1' else None
        return m.group(1) if m else None

    # 1. a section break in front of every annex heading (it closes the section before it)
    for el in list(body):
        if h1_label(el):
            _Paragraph(el, None).paragraph_format.page_break_before = False
            el.addprevious(_section_break_paragraph(_make_sectPr(final_sectPr, landscape=False)))

    # 2. zone of each section, in document order
    zone, zones = None, []
    for el in body:
        lab = h1_label(el)
        if lab:
            zone = lab
        sp = el if el.tag == qn('w:sectPr') else (el.find(qn('w:pPr') + '/' + qn('w:sectPr')) if el.tag == qn('w:p') else None)
        if sp is not None:
            zones.append((sp, zone))

    # 3. one footer per annex, cloned from the document's default footer, with the label before the page field
    base = doc.sections[-1].footer._element
    rids, started = {}, set()
    for sp, zone in zones:
        pg = sp.find(qn('w:pgNumType'))
        if zone is None:
            continue
        if zone not in rids:
            part, rid = doc.part.add_footer_part()
            ftr = part.element
            for child in list(ftr): ftr.remove(child)
            for child in base: ftr.append(_copy.deepcopy(child))
            for p_el in ftr.iter(qn('w:p')):
                first_fld = next((r for r in p_el.findall(qn('w:r')) if r.find(qn('w:fldChar')) is not None), None)
                if first_fld is not None:
                    lab_run = _copy.deepcopy(first_fld)
                    for ch in list(lab_run):
                        if ch.tag != qn('w:rPr'): lab_run.remove(ch)
                    t = OxmlElement('w:t'); t.set(qn('xml:space'), 'preserve'); t.text = zone + separator; lab_run.append(t)
                    first_fld.addprevious(lab_run)
                    break
            rids[zone] = rid
        for ref in sp.findall(qn('w:footerReference')): sp.remove(ref)
        for i, typ in enumerate(('default', 'even', 'first')):
            ref = OxmlElement('w:footerReference'); ref.set(qn('w:type'), typ); ref.set(qn('r:id'), rids[zone]); sp.insert(i, ref)
        if pg is None:
            pg = OxmlElement('w:pgNumType')
            anchor = sp.find(qn('w:pgMar'))
            (anchor.addnext(pg) if anchor is not None else sp.append(pg))
        if zone not in started:
            pg.set(qn('w:start'), '1'); started.add(zone)
        elif qn('w:start') in pg.attrib:
            del pg.attrib[qn('w:start')]
    return sorted(rids)
