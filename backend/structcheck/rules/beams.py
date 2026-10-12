"""Rules 1, 2, 3, 5 - beam checks."""
from __future__ import annotations
import math, re
from collections import defaultdict
from dataclasses import dataclass, field
from ..findings import Severity
from ..context import RuleResult
from ..geom import seg_dist, union_bbox, angle_mod_pi, bbox_of
from ..ids import strict_key, loose_key, match_key, is_blank, first_number


@dataclass
class BeamGeo:
    handles: list
    layout: str
    segs: list
    width_du: float
    kind: str
    layer: str
    layers_heuristic: bool = False
    note: str = ""

    @property
    def bbox(self):
        return bbox_of([p for s in self.segs for p in s])


def _layer_ok(ctx, layer, pats):
    if ctx.layer_excluded(layer):
        return False
    return (not pats) or any(re.search(r, layer, re.I) for r in pats)


def beam_geometry(ctx):
    cached = getattr(ctx, "_beam_geo", None)
    if cached is not None:
        return cached
    p, d = ctx.p, ctx.d
    wmin, wmax, Lmin = ctx.du(p.beam_min_width_mm), ctx.du(p.beam_max_width_mm), ctx.du(p.beam_min_length_mm)
    geos = []
    for ml in d.mlines:
        if ctx.layer_excluded(ml.layer) or len(ml.pts) < 2:
            continue
        segs = list(zip(ml.pts[:-1], ml.pts[1:]))
        if ml.closed:
            segs.append((ml.pts[-1], ml.pts[0]))
        note = ""
        if ml.n_elements > 2:
            note = f"MLINE style '{ml.style}' has {ml.n_elements} elements (may include a centreline); width = outer offsets span"
        if ml.width_du <= 0:
            note = "MLINE width evaluates to zero (style offsets or scale)"
        geos.append(BeamGeo([ml.handle], ml.layout, segs, ml.width_du, "MLINE", ml.layer, False, note))
    # layer selection for LINE/polyline representations
    user_layers = p.beam_layers
    auto = []
    if not user_layers:
        auto = [l for l in d.layers if re.search(r"BEAM", l, re.I)]
    pats = user_layers or ([re.escape(l) for l in auto] if auto else [])
    heuristic = not user_layers and not auto
    for lay in d.layouts:
        lines = [l for l in d.lines if l.layout == lay and _layer_ok(ctx, l.layer, pats)
                 and not ctx.point_in_schedule(lay, ((l.p1[0] + l.p2[0]) / 2, (l.p1[1] + l.p2[1]) / 2))
                 and math.dist(l.p1, l.p2) >= Lmin]
        used = set()
        lines.sort(key=lambda l: -math.dist(l.p1, l.p2))
        for i, a in enumerate(lines):
            if i in used:
                continue
            ang_a = angle_mod_pi(a.p1, a.p2)
            la = math.dist(a.p1, a.p2)
            ux, uy = (a.p2[0] - a.p1[0]) / la, (a.p2[1] - a.p1[1]) / la
            best = None
            for j in range(i + 1, len(lines)):
                if j in used:
                    continue
                b = lines[j]
                dang = abs(angle_mod_pi(b.p1, b.p2) - ang_a)
                if min(dang, math.pi - dang) > math.radians(1.0):
                    continue
                nx, ny = -uy, ux
                dist = abs((b.p1[0] - a.p1[0]) * nx + (b.p1[1] - a.p1[1]) * ny)
                if not (wmin <= dist <= wmax):
                    continue
                ta = sorted([(q[0] - a.p1[0]) * ux + (q[1] - a.p1[1]) * uy for q in (a.p1, a.p2)])
                tb = sorted([(q[0] - a.p1[0]) * ux + (q[1] - a.p1[1]) * uy for q in (b.p1, b.p2)])
                ov = min(ta[1], tb[1]) - max(ta[0], tb[0])
                if ov < 0.6 * min(la, math.dist(b.p1, b.p2)):
                    continue
                if best is None or dist < best[0]:
                    best = (dist, j)
            if best:
                dist, j = best
                b = lines[j]
                used.update((i, j))
                mid = lambda q: ((q[0][0] + q[1][0]) / 2, (q[0][1] + q[1][1]) / 2)
                nx, ny = -uy, ux
                s = 1 if ((b.p1[0] - a.p1[0]) * nx + (b.p1[1] - a.p1[1]) * ny) > 0 else -1
                c1 = (a.p1[0] + s * nx * dist / 2, a.p1[1] + s * ny * dist / 2)
                c2 = (a.p2[0] + s * nx * dist / 2, a.p2[1] + s * ny * dist / 2)
                geos.append(BeamGeo([a.handle, b.handle], lay, [(c1, c2)], dist, "LINE-PAIR", a.layer, heuristic))
        for pl in d.polys:
            if pl.layout != lay or not pl.closed or not _layer_ok(ctx, pl.layer, pats):
                continue
            pts = pl.pts[:-1] if len(pl.pts) == 5 and pl.pts[0] == pl.pts[-1] else pl.pts
            if len(pts) != 4:
                continue
            s1, s2 = math.dist(pts[0], pts[1]), math.dist(pts[1], pts[2])
            long_, short = max(s1, s2), min(s1, s2)
            if short <= 0 or long_ / short < 3 or not (wmin <= short <= wmax) or long_ < Lmin:
                continue
            if s1 >= s2:
                m1 = ((pts[0][0] + pts[3][0]) / 2, (pts[0][1] + pts[3][1]) / 2)
                m2 = ((pts[1][0] + pts[2][0]) / 2, (pts[1][1] + pts[2][1]) / 2)
            else:
                m1 = ((pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2)
                m2 = ((pts[2][0] + pts[3][0]) / 2, (pts[2][1] + pts[3][1]) / 2)
            geos.append(BeamGeo([pl.handle], lay, [(m1, m2)], short, "RECT-POLYLINE", pl.layer, heuristic))
    ctx._beam_geo = geos
    return geos


def associate(ctx):
    """Associate every plan beam label with its nearest beam geometry. Returns (assoc, unassoc, ambiguous)."""
    cached = getattr(ctx, "_beam_assoc", None)
    if cached is not None:
        return cached
    geos = beam_geometry(ctx)
    labels = ctx.labels(ctx.p.beam_id_regex)
    radius = ctx.du(ctx.p.label_search_radius_mm)
    assoc, unassoc, ambiguous = [], [], []
    for lab in labels:
        c = Context_centre(lab)
        cand = []
        for g in geos:
            if g.layout != lab.layout:
                continue
            dist = min(seg_dist(c, a, b) for a, b in g.segs)
            if dist <= radius + g.width_du / 2:
                cand.append((dist, g))
        cand.sort(key=lambda x: x[0])
        if not cand:
            unassoc.append(lab)
        elif len(cand) > 1 and (cand[1][0] - cand[0][0]) < 0.15 * max(cand[0][0], 1e-9):
            ambiguous.append((lab, [g for _, g in cand[:2]]))
        else:
            assoc.append((lab, cand[0][1]))
    ctx._beam_assoc = (assoc, unassoc, ambiguous)
    return ctx._beam_assoc


def Context_centre(t):
    b = t.bbox
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _beam_scheds(ctx):
    return ctx.sched("beam")


def _rows_by_key(ctx):
    rows = defaultdict(list)
    for s in _beam_scheds(ctx):
        for r in s.rows:
            if r.cells.get("id"):
                rows[match_key(r.cells["id"], ctx.p)].append((s, r))
    return rows


# ------------------------------------------------------------------ Rule 1
def run_rule1(ctx) -> RuleResult:
    R = RuleResult(1, "Missing beam numbers in plan vs beam schedule")
    if not _beam_scheds(ctx):
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(1, "Beam numbers", "Beam schedule not detected",
                                          "No beam schedule header (id column plus at least two design columns) was recognised."))
        return R
    rows = _rows_by_key(ctx)
    labels = ctx.labels(ctx.p.beam_id_regex)
    geos = beam_geometry(ctx)
    assoc, unassoc, ambiguous = associate(ctx)
    present = {match_key(l.text, ctx.p) for l in labels}
    present_loose = {loose_key(l.text) for l in labels}
    # A. schedule beam types with no plan occurrence
    for k, lst in rows.items():
        s, r = lst[0]
        if k in present:
            continue
        loose_hit = loose_key(r.cells["id"]) in present_loose
        sev = Severity.REVIEW if loose_hit else Severity.WARNING
        R.findings.append(ctx.finding(
            rule=1, category="Beam numbers", severity=sev, sub_check="type not in plan",
            description=f"Scheduled beam {r.cells['id']} has no label in the plan" if not loose_hit
            else f"Scheduled beam {r.cells['id']} only matches a plan label after hyphen/leading-zero normalisation",
            explanation="The beam type is in the schedule but no matching beam-number annotation was found in any layout.",
            expected=r.cells["id"], detected="not found in plan", identifier=r.cells["id"], layout=s.layout,
            schedule_ref=f"{s.type} schedule row {r.index}", entity_handles=r.handles, bbox=r.bbox,
            confidence=0.45 if loose_hit else (0.8 if labels else 0.55),
            reason="Schedule identifier absent from plan annotations" + (" (plan contains no beam labels at all - label pattern may not fit this drawing)" if not labels else ""),
            recommended_action="Confirm whether this beam type is used on this floor; if so add its label to the plan."))
    # B. beam instances with no label
    if not geos:
        R.status = "PARTIAL"
        R.notes.append("No beam geometry (MLINE / parallel line pairs / thin rectangles) recognised; per-instance label check not performed.")
        R.findings.append(ctx.not_checked(1, "Beam numbers", "Beam instances not checked",
                                          "No beam geometry could be recognised, so missing labels on individual beams cannot be detected.",
                                          "Set beam layers in the profile or check unsupported entities."))
    labelled = {id(g) for _, g in assoc} | {id(g) for _, gs in ambiguous for g in gs}
    for g in geos:
        if id(g) in labelled:
            continue
        L = sum(math.dist(a, b) for a, b in g.segs)
        short = ctx.mm(L) < 2000
        conf = 0.7 - (0.2 if short else 0) - (0.2 if g.layers_heuristic else 0)
        R.findings.append(ctx.finding(
            rule=1, category="Beam numbers", severity=Severity.WARNING if conf >= 0.5 else Severity.REVIEW,
            sub_check="instance without label",
            description="Beam without a beam-number label",
            explanation=f"{g.kind} on layer {g.layer}, length {ctx.mm(L):.0f} mm, width {ctx.mm(g.width_du):.0f} mm has no beam label within "
                        f"{ctx.p.label_search_radius_mm:.0f} mm.",
            layout=g.layout, floor_level=ctx.floor_for(g.layout), entity_handles=g.handles, bbox=g.bbox, confidence=conf,
            reason="No beam-number annotation associated with this geometry" + (" (beam layer inferred, not configured)" if g.layers_heuristic else "") + (" (short member)" if short else ""),
            recommended_action="Verify on the drawing whether this member is a beam and whether its label is missing or placed too far away."))
    for lab in unassoc:
        R.findings.append(ctx.finding(
            rule=1, category="Beam numbers", severity=Severity.REVIEW, sub_check="label not associated",
            description=f"Label {lab.text} cannot be associated with any beam",
            explanation="No recognised beam geometry lies within the search radius of this label.",
            identifier=lab.text, layout=lab.layout, entity_handles=[lab.handle], bbox=lab.bbox, confidence=0.4,
            reason="Label is not near recognised beam geometry", recommended_action="Check label placement or beam layer settings."))
    for lab, gs in ambiguous:
        R.findings.append(ctx.finding(
            rule=1, category="Beam numbers", severity=Severity.REVIEW, sub_check="label ambiguous",
            description=f"Label {lab.text} is equally close to two beams",
            explanation="The label cannot be assigned reliably; neither beam is reported as unlabelled because of it.",
            identifier=lab.text, layout=lab.layout, entity_handles=[lab.handle] + [h for g in gs for h in g.handles],
            bbox=union_bbox([lab.bbox] + [g.bbox for g in gs]), confidence=0.45,
            reason="Two beam geometries within 15% of the same distance", recommended_action="Confirm which beam the label belongs to."))
    return R


# ------------------------------------------------------------------ Rule 2
def run_rule2(ctx) -> RuleResult:
    R = RuleResult(2, "Beam width: drawing vs schedule")
    if not _beam_scheds(ctx):
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(2, "Beam width", "Beam schedule not detected", "Scheduled widths unavailable."))
        return R
    if not any("width" in s.header for s in _beam_scheds(ctx)):
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(2, "Beam width", "No width column in the beam schedule",
                                          "The schedule has no column mapped to 'width'.", "Map the width column in the profile (beam_columns.width)."))
        return R
    rows = _rows_by_key(ctx)
    assoc, unassoc, ambiguous = associate(ctx)
    if not beam_geometry(ctx):
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(2, "Beam width", "No beam geometry recognised", "Drawn widths cannot be measured."))
        return R
    tol = ctx.p.beam_width_tolerance_mm
    checked = 0
    for lab, g in assoc:
        lst = rows.get(match_key(lab.text, ctx.p))
        if not lst:
            continue                       # missing schedule row is Rule 3
        if len(lst) > 1:
            R.findings.append(ctx.finding(
                rule=2, category="Beam width", severity=Severity.REVIEW, identifier=lab.text, layout=lab.layout,
                description=f"{lab.text}: several schedule rows - width not compared",
                explanation="Duplicate schedule rows make the scheduled width ambiguous (see Rule 5).",
                entity_handles=[lab.handle] + g.handles, bbox=union_bbox([lab.bbox, g.bbox]), confidence=0.5,
                reason="Ambiguous schedule match", recommended_action="Resolve the duplicate schedule entries first."))
            continue
        s, r = lst[0]
        w = first_number(r.cells.get("width", ""))
        if w is None:
            continue                       # missing width is Rule 3
        checked += 1
        drawn = ctx.mm(g.width_du)
        diff = drawn - w
        if g.width_du <= 0:
            sev, conf, why = Severity.REVIEW, 0.3, g.note
        elif abs(diff) <= tol:
            continue
        else:
            clean = g.kind in ("MLINE", "LINE-PAIR", "RECT-POLYLINE") and not g.layers_heuristic and not (g.kind == "MLINE" and g.note)
            sev = Severity.ERROR if clean else (Severity.REVIEW if g.kind == "MLINE" and g.note else Severity.WARNING)
            conf = 0.9 if clean else 0.6
            why = f"Width measured from {g.kind} geometry (rotation-independent)." + (f" {g.note}" if g.note else "")
            dep = first_number(r.cells.get("depth", ""))
            if dep is not None and abs(drawn - dep) <= tol:
                why += " Drawn width equals the scheduled depth - width/depth may be swapped."
        R.findings.append(ctx.finding(
            rule=2, category="Beam width", severity=sev, identifier=lab.text, layout=lab.layout, floor_level=ctx.floor_for(lab.layout),
            description=f"Potential beam-width mismatch for {lab.text}",
            explanation=why, expected=f"{w:g} mm", detected=f"{drawn:.0f} mm", difference=f"{diff:+.0f} mm (tolerance {tol:g} mm)",
            schedule_ref=f"beam schedule row {r.index}", entity_handles=[lab.handle] + g.handles + r.handles,
            bbox=union_bbox([lab.bbox, g.bbox]), confidence=conf, reason=why,
            recommended_action="Compare the drawn beam against the schedule and correct whichever is wrong."))
    for lab, gs in ambiguous:
        R.notes.append(f"{lab.text}: not width-checked (label ambiguous between two beams).")
    if checked == 0:
        R.status = "PARTIAL"
        R.notes.append("No label/geometry/schedule triple could be formed; no widths were compared.")
    return R


# ------------------------------------------------------------------ Rule 3
def run_rule3(ctx) -> RuleResult:
    R = RuleResult(3, "Beam missing from schedule / incomplete design data")
    scheds = _beam_scheds(ctx)
    if not scheds:
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(3, "Beam schedule", "Beam schedule not detected", "Nothing to compare plan labels against."))
        return R
    rows = _rows_by_key(ctx)
    loose_rows = defaultdict(list)
    for s in scheds:
        for r in s.rows:
            if r.cells.get("id"):
                loose_rows[loose_key(r.cells["id"])].append((s, r))
    # A / E / F : plan label vs schedule
    seen = defaultdict(list)
    for lab in ctx.labels(ctx.p.beam_id_regex):
        seen[strict_key(lab.text)].append(lab)
    for key, labs in seen.items():
        mk = match_key(labs[0].text, ctx.p)
        hit = rows.get(mk)
        handles = [l.handle for l in labs]
        bb = union_bbox([l.bbox for l in labs])
        if hit is None:
            lk = loose_rows.get(loose_key(labs[0].text))
            if lk:
                R.findings.append(ctx.finding(
                    rule=3, category="Beam schedule", severity=Severity.REVIEW, sub_check="E identifier format",
                    description=f"Plan label {labs[0].text} resembles scheduled {lk[0][1].cells['id']} but is written differently",
                    explanation="Identifiers differ only by hyphen/leading-zero formatting. They are NOT merged unless the profile allows it.",
                    expected=lk[0][1].cells["id"], detected=labs[0].text, identifier=labs[0].text, layout=labs[0].layout,
                    entity_handles=handles + lk[0][1].handles, bbox=bb, confidence=0.6,
                    reason="Possible formatting inconsistency", recommended_action="Standardise the identifier or enable the matching option in the profile."))
            else:
                R.findings.append(ctx.finding(
                    rule=3, category="Beam schedule", severity=Severity.ERROR if len(scheds) else Severity.WARNING, sub_check="A not in schedule",
                    description=f"Beam {labs[0].text} appears in the plan but not in the beam schedule",
                    explanation=f"{len(labs)} plan label(s) with no schedule row.", expected="schedule entry", detected="none",
                    identifier=labs[0].text, layout=labs[0].layout, entity_handles=handles, bbox=bb, confidence=0.85,
                    reason="Plan identifier has no match in the schedule", recommended_action="Add the beam to the schedule or correct the plan label."))
        elif len(hit) > 1:
            R.findings.append(ctx.finding(
                rule=3, category="Beam schedule", severity=Severity.REVIEW, sub_check="F multiple matches",
                description=f"Plan label {labs[0].text} matches {len(hit)} schedule rows",
                explanation="See Rule 5 for the duplicate entries.", identifier=labs[0].text, layout=labs[0].layout,
                entity_handles=handles + [h for _, r in hit for h in r.handles], bbox=bb, confidence=0.7,
                reason="Multiple schedule rows share this identifier", recommended_action="Remove or correct duplicate rows."))
    # B / C / D : required fields
    for s in scheds:
        missing_cols = [f for f in ctx.p.beam_required_fields if f != "id" and f not in s.header]
        for f in missing_cols:
            R.findings.append(ctx.finding(
                rule=3, category="Beam schedule", severity=Severity.REVIEW, sub_check="column not found",
                description=f"Schedule has no column recognised as '{f}'",
                explanation=f"Required field '{f}' could not be located, so per-row checks for it were not performed (not treated as passed).",
                layout=s.layout, bbox=s.bbox, confidence=0.5, reason="Column mapping missing",
                recommended_action=f"Add the schedule's header wording to beam_columns.{f} in the profile."))
        if missing_cols:
            R.status = "PARTIAL"
        for r in s.rows:
            for f in ctx.p.beam_required_fields:
                if f in missing_cols:
                    continue
                if is_blank(r.cells.get(f)):
                    sub = "B dimensions" if f in ("width", "depth") else "C reinforcement" if f in ("top", "bottom", "stirrups") else "D mandatory field"
                    R.findings.append(ctx.finding(
                        rule=3, category="Beam schedule", severity=Severity.ERROR, sub_check=sub,
                        description=f"Beam {r.cells.get('id', '?')}: '{f}' is missing in the schedule",
                        explanation=f"Cell under '{s.header.get(f, f)}' is empty.", expected=f, detected="blank",
                        identifier=r.cells.get("id"), layout=s.layout, schedule_ref=f"beam schedule row {r.index}, column {s.header.get(f, f)}",
                        entity_handles=r.handles, bbox=r.bbox, confidence=0.9, reason="Required schedule data absent",
                        recommended_action="Complete the schedule entry."))
    return R


# ------------------------------------------------------------------ Rule 5
def _data_sig(r):
    d = {k: re.sub(r"[\s]", "", v.upper()).replace("X", "x").replace("×", "x") for k, v in r.cells.items() if k != "id"}
    d.update({k: re.sub(r"[\s]", "", v.upper()) for k, v in r.extra.items()})
    return d

def run_rule5(ctx) -> RuleResult:
    R = RuleResult(5, "Duplicate beam numbers in beam schedule")
    scheds = _beam_scheds(ctx)
    if not scheds:
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(5, "Beam schedule", "Beam schedule not detected", "No schedule rows to inspect."))
        return R
    groups = defaultdict(list)
    for s in scheds:
        for r in s.rows:
            if r.cells.get("id"):
                groups[match_key(r.cells["id"], ctx.p)].append((s, r))
    for k, lst in groups.items():
        if len(lst) < 2:
            continue
        sigs = [_data_sig(r) for _, r in lst]
        conflict = any(sg != sigs[0] for sg in sigs[1:])
        diffs = []
        if conflict:
            for fld in sorted({f for sg in sigs for f in sg}):
                vals = [sg.get(fld, "") for sg in sigs]
                if len(set(vals)) > 1:
                    diffs.append(f"{fld}: " + " | ".join(vals))
        s0 = lst[0][0]
        R.findings.append(ctx.finding(
            rule=5, category="Beam schedule", severity=Severity.ERROR if conflict else Severity.WARNING,
            description=f"Duplicate beam number {lst[0][1].cells['id']} in the beam schedule ({len(lst)} rows)",
            explanation=("Rows have CONFLICTING data - " + "; ".join(diffs)) if conflict else "Rows carry identical data - redundant entry.",
            expected="one row per beam number", detected=f"rows {', '.join(str(r.index) for _, r in lst)}",
            identifier=lst[0][1].cells["id"], layout=s0.layout,
            schedule_ref="; ".join(f"row {r.index}" for _, r in lst), entity_handles=[h for _, r in lst for h in r.handles],
            bbox=union_bbox([r.bbox for _, r in lst]), confidence=0.95,
            reason="Same identifier repeated within the schedule" + (" with different design values" if conflict else ""),
            recommended_action="Delete the redundant row or give the conflicting beam its own number."))
    # strict-different but loose-same (B1 / B-1) inside schedule
    loose = defaultdict(set)
    for s in scheds:
        for r in s.rows:
            if r.cells.get("id"):
                loose[loose_key(r.cells["id"])].add(strict_key(r.cells["id"]))
    for lk, forms in loose.items():
        if len(forms) > 1 and not (ctx.p.hyphen_equivalent or ctx.p.leading_zero_equivalent):
            R.findings.append(ctx.finding(
                rule=5, category="Beam schedule", severity=Severity.REVIEW, sub_check="possible duplicate (format)",
                description=f"Schedule contains {' and '.join(sorted(forms))} - possibly the same beam",
                confidence=0.5, reason="Identifiers differ only in hyphen / leading zeros; not merged automatically",
                layout=scheds[0].layout, recommended_action="Confirm whether these are the same beam."))
    return R
