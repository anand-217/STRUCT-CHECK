"""Rule 4 - slab numbers: plan vs schedule."""
from __future__ import annotations
import re
from collections import defaultdict
from ..findings import Severity
from ..context import RuleResult
from ..geom import point_in_poly, poly_area, bbox_of, union_bbox
from ..ids import strict_key, loose_key, match_key, is_blank


def slab_panels(ctx):
    p, d = ctx.p, ctx.d
    pats = p.panel_layers
    auto = [] if pats else [l for l in d.layers if re.search(r"SLAB|PANEL", l, re.I)]
    use = pats or [re.escape(l) for l in auto]
    heuristic = not use
    amin, amax = p.min_panel_area_m2 * 1e6, p.max_panel_area_m2 * 1e6
    panels = []
    for pl in d.polys:
        if not pl.closed or len(pl.pts) < 3 or ctx.layer_excluded(pl.layer):
            continue
        if use and not any(re.search(r, pl.layer, re.I) for r in use):
            continue
        area_mm2 = poly_area(pl.pts) * ctx.unit ** 2
        if not (amin <= area_mm2 <= amax):
            continue
        c = (sum(x for x, _ in pl.pts) / len(pl.pts), sum(y for _, y in pl.pts) / len(pl.pts))
        if ctx.point_in_schedule(pl.layout, c):
            continue
        panels.append({"poly": pl, "area": area_mm2, "bbox": bbox_of(pl.pts)})
    return panels, heuristic


def run(ctx) -> RuleResult:
    R = RuleResult(4, "Slab numbers: plan vs slab schedule")
    scheds = ctx.sched("slab")
    if not scheds:
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(4, "Slab numbers", "Slab schedule not detected", "No slab schedule header was recognised."))
        return R
    rows = defaultdict(list)
    for s in scheds:
        for r in s.rows:
            if r.cells.get("id"):
                rows[match_key(r.cells["id"], ctx.p)].append((s, r))
    labels = ctx.labels(ctx.p.slab_id_regex)
    by_key = defaultdict(list)
    for l in labels:
        by_key[match_key(l.text, ctx.p)].append(l)
    loose_rows = {loose_key(r.cells["id"]): (s, r) for lst in rows.values() for s, r in lst}
    # A. schedule -> plan
    for k, lst in rows.items():
        s, r = lst[0]
        if k in by_key:
            continue
        loose_hit = any(loose_key(l.text) == loose_key(r.cells["id"]) for l in labels)
        R.findings.append(ctx.finding(
            rule=4, category="Slab numbers", severity=Severity.REVIEW if loose_hit else Severity.WARNING, sub_check="A schedule not in plan",
            description=f"Scheduled slab {r.cells['id']} not found in the slab plan",
            explanation="Slab type present in schedule with no matching plan label." + (" A differently-formatted label exists." if loose_hit else ""),
            expected=r.cells["id"], detected="not found", identifier=r.cells["id"], layout=s.layout,
            schedule_ref=f"slab schedule row {r.index}", entity_handles=r.handles, bbox=r.bbox,
            confidence=0.5 if loose_hit else (0.75 if labels else 0.5), reason="No plan annotation for this schedule entry",
            recommended_action="Confirm whether the slab type is used on this level."))
    # B. plan -> schedule
    for k, labs in by_key.items():
        if k in rows:
            continue
        lk = loose_rows.get(loose_key(labs[0].text))
        R.findings.append(ctx.finding(
            rule=4, category="Slab numbers", severity=Severity.REVIEW if lk else Severity.ERROR, sub_check="B plan not in schedule",
            description=f"Slab {labs[0].text} appears in the plan but not in the slab schedule",
            explanation=f"{len(labs)} plan label(s)." + (f" Similar schedule entry {lk[1].cells['id']} exists (format differs)." if lk else ""),
            expected="schedule entry", detected="none", identifier=labs[0].text, layout=labs[0].layout,
            entity_handles=[l.handle for l in labs], bbox=union_bbox([l.bbox for l in labs]),
            confidence=0.5 if lk else 0.85, reason="Plan slab identifier absent from schedule",
            recommended_action="Add to schedule or correct the plan label."))
    # F. required fields
    for s in scheds:
        miss_cols = [f for f in ctx.p.slab_required_fields if f != "id" and f not in s.header]
        for f in miss_cols:
            R.status = "PARTIAL"
            R.findings.append(ctx.finding(rule=4, category="Slab numbers", severity=Severity.REVIEW, sub_check="column not found",
                                          description=f"Slab schedule has no column recognised as '{f}'", layout=s.layout, bbox=s.bbox,
                                          explanation="Row-level check of this field not performed.", confidence=0.5,
                                          reason="Column mapping missing", recommended_action=f"Add header wording to slab_columns.{f}."))
        for r in s.rows:
            for f in ctx.p.slab_required_fields:
                if f in miss_cols or f == "id":
                    continue
                if is_blank(r.cells.get(f)):
                    R.findings.append(ctx.finding(
                        rule=4, category="Slab numbers", severity=Severity.ERROR, sub_check="F required field",
                        description=f"Slab {r.cells.get('id', '?')}: '{f}' missing in the schedule",
                        explanation=f"Cell under '{s.header.get(f, f)}' is empty.", identifier=r.cells.get("id"), layout=s.layout,
                        schedule_ref=f"slab schedule row {r.index}", entity_handles=r.handles, bbox=r.bbox, confidence=0.9,
                        reason="Required slab data absent", recommended_action="Complete the schedule entry."))
    # C / D / E : panels
    panels, heuristic = slab_panels(ctx)
    if not panels:
        R.status = "PARTIAL"
        R.notes.append("No slab panel boundaries recognised; panel-level checks (C, D, E) not performed.")
        R.findings.append(ctx.not_checked(4, "Slab numbers", "Slab panels not checked",
                                          "No closed polylines of plausible panel size were found. Panel-level checks need panel boundaries.",
                                          "Set panel_layers in the profile or map panel boundaries manually."))
        return R
    sorted_p = sorted(panels, key=lambda pn: pn["area"])   # smallest first for nesting
    assigned = defaultdict(list)
    loose_labels = []
    for lab in labels:
        c = ctx.centre(lab)
        for pn in sorted_p:
            if pn["poly"].layout == lab.layout and point_in_poly(c, pn["poly"].pts):
                assigned[id(pn)].append(lab); break
        else:
            loose_labels.append(lab)
    for pn in panels:
        labs = assigned.get(id(pn), [])
        pl = pn["poly"]
        base = 0.8 if not heuristic else 0.5
        if not labs:
            R.findings.append(ctx.finding(
                rule=4, category="Slab numbers", severity=Severity.WARNING if not heuristic else Severity.REVIEW, sub_check="C panel without label",
                description="Slab panel without a slab number",
                explanation=f"Closed boundary on layer {pl.layer}, area {pn['area'] / 1e6:.1f} m2 contains no slab label.",
                layout=pl.layout, floor_level=ctx.floor_for(pl.layout), entity_handles=[pl.handle], bbox=pn["bbox"], confidence=base - 0.1,
                reason="No slab annotation inside the panel" + (" (panel inferred from any closed polyline)" if heuristic else ""),
                recommended_action="Add the slab number or confirm the polygon is not a slab panel."))
        elif len(labs) > 1 and not ctx.p.allow_multiple_slab_labels:
            R.findings.append(ctx.finding(
                rule=4, category="Slab numbers", severity=Severity.WARNING, sub_check="D multiple labels",
                description=f"Panel contains {len(labs)} slab-number annotations ({', '.join(l.text for l in labs)})",
                explanation="One slab number per panel expected by the profile.", identifier=", ".join(l.text for l in labs),
                layout=pl.layout, entity_handles=[pl.handle] + [l.handle for l in labs], bbox=pn["bbox"], confidence=base,
                reason="More than one slab label within a single panel", recommended_action="Remove the extra label or split the panel."))
    if loose_labels:
        for lab in loose_labels:
            R.findings.append(ctx.finding(
                rule=4, category="Slab numbers", severity=Severity.REVIEW, sub_check="E not in a panel",
                description=f"Slab label {lab.text} is not inside any recognised panel",
                explanation="Panel recognition may be incomplete.", identifier=lab.text, layout=lab.layout,
                entity_handles=[lab.handle], bbox=lab.bbox, confidence=0.4, reason="Label outside all panel boundaries",
                recommended_action="Check the label position / panel layer settings."))
    return R
