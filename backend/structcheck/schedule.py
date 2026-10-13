"""Schedule recognition from loose TEXT/MTEXT (and rendered table blocks).
Header row -> column map -> body rows. Keyword maps come from the project profile so the engineer can remap."""
from __future__ import annotations
import re, statistics
from dataclasses import dataclass, field
from .geom import union_bbox

@dataclass
class ScheduleRow:
    index: int
    cells: dict               # field -> text
    extra: dict               # unmapped header text -> cell text
    handles: list
    bbox: tuple
    y: float
    id_text: str = ""         # id cell as drawn, e.g. "2, 8, 19."  (one drawn row may cover several beams)
    group: int = 0

@dataclass
class Schedule:
    type: str                 # beam | slab | column
    layout: str
    header: dict              # field -> header text
    rows: list
    bbox: tuple
    title: str = ""
    title_handle: str = ""
    header_handles: list = field(default_factory=list)
    missing_fields: list = field(default_factory=list)   # known fields with no column in this schedule
    hdr_boundary: float = None                           # texts above this y are header text (None = derive from rows)

def _norm(s):
    return re.sub(r"[^A-Z0-9 ]", " ", s.upper()).split()

def _match_field(cell_text, colmap):
    t = " ".join(_norm(cell_text))
    best, blen = None, -1
    for fld, kws in colmap.items():
        for kw in kws:
            k = " ".join(_norm(kw))
            if t == k or t.startswith(k + " "):
                score = len(k) + (100 if t == k else 0)
                if score > blen:
                    best, blen = fld, score
    return best

def _rows(texts, tol):
    texts = sorted(texts, key=lambda t: -t.y)
    rows, cur = [], []
    for t in texts:
        if cur and abs(t.y - cur[0].y) > tol:
            rows.append(sorted(cur, key=lambda a: a.x)); cur = []
        cur.append(t)
    if cur:
        rows.append(sorted(cur, key=lambda a: a.x))
    return rows

def _legacy_detect(drawing, profile):
    maps = {"beam": profile.beam_columns, "slab": profile.slab_columns, "column": profile.column_columns}
    required = {"beam": profile.beam_required_fields, "slab": profile.slab_required_fields, "column": profile.column_required_fields}
    out, notes = [], []
    for layout in drawing.layouts:
        pool = [t for t in drawing.texts if t.layout == layout and t.kind in ("TEXT", "MTEXT", "ATTRIB") and t.nlines == 1 and t.text]
        if not pool:
            continue
        for reg in profile.schedule_regions:
            if reg.get("layout", layout) == layout:
                bb = reg["bbox"]
                sub = [t for t in pool if bb[0] <= t.x <= bb[2] and bb[1] <= t.y <= bb[3]]
                out += _parse_pool(sub, reg["type"], maps, required, profile, drawing, layout, pool)
        if profile.schedule_regions and any(r.get("layout", layout) == layout for r in profile.schedule_regions):
            continue
        out += _parse_pool(pool, None, maps, required, profile, drawing, layout, pool)
    return out

def _parse_pool(pool, forced_type, maps, required, profile, drawing, layout, all_pool):
    if not pool:
        return []
    med_h = statistics.median(t.eff_height for t in pool) or 1.0
    tol = med_h * profile.schedule_row_tol_factor
    rows = _rows(pool, tol)
    used, result = set(), []
    for ri, row in enumerate(rows):
        if any(id(t) in used for t in row):
            continue
        best = None
        for typ, cmap in maps.items():
            if forced_type and typ != forced_type:
                continue
            hits = {}
            for t in row:
                f = _match_field(t.text, cmap)
                if f and f not in hits:
                    hits[f] = t
            if "id" not in hits or len(hits) < 3:
                continue
            # keep only row texts inside the span of the matched header cells: other drawing text that happens to
            # share the same y (plan labels, notes) must not become header columns
            lo = min(t.x for t in hits.values()) - 2 * med_h
            hi = max(t.x for t in hits.values()) + 14 * med_h
            hrow = [t for t in row if lo <= t.x <= hi]
            title = _find_title(typ, hrow, all_pool, med_h)
            score = len(hits) + (3 if title else 0)
            if not best or score > best[0]:
                best = (score, typ, hits, title, hrow)
        if not best:
            continue
        _, typ, hits, title, hrow = best
        sch = _build(typ, hrow, hits, rows[ri + 1:], maps[typ], required[typ], med_h, layout, used, title)
        if sch and sch.rows:
            result.append(sch)
            for t in hrow:
                used.add(id(t))
    return result

def _find_title(typ, header_row, pool, h):
    key = {"beam": "BEAM", "slab": "SLAB", "column": "COL"}[typ]
    x0 = min(t.x for t in header_row) - 5 * h
    x1 = max(t.x for t in header_row) + 5 * h
    y = header_row[0].y
    cands = [t for t in pool if "SCHEDULE" in t.text.upper() and key in t.text.upper() and x0 <= t.x <= x1 and 0 < t.y - y <= 12 * h]
    return min(cands, key=lambda t: t.y - y) if cands else None


# ===================================================================== titled / multi-line header parser
ID_TOKEN = re.compile(r"[A-Z]{0,3}-?\d{1,4}[A-Z]{0,2}|[A-Z]{1,3}")
_TYPE_WORDS = (("BEAM", "beam"), ("SLAB", "slab"), ("COLUMN", "column"))


def parse_ids(text):
    """'2, 8, 19.' -> ['2','8','19'];  'S 1.' -> ['S1'];  '26. 27.' -> ['26','27'];  '1 TO 4' -> ['1'..'4'].
    Returns (tokens, all_valid)."""
    t = re.sub(r"%%[A-Za-z]", "", (text or "").upper()).strip()
    t = re.sub(r"\b([A-Z]{1,3}) (?=\d)", r"\1", t)
    m = re.fullmatch(r"(\d+)\s*(?:TO|TILL)\s*(\d+)\.?", t)
    if m and 0 < int(m.group(2)) - int(m.group(1)) <= 60:
        return [str(i) for i in range(int(m.group(1)), int(m.group(2)) + 1)], True
    t = re.sub(r"\.\s+", ",", t)
    t = re.sub(r"\s+AND\s+|&|;|/", ",", t)
    t = re.sub(r"[.,]+\s*$", "", t)
    parts = [p.strip() for p in re.split(r",", t) if p.strip()]
    toks, ok = [], bool(parts)
    for p in parts:
        p = p.replace(" ", "")
        if ID_TOKEN.fullmatch(p):
            toks.append(p)
        else:
            ok = False
    return toks, ok


def _has_digit_id(text):
    toks, ok = parse_ids(text)
    return ok and any(re.search(r"\d", x) for x in toks)


def _words(s):
    return set(re.sub(r"[^A-Z0-9]+", " ", s.upper()).split())


def _field_for(header, cmap):
    hw = _words(header)
    for fld, phrases in cmap.items():
        for ph in phrases:
            pw = _words(ph)
            if pw and pw <= hw:
                return fld
    return None


def _row_cluster(texts, tol):
    texts = sorted(texts, key=lambda t: -t.y)
    rows, cur = [], []
    for t in texts:
        if cur and abs(t.y - cur[0].y) > tol:
            rows.append(sorted(cur, key=lambda a: a.x)); cur = []
        cur.append(t)
    if cur:
        rows.append(sorted(cur, key=lambda a: a.x))
    return rows


_TYPE_RX = {"beam": r"BEAMS?", "slab": r"SLABS?", "column": r"COLUMNS?"}


def _title_type(u):
    """Type word attached to the word SCHEDULE ('COLUMN SCHEDULE AT FIRST SLAB LEVEL', 'SCHEDULE OF BEAMS ...')."""
    for typ, rx in _TYPE_RX.items():
        if re.search(rf"\b{rx}\s+SCHEDULE\b|\bSCHEDULE\s+(?:OF|FOR)?\s*{rx}\b", u):
            return typ
    hits = sorted((m.start(), typ) for typ, rx in _TYPE_RX.items() for m in [re.search(rf"\b{rx}\b", u)] if m)
    return hits[0][1] if hits else None


def _titles(pool):
    out = []
    for t in pool:
        u = t.text.upper()
        if "SCHEDULE" in u:
            typ = _title_type(u)
            if typ:
                out.append((typ, t))
    return out


def _region(title, all_titles, pool, profile, unit):
    h = title.eff_height
    xl = title.left - 1500 / unit
    xr = float("inf")
    yb = float("-inf")
    for _, o in all_titles:
        if o is title:
            continue
        if abs(o.y - title.y) < 2500 / unit and o.left > title.left + 1000 / unit:
            xr = min(xr, o.left - 800 / unit)
        if o.y < title.y - 1000 / unit and o.left < title.left + 6000 / unit and o.left + 20000 / unit > title.left:
            yb = max(yb, o.y + h * 0.4)
    reg = [t for t in pool if t is not title and t.y < title.y - 0.3 * h and t.y > yb and xl <= t.left <= xr]
    return reg


def _cut_x(reg, title, max_gap):
    ivs = sorted((t.left, t.left + t.width) for t in reg)
    cur = title.left + title.width
    limit = float("inf")
    for a, b in ivs:
        if a - cur > max_gap:
            limit = a; break
        cur = max(cur, b)
    return [t for t in reg if t.left < limit]


def _parse_titled(typ, title, all_titles, pool, profile, unit, layout):
    cmap = {"beam": profile.beam_columns, "slab": profile.slab_columns, "column": profile.column_columns}[typ]
    reg = _region(title, all_titles, pool, profile, unit)
    reg = _cut_x(reg, title, profile.schedule_max_gap_mm / unit)
    if not reg:
        return None
    med_h = statistics.median(t.eff_height for t in reg) or 1.0
    rows = _row_cluster(reg, med_h * profile.schedule_row_tol_factor)
    gaps = [rows[i][0].y - rows[i + 1][0].y for i in range(len(rows) - 1)]
    if gaps:
        pitch = statistics.median(gaps)
        cut = next((i + 1 for i, g in enumerate(gaps) if g > profile.schedule_max_row_gap_factor * max(pitch, med_h)), len(rows))
        rows = rows[:cut]
    # body start: first row whose LEFTMOST text is an id list containing a digit
    bs = next((i for i, r in enumerate(rows) if _has_digit_id(r[0].text)), None)
    if bs is None:
        return _parse_column_list(typ, title, rows, cmap, layout) if typ == "column" else None
    header_rows, body_rows = rows[:bs], rows[bs:]
    body = [t for r in body_rows for t in r]
    xs = sorted(t.x for t in body)
    gap = 2.0 * med_h
    clusters = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] <= gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    cols = [{"x0": c[0], "x1": c[-1], "mid": sum(c) / len(c), "texts": []} for c in clusters]

    def col_of(t):
        return min(range(len(cols)), key=lambda i: abs(t.x - cols[i]["mid"]))

    htexts = [t for r in header_rows for t in r]
    for t in htexts:     # header words sit over the column whose data is nearest (by alignment point or centre)
        i = min(range(len(cols)), key=lambda i: min(abs(t.x - cols[i]["mid"]), abs(t.cx - cols[i]["mid"])))
        cols[i]["texts"].append(t)
    header, fieldcol, extra_hdr = {}, {}, {}
    for i, c in enumerate(cols):
        htxt = " ".join(t.text for t in sorted(c["texts"], key=lambda t: (-round(t.y / (med_h * 0.7)), t.x))).strip()
        c["header"] = htxt
        f = _field_for(htxt, cmap) if htxt else None
        if f and f not in header:
            header[f] = htxt; fieldcol[i] = f
        else:
            extra_hdr[i] = htxt
    if "id" not in header:
        header["id"] = cols[0]["header"] or "id"; fieldcol[0] = "id"
    if "size" in header:               # 'B x D' column provides both width and depth
        header.setdefault("width", header["size"]); header.setdefault("depth", header["size"])
    # group rows
    groups = []
    for r in body_rows:
        cells, texts = {}, []
        for t in r:
            i = col_of(t)
            cells.setdefault(i, []).append(t.text)
            texts.append(t)
        id_i = next(i for i, f in fieldcol.items() if f == "id")
        idtxt = " ".join(cells.get(id_i, []))
        # a drawn row starts a new group only if it has an id AND other cells; an id-only line continues the previous list
        new = bool(idtxt) and len(cells) > 1 and (_has_digit_id(idtxt) or parse_ids(idtxt)[1])
        if new or not groups:
            groups.append({"cells": {i: list(v) for i, v in cells.items()}, "texts": list(texts), "y": r[0].y})
        else:
            g = groups[-1]
            for i, v in cells.items():
                g["cells"].setdefault(i, []).extend(v)
            g["texts"].extend(texts)
    out_rows, n = [], 0
    for gi, g in enumerate(groups, start=1):
        id_i = next(i for i, f in fieldcol.items() if f == "id")
        idtxt = " ".join(g["cells"].get(id_i, []))
        ids, ok = parse_ids(idtxt)
        base, extra = {}, {}
        for i, v in g["cells"].items():
            if i == id_i:
                continue
            txt = " ".join(v).strip()
            if i in fieldcol:
                base[fieldcol[i]] = txt
            else:
                extra[cols[i]["header"] or f"col{i}"] = txt
        if "size" in base:
            nums = re.findall(r"\d+(?:\.\d+)?", base["size"])
            if len(nums) >= 2:
                base.setdefault("width", nums[0]); base.setdefault("depth", nums[1])
        bb = (min(t.left for t in g["texts"]), min(t.y for t in g["texts"]), max(t.left + t.width for t in g["texts"]),
              max(t.y + t.eff_height for t in g["texts"]))
        for tok in (ids or [idtxt]):
            n += 1
            c = dict(base); c["id"] = tok
            out_rows.append(ScheduleRow(n, c, extra, [t.handle for t in g["texts"]], bb, g["y"], idtxt, gi))
    if not out_rows:
        return None
    alltx = [title] + htexts + body
    bbox = (min(t.left for t in alltx) - med_h, min(t.y for t in alltx) - med_h,
            max(t.left + t.width for t in alltx) + med_h, max(t.y + t.eff_height for t in alltx) + med_h)
    missing = [f for f in cmap if f not in header]
    sch = Schedule(typ, layout, header, out_rows, bbox, title.text, title.handle, [t.handle for t in htexts], missing)
    sch.hdr_boundary = max(r.y for r in out_rows) + 0.5 * med_h
    return sch


_SIZE = re.compile(r"\d+\s*[xX*]\s*\d+")


def _parse_column_list(typ, title, rows, cmap, layout):
    """Column schedules laid out as 'COLUMN NOS.  FC16, FC9.' + size / steel / ties further down (one block)."""
    hdr = next((r for r in rows if re.fullmatch(r"COLUMN\s+NOS?\.?", r[0].text.upper().strip())), None)
    if not hdr:
        return None
    ids, handles = [], [title.handle]
    for t in hdr[1:]:
        toks, ok = parse_ids(t.text)
        if ok:
            ids += toks
        handles.append(t.handle)
    if not ids:
        return None
    alltx = [t for r in rows for t in r]
    size_t = next((t for t in alltx if _SIZE.fullmatch(t.text.strip())), None)
    main_t = next((t for t in alltx if re.match(r"\d+\s*-\s*\d+\s*mm", t.text.strip(), re.I)), None)
    tie_t = [t for t in sorted(alltx, key=lambda t: -t.y) if "@" in t.text or "C/C" in t.text.upper()]
    lvl_t = [t for t in alltx if re.search(r"LEVEL|^TO$", t.text.upper().strip()) and t.left < hdr[0].left + 3000]
    key = [title] + list(hdr) + [t for t in [size_t, main_t] if t] + tie_t + lvl_t
    pad = 2 * title.eff_height
    kb = (min(t.left for t in key) - pad, min(t.y for t in key) - pad, max(t.left + t.width for t in key) + pad, max(t.y + t.eff_height for t in key) + pad)
    inside = [t for t in alltx if kb[0] <= t.left and t.left + t.width <= kb[2] and kb[1] <= t.y <= kb[3]]
    size = size_t.text if size_t else ""
    main = main_t.text if main_t else ""
    ties = " ".join(t.text.strip() for t in tie_t)
    base = {"size": size, "main": main, "ties": ties}
    nums = re.findall(r"\d+", size)
    if len(nums) >= 2:
        base["width"], base["depth"] = nums[0], nums[1]
    bb = (min(t.left for t in inside + [title]), min(t.y for t in inside + [title]),
          max(t.left + t.width for t in inside + [title]), max(t.y + t.eff_height for t in inside + [title]))
    out = [ScheduleRow(i + 1, dict(base, id=tok), {}, handles, bb, hdr[0].y, ", ".join(ids), 1) for i, tok in enumerate(ids)]
    header = {"id": "COLUMN NOS.", "size": "size", "main": "main", "ties": "ties"}
    sch = Schedule("column", layout, header, out, bb, title.text, title.handle, [], [f for f in cmap if f not in header])
    sch.hdr_boundary = hdr[0].y - 0.5 * title.eff_height      # 'COLUMN NOS.' and its ids share the first row: header text
    return sch


def detect_schedules(drawing, profile):
    found = []
    for layout in drawing.layouts:
        pool = [t for t in drawing.texts if t.layout == layout and t.kind in ("TEXT", "MTEXT", "ATTRIB") and t.nlines == 1 and t.text]
        titles = _titles(pool)
        for typ, ttl in titles:
            try:
                sch = _parse_titled(typ, ttl, titles, pool, profile, drawing.unit_mm, layout)
            except Exception as ex:    # never let one odd schedule break the run
                drawing.limitations.append(f"Schedule under '{ttl.text}' could not be parsed ({type(ex).__name__}: {ex})")
                sch = None
            if sch:
                found.append(sch)
            else:
                drawing.limitations.append(f"Title '{ttl.text}' found but no table rows were recognised under it - map it in the profile")
    have = {(s.layout, s.type) for s in found}
    for s in _legacy_detect(drawing, profile):      # untitled / single-line-header schedules
        if (s.layout, s.type) not in have:
            found.append(s)
    return found

def _build(typ, header_row, hits, below, cmap, req, h, layout, used, title):
    fld_of = {id(t): f for f, t in hits.items()}
    cols = []   # (x, field_or_None, header_text)
    for t in header_row:
        cols.append((t.x, fld_of.get(id(t)), t.text))
    xs = [c[0] for c in cols]
    bounds = [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)]
    def col_index(x):
        for i, b in enumerate(bounds):
            if x < b:
                return i
        return len(xs) - 1
    xmin, xmax = min(xs) - 2 * h, max(xs) + 25 * h
    rows, gaps, prev_y = [], [], header_row[0].y
    for r in below:
        r = [t for t in r if xmin <= t.x <= xmax]
        if not r:
            continue          # other drawing text sharing this y-band; not part of the table
        gap = prev_y - r[0].y
        if gaps and gap > 2.2 * statistics.median(gaps):
            break
        if not gaps and gap > 6 * h:
            break
        gaps.append(gap); prev_y = r[0].y
        cells, extra, handles = {}, {}, []
        for t in r:
            i = col_index(t.x)
            f, htxt = cols[i][1], cols[i][2]
            tgt = cells if f else extra
            k = f if f else htxt
            tgt[k] = (tgt.get(k, "") + " " + t.text).strip()
            handles.append(t.handle); used.add(id(t))
        bb = (min(t.x for t in r), min(t.y for t in r), max(t.bbox[2] for t in r), max(t.bbox[3] for t in r))
        rows.append(ScheduleRow(len(rows) + 1, cells, extra, handles, bb, r[0].y))
    if not rows:
        return None
    header = {f: txt for _, f, txt in cols if f}
    bbox = union_bbox([(min(xs) - h, min(r.bbox[1] for r in rows) - h, xmax, header_row[0].y + 2 * h)])
    missing = [f for f in cmap if f not in header]
    return Schedule(typ, layout, header, rows, bbox, title.text if title else "", title.handle if title else "",
                    [t.handle for t in header_row], missing)
