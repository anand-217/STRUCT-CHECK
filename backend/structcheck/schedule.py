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

def detect_schedules(drawing, profile):
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
