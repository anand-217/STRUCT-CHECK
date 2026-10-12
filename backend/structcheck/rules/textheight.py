"""Rule 8 - text-height consistency. Never modifies anything; reports configured vs inferred standards."""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from ..findings import Severity
from ..context import RuleResult
from ..geom import in_bbox
from .titles import is_title_text

REBAR = re.compile(r"(\d+\s*[-/]?\s*(?:T|Y|#|%%C|Ø|Φ|ø|DIA)\s*\d+)|(@\s*\d+)|(\d+\s*[TY]\s*@)|(\d+\s*-\s*\d+\s*[TY])", re.I)
REVISION = re.compile(r"\b(REVISION|REV\.?|DRAWN|CHECKED|APPROVED|DRG\.? ?NO|DRAWING NO|CLIENT|PROJECT|SCALE|DATE)\b", re.I)


def _matches(rx_list, s):
    return any(re.search(r, s, re.I) for r in rx_list)


def classify(ctx, t):
    """Returns (category, excluded: bool, reason)."""
    p = ctx.p
    # explicit engineer exclusions
    if t.handle in p.exclude_text_handles:
        return "-", True, "Excluded by engineer (selected object)"
    if _matches(p.exclude_text_layers, t.layer): return "-", True, f"Excluded layer {t.layer}"
    if t.style in p.exclude_text_styles: return "-", True, f"Excluded text style {t.style}"
    if any(re.search(r, b, re.I) for b in t.block_path for r in p.exclude_text_blocks): return "-", True, "Excluded block"
    if _matches(p.exclude_text_patterns, t.text): return "-", True, "Excluded by content pattern"
    if t.kind in p.exclude_entity_types: return "-", True, f"Excluded entity type {t.kind}"
    for reg in p.exclude_regions:
        if reg.get("layout", t.layout) == t.layout and in_bbox((t.x, t.y), reg["bbox"]):
            return "-", True, f"Inside region marked as {reg.get('kind', 'excluded')} area"
    # default exclusions (title block, headings, notes, revision tables)
    if any(re.search(r"TITLE|T-?BLOCK|BORDER|FRAME|SHEET", b, re.I) for b in t.block_path):
        return "-", True, "Default: text inside a title-block/border block"
    if re.search(r"TITLE|TBLOCK|T-BLOCK|BORDER|REVISION", t.layer, re.I):
        return "-", True, "Default: title-block layer"
    if is_title_text(t.text.replace("\n", " ")):
        return "-", True, "Default: drawing title / heading"
    if REVISION.search(t.text) and not ctx.in_schedule(t) and len(t.text.split()) <= 6 and re.search(r"REV|DRAWN|CHECK|APPROV|DRG|DRAWING NO|CLIENT|PROJECT", t.text, re.I):
        return "-", True, "Default: revision / title-block metadata"
    if not p.include_notes_check:
        words = len(t.text.split())
        if re.search(r"NOTE", t.layer, re.I): return "-", True, "Default: general notes layer"
        if re.match(r"^\s*NOTES?\b", t.text, re.I): return "-", True, "Default: general notes"
        if t.nlines >= 4 or words >= 8: return "-", True, "Default: long narrative text treated as a note (heuristic)"
    # categorise
    first = t.text.split("\n")[0].strip()
    if ctx.in_schedule(t):
        for s in ctx.schedules:
            if s.layout == t.layout and in_bbox((t.x, t.y), s.bbox):
                hdr_y = max(r.y for r in s.rows)
                part = "header" if t.y > hdr_y + 1e-6 else "body"
                return f"{s.type.capitalize()} schedule text ({part})", False, ""
    if t.kind == "DIMENSION": return "Dimensions", False, ""
    if re.fullmatch(p.beam_id_regex, first, re.I): return "Beam numbers", False, ""
    if re.fullmatch(p.slab_id_regex, first, re.I): return "Slab numbers", False, ""
    if re.fullmatch(p.column_id_regex, first, re.I): return "Column numbers", False, ""
    if re.search(r"GRID", t.layer, re.I) and len(first) <= 3: return "Grid labels", False, ""
    if REBAR.search(first): return "Reinforcement annotations", False, ""
    return "General structural annotations", False, ""


def run(ctx) -> RuleResult:
    R = RuleResult(8, "Text-height consistency")
    p = ctx.p
    rows, groups = [], defaultdict(list)
    for t in ctx.d.texts:
        cat, excl, why = classify(ctx, t)
        row = {"layout": t.layout, "category": cat, "text": t.text.split("\n")[0][:60], "layer": t.layer, "style": t.style,
               "kind": t.kind, "handle": t.handle, "raw_height": round(t.raw_height, 4), "effective_height": round(t.eff_height, 4),
               "effective_certain": t.height_certain, "height_note": t.height_note, "expected": None, "expected_source": None,
               "difference": None, "included": not excl, "exclusion_reason": why, "severity": "", "review_status": "Unreviewed", "_t": t}
        rows.append(row)
        if not excl:
            groups[(cat, t.layout if not t.is_model else "Model")].append(row)
    n_incl = sum(1 for r in rows if r["included"])
    if not rows:
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(8, "Text height", "No text found", "Drawing has no inspectable text."))
        return R
    dist = {}
    for (cat, scope), grp in groups.items():
        certain = [r for r in grp if r["effective_certain"]]
        uncertain = [r for r in grp if not r["effective_certain"]]
        cnt = Counter(round(r["effective_height"], 3) for r in certain)
        dist[f"{cat} [{scope}]"] = dict(sorted(cnt.items()))
        if uncertain:   # cannot rely on plotted height -> ONE aggregated REVIEW per category/scope (not one per text)
            notes = sorted({r["height_note"] for r in uncertain})
            ts = [r["_t"] for r in uncertain]
            for r in uncertain:
                r["severity"] = "REVIEW"
            from ..geom import union_bbox
            R.findings.append(ctx.finding(
                rule=8, category="Text height", severity=Severity.REVIEW, sub_check="effective height uncertain",
                description=f"{cat} [{scope}]: effective plotted height not determinable for {len(uncertain)} text object(s)",
                explanation="Raw heights are reported in the Text Height Analysis sheet. Reasons: " + "; ".join(notes),
                detected=f"raw heights {sorted({r['raw_height'] for r in uncertain})[:8]}", layout=scope,
                entity_handles=[t.handle for t in ts][:200], bbox=union_bbox([t.bbox for t in ts]), confidence=0.3,
                reason="; ".join(notes), recommended_action="Check the plotted size manually (annotation scale / viewport scale)."))
            R.status = "PARTIAL"
        std = p.text_categories_standard.get(cat)
        total = len(certain)
        if std is not None:
            ref, source, dominance = float(std), "configured", 1.0
        elif total >= p.text_min_group_size and cnt:
            ref, n = cnt.most_common(1)[0]
            dominance = n / total
            source = "inferred" if dominance >= p.text_min_dominance else "uncertain"
        else:
            ref, source, dominance = None, "none", 0.0
        if source == "uncertain" and len(cnt) > 1:
            R.findings.append(ctx.finding(
                rule=8, category="Text height", severity=Severity.REVIEW, sub_check="no reliable standard",
                description=f"{cat} [{scope}]: no dominant text height ({dict(cnt)})",
                explanation="No height is used by enough items to be an inferred standard. Set a standard height in the profile.",
                layout=scope, confidence=0.4, reason="Distribution too mixed", recommended_action="Configure a standard height for this category."))
        for r in certain:
            if ref is None or source == "uncertain":
                r["expected_source"] = source if source != "none" else "insufficient items"
                continue
            tol = max(abs(ref) * p.text_height_tolerance_pct / 100.0, 1e-6)
            diff = r["effective_height"] - ref
            r["expected"], r["expected_source"], r["difference"] = ref, source, round(diff, 4)
            t = r["_t"]
            if abs(diff) > tol:
                if source == "configured":
                    sev, conf = Severity.ERROR, 0.95
                elif dominance >= p.text_likely_dominance:
                    sev, conf = Severity.WARNING, 0.7
                else:
                    sev, conf = Severity.REVIEW, 0.5
                r["severity"] = sev.value
                kind = "smaller" if diff < 0 else "larger"
                R.findings.append(ctx.finding(
                    rule=8, category="Text height", severity=sev, sub_check=f"{source} standard",
                    description=f"{cat}: '{r['text']}' is {kind} than the {source} standard",
                    explanation=f"Category {cat}, style {t.style}, layer {t.layer}. Raw {r['raw_height']:g}, effective {r['effective_height']:g}. "
                                + ("Standard configured by the engineer." if source == "configured" else
                                   f"Reference inferred from the drawing ({dominance:.0%} of items) - not an approved requirement."),
                    expected=f"{ref:g} ({source})", detected=f"{r['effective_height']:g}", difference=f"{diff:+g}",
                    identifier=r["text"], layout=t.layout, floor_level=ctx.floor_for(t.layout), entity_handles=[t.handle], bbox=t.bbox,
                    confidence=conf, reason=f"Height differs from {source} reference by more than {p.text_height_tolerance_pct:g}%",
                    recommended_action="Check whether the different size is intentional. StructCheck never changes text."))
    # legibility (only when plotted size is computable)
    for r in rows:
        t = r["_t"]
        if not r["included"] or not r["effective_certain"]:
            continue
        if t.is_model and not p.plot_scale:
            continue
        plotted = ctx.mm(t.eff_height) / (p.plot_scale if (t.is_model and p.plot_scale) else 1.0)
        r["plotted_mm"] = round(plotted, 3)
        if plotted < p.min_plotted_text_mm:
            r["severity"] = r["severity"] or "WARNING"
            R.findings.append(ctx.finding(
                rule=8, category="Text height", severity=Severity.WARNING, sub_check="small text",
                description=f"'{r['text']}' plots at {plotted:.2f} mm - may be hard to read",
                expected=f">= {p.min_plotted_text_mm:g} mm", detected=f"{plotted:.2f} mm", identifier=r["text"], layout=t.layout,
                entity_handles=[t.handle], bbox=t.bbox, confidence=0.6, reason="Below minimum plotted text height",
                recommended_action="Check legibility on a plot preview."))
    # cross-layout comparison of dominant heights (paper space)
    by_cat = defaultdict(dict)
    for (cat, scope), grp in groups.items():
        c = Counter(round(r["effective_height"], 3) for r in grp if r["effective_certain"])
        if len(c) and scope != "Model":
            by_cat[cat][scope] = c.most_common(1)[0][0]
    for cat, d in by_cat.items():
        if len(set(d.values())) > 1:
            R.findings.append(ctx.finding(
                rule=8, category="Text height", severity=Severity.REVIEW, sub_check="cross-layout",
                description=f"{cat}: dominant height differs between layouts ({d})", confidence=0.4,
                reason="Comparable annotations use different sizes on different layouts",
                recommended_action="Confirm layouts are meant to use different sizes."))
    for r in rows:
        r.pop("_t", None)
    R.extra = {"analysis": rows, "distribution": dist, "included": n_incl, "excluded": len(rows) - n_incl}
    if any(not r["effective_certain"] for r in rows if r["included"]):
        R.status = "PARTIAL"
        R.notes.append("Some text heights could not be resolved to a plotted height; they are listed as REVIEW with raw values.")
    if not R.findings:
        R.notes.append("No height outliers found among included text.")
    return R
