"""Rule 7 - duplicate / conflicting column numbers."""
from __future__ import annotations
import math, re
from collections import defaultdict
from ..findings import Severity
from ..context import RuleResult
from ..geom import point_in_poly, bbox_of, union_bbox
from ..ids import strict_key, loose_key, match_key
from .beams import _data_sig


def _column_geoms(ctx):
    lo, hi = ctx.du(150), ctx.du(ctx.p.column_max_dim_mm)
    out = []
    for pl in ctx.d.polys:
        if not pl.closed or len(pl.pts) not in (4, 5) or ctx.layer_excluded(pl.layer):
            continue
        bb = bbox_of(pl.pts)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        if lo <= w <= hi and lo <= h <= hi and max(w, h) / max(min(w, h), 1e-9) < 3:
            out.append({"layout": pl.layout, "pts": pl.pts, "handle": pl.handle, "bbox": bb})
    for ins in ctx.d.inserts:
        if re.search(r"COL", ins.name, re.I):
            out.append({"layout": ins.layout, "pts": None, "handle": ins.handle, "bbox": (ins.x, ins.y, ins.x, ins.y), "centre": (ins.x, ins.y)})
    return out


def run(ctx) -> RuleResult:
    R = RuleResult(7, "Duplicate / conflicting column numbers")
    p = ctx.p
    labels = ctx.labels(p.column_id_regex)
    scheds = ctx.sched("column")
    mode = p.column_id_mode
    if not labels and not scheds:
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(7, "Column numbers", "No column labels or column schedule recognised",
                                          "Neither plan labels matching the column pattern nor a column schedule were found.",
                                          "Check column_id_regex in the profile."))
        return R
    if mode == "unknown":
        R.notes.append("column_id_mode is 'unknown': repeated labels are reported as REVIEW, not ERROR.")
    # --- A: same id at several locations within one layout --------------------------------
    per_layout = defaultdict(lambda: defaultdict(list))
    for l in labels:
        per_layout[l.layout][match_key(l.text, p)].append(l)
    if mode != "types":
        for lay, groups in per_layout.items():
            for k, labs in groups.items():
                if len(labs) < 2:
                    continue
                sev = Severity.ERROR if mode == "unique" else Severity.REVIEW
                R.findings.append(ctx.finding(
                    rule=7, category="Column numbers", severity=sev, sub_check="A same id at several locations",
                    description=f"Column number {labs[0].text} used at {len(labs)} locations" + ("" if mode == "unique" else " (numbering convention unknown)"),
                    explanation="Unique-location numbering expected." if mode == "unique" else
                                "May be a legitimate column TYPE mark. Set column_id_mode to 'types' or 'unique' to resolve.",
                    identifier=labs[0].text, layout=lay, floor_level=ctx.floor_for(lay),
                    entity_handles=[l.handle for l in labs], bbox=union_bbox([l.bbox for l in labs]),
                    confidence=0.85 if mode == "unique" else 0.4,
                    reason="Same identifier at multiple distinct positions in one layout",
                    recommended_action="Confirm the numbering convention; renumber duplicates if identifiers must be unique."))
    # --- B / C : same column with several labels, or labels too close ----------------
    geoms = _column_geoms(ctx)
    taken = set()
    for g in geoms:
        if "centre" in g:
            cx, cy = g["centre"]
        else:
            cx, cy = (g["bbox"][0] + g["bbox"][2]) / 2, (g["bbox"][1] + g["bbox"][3]) / 2
        near = []
        for l in labels:
            if l.layout != g["layout"]:
                continue
            c = ctx.centre(l)
            inside = g["pts"] is not None and point_in_poly(c, g["pts"])
            if inside or math.hypot(c[0] - cx, c[1] - cy) <= ctx.du(450):
                near.append(l)
        if len(near) >= 2:
            ids = {strict_key(l.text) for l in near}
            R.findings.append(ctx.finding(
                rule=7, category="Column numbers", severity=Severity.WARNING, sub_check="B several labels at one column",
                description=f"Column location has {len(near)} number annotations ({', '.join(l.text for l in near)})",
                explanation="Different identifiers at one column." if len(ids) > 1 else "Same identifier annotated twice at one column.",
                identifier=", ".join(l.text for l in near), layout=g["layout"], floor_level=ctx.floor_for(g["layout"]),
                entity_handles=[g["handle"]] + [l.handle for l in near], bbox=union_bbox([l.bbox for l in near] + [g["bbox"]]),
                confidence=0.75, reason="Multiple column-number labels associated with the same column geometry",
                recommended_action="Keep one number per column."))
            for l in near:
                taken.add(id(l))
    lim = ctx.du(p.column_label_conflict_dist_mm)
    for i, a in enumerate(labels):
        for b in labels[i + 1:]:
            if a.layout != b.layout or id(a) in taken and id(b) in taken:
                continue
            if strict_key(a.text) == strict_key(b.text):
                continue
            ca, cb = ctx.centre(a), ctx.centre(b)
            if math.dist(ca, cb) <= lim:
                R.findings.append(ctx.finding(
                    rule=7, category="Column numbers", severity=Severity.WARNING, sub_check="C labels overlap/conflict",
                    description=f"Column labels {a.text} and {b.text} are {ctx.mm(math.dist(ca, cb)):.0f} mm apart",
                    explanation="Two different column numbers are placed so close that they overlap or conflict.",
                    identifier=f"{a.text}, {b.text}", layout=a.layout, entity_handles=[a.handle, b.handle],
                    bbox=union_bbox([a.bbox, b.bbox]), confidence=0.7, reason=f"Distance below {p.column_label_conflict_dist_mm:g} mm",
                    recommended_action="Separate or correct the labels."))
    # --- F: equivalent identifiers -----------------------------------------------------
    allids = defaultdict(set)
    for l in labels:
        allids[loose_key(l.text)].add(strict_key(l.text))
    for s in scheds:
        for r in s.rows:
            if r.cells.get("id"):
                allids[loose_key(r.cells["id"])].add(strict_key(r.cells["id"]))
    if not (p.hyphen_equivalent or p.leading_zero_equivalent):
        for lk, forms in allids.items():
            if len(forms) > 1:
                hs = [l.handle for l in labels if loose_key(l.text) == lk]
                R.findings.append(ctx.finding(
                    rule=7, category="Column numbers", severity=Severity.REVIEW, sub_check="F equivalent identifiers",
                    description=f"Identifiers {' / '.join(sorted(forms))} may be the same column written differently",
                    explanation="Not merged automatically.", entity_handles=hs, confidence=0.5, reason="Differ only in hyphen/leading zeros",
                    recommended_action="Standardise identifier format."))
    # --- schedule checks ----------------------------------------------------------------
    if not scheds:
        R.status = "PARTIAL"
        R.notes.append("No column schedule detected; checks D, E, G, H not performed.")
        R.findings.append(ctx.not_checked(7, "Column numbers", "Column schedule checks not performed",
                                          "No column schedule recognised (checks D, E, G, H).", "Map the column schedule in the profile."))
        return R
    rows = defaultdict(list)
    for s in scheds:
        for r in s.rows:
            if r.cells.get("id"):
                rows[match_key(r.cells["id"], p)].append((s, r))
    for k, lst in rows.items():                      # D / E
        if len(lst) < 2:
            continue
        sigs = [_data_sig(r) for _, r in lst]
        conflict = any(sg != sigs[0] for sg in sigs[1:])
        diffs = [f"{f}: " + " | ".join(sg.get(f, "") for sg in sigs) for f in sorted({f for sg in sigs for f in sg})
                 if len({sg.get(f, "") for sg in sigs}) > 1]
        R.findings.append(ctx.finding(
            rule=7, category="Column numbers", severity=Severity.ERROR, sub_check="E conflicting data" if conflict else "D duplicate in schedule",
            description=f"Column {lst[0][1].cells['id']} appears {len(lst)} times in the column schedule" + (" with conflicting data" if conflict else ""),
            explanation=("Conflicts - " + "; ".join(diffs)) if conflict else "Identical repeated rows.",
            identifier=lst[0][1].cells["id"], layout=lst[0][0].layout, schedule_ref="; ".join(f"row {r.index}" for _, r in lst),
            entity_handles=[h for _, r in lst for h in r.handles], bbox=union_bbox([r.bbox for _, r in lst]),
            confidence=0.95, reason="Schedule identifiers are expected to be unique",
            recommended_action="Remove the duplicate or give the different column its own number."))
    if p.column_schedule_check:
        plan_keys = {match_key(l.text, p) for l in labels}
        grouped = defaultdict(list)
        for l in labels:
            grouped[match_key(l.text, p)].append(l)
        for k, labs in grouped.items():               # G
            if k not in rows and not any(loose_key(labs[0].text) == loose_key(r.cells["id"]) for lst in rows.values() for _, r in lst):
                R.findings.append(ctx.finding(
                    rule=7, category="Column numbers", severity=Severity.WARNING, sub_check="G layout not in schedule",
                    description=f"Column {labs[0].text} appears in the layout but not in the column schedule",
                    identifier=labs[0].text, layout=labs[0].layout, entity_handles=[l.handle for l in labs],
                    bbox=union_bbox([l.bbox for l in labs]), confidence=0.8, reason="No schedule row for this label",
                    recommended_action="Add to schedule or correct label."))
        loose_plan = {loose_key(l.text) for l in labels}
        for k, lst in rows.items():                   # H
            s, r = lst[0]
            if k not in plan_keys and loose_key(r.cells["id"]) not in loose_plan:
                R.findings.append(ctx.finding(
                    rule=7, category="Column numbers", severity=Severity.WARNING, sub_check="H schedule not in layout",
                    description=f"Scheduled column {r.cells['id']} not found in the column layout",
                    identifier=r.cells["id"], layout=s.layout, schedule_ref=f"row {r.index}", entity_handles=r.handles, bbox=r.bbox,
                    confidence=0.7, reason="No layout label for this schedule entry",
                    recommended_action="Confirm the column exists on this level."))
    return R
