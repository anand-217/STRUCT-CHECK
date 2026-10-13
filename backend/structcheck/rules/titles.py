"""Rule 6 - sheet / layout / schedule title consistency (floor-level semantics)."""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from ..findings import Severity
from ..context import RuleResult
from ..geom import union_bbox

ORD = {"FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5, "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8,
       "NINTH": 9, "TENTH": 10}
NAMED = {"GROUND": "G", "PLINTH": "PLINTH", "STILT": "STILT", "PODIUM": "PODIUM", "TERRACE": "TERRACE", "ROOF": "ROOF",
         "FOUNDATION": "FOUNDATION", "BASEMENT": "BASEMENT"}
TITLE_WORDS = re.compile(r"\b(SCHEDULE|LAYOUT|DETAILS?|PLAN|RCC)\b")

def parse_levels(text, abbr):
    t = " " + re.sub(r"[^A-Z0-9+ .]", " ", text.upper()) + " "
    for k, v in (abbr or {}).items():
        t = re.sub(rf"(?<![A-Z0-9]){re.escape(k.upper())}(?![A-Z0-9])", v.upper(), t)
    levels = set()
    for m in re.finditer(r"\b(\d+)(?:ST|ND|RD|TH)\b", t):
        levels.add(int(m.group(1)))
    for w, n in ORD.items():
        if re.search(rf"\b{w}\b", t): levels.add(n)
    for w, n in NAMED.items():
        if re.search(rf"\b{w}\b", t): levels.add(n)
    return levels

def title_kind(text):
    u = text.upper()
    if "SCHEDULE" in u:
        return "beam schedule" if "BEAM" in u else "slab schedule" if "SLAB" in u else "column schedule" if "COL" in u else "schedule"
    if "LAYOUT" in u or re.search(r"\bPLAN\b", u): return "layout"
    if "DETAILS" in u or "DETAIL" in u or "RCC" in u: return "sheet"
    return "other"

def is_title_text(text):
    u = text.upper()
    return bool(TITLE_WORDS.search(u)) and len(u.split()) >= 3 and bool(re.search(r"LEVEL|FLOOR|SLAB|BEAM|COLUMN|SCHEDULE|LAYOUT", u))

def collect_titles(ctx):
    out = []
    for t in ctx.d.texts:
        if t.kind in ("TEXT", "MTEXT", "ATTRIB", "MLEADER") and is_title_text(t.text.replace("\n", " ")):
            lv = parse_levels(t.text, ctx.p.title_abbreviations)
            out.append({"item": t, "levels": lv, "kind": title_kind(t.text), "layout": t.layout, "source": "text"})
    for lay in ctx.d.layouts:
        if lay.lower() != "model":
            lv = parse_levels(lay, ctx.p.title_abbreviations)
            if lv:
                out.append({"item": None, "levels": lv, "kind": "layout tab name", "layout": lay, "source": "layout name", "text": lay})
    return out

def title_levels_by_layout(ctx):
    per = defaultdict(Counter)
    for tt in collect_titles(ctx):
        if tt["levels"]:
            per[tt["layout"]][tuple(sorted(tt["levels"], key=str))] += 1
    res = {}
    for lay, c in per.items():
        lv, _ = c.most_common(1)[0]
        res[lay] = "/".join(("G" if x == 0 else str(x)) for x in lv)
    return res

def _label(lv):
    return ", ".join(sorted(("Ground" if x == "G" else str(x)) for x in lv))

def run(ctx) -> RuleResult:
    R = RuleResult(6, "Sheet / layout / schedule title consistency")
    titles = [t for t in collect_titles(ctx)]
    with_lv = [t for t in titles if t["levels"]]
    if not titles:
        R.status = "SKIPPED"
        R.findings.append(ctx.not_checked(6, "Titles", "No title text recognised",
                                          "No text containing title words (LAYOUT/SCHEDULE/DETAILS/LEVEL...) was found."))
        return R
    by_layout = defaultdict(list)
    for t in with_lv:
        by_layout[t["layout"]].append(t)
    # titles that carry no level but belong to a drawing whose other titles do
    for lay, tl in by_layout.items():
        groups = defaultdict(list)
        for t in tl:
            groups[frozenset(t["levels"])].append(t)
        if len(groups) < 2 and not any(not (a & b) for a in groups for b in groups if a != b):
            continue
        keys = list(groups)
        # conflict only when level sets are disjoint
        conflict = any(not (a & b) for i, a in enumerate(keys) for b in keys[i + 1:])
        if not conflict:
            continue
        ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
        unique_dom = len(ranked) == 1 or len(ranked[0][1]) > len(ranked[1][1])
        dom = ranked[0][0] if unique_dom else None
        minority = [t for k, v in ranked for t in v if (dom is None or not (k & dom))]
        involved = minority if dom is not None else [t for _, v in ranked for t in v]
        is_model = lay.lower() == "model"
        sev = Severity.WARNING if (not is_model or ctx.p.single_floor_per_drawing) else Severity.REVIEW
        conf = 0.8 if dom is not None else 0.6
        if not unique_dom and sev == Severity.WARNING:
            conf = 0.6
        shown = "; ".join(f'"{(t["item"].text if t["item"] else t["text"])}" [{t["kind"]}] -> level {_label(t["levels"])}' for _, v in ranked for t in v)
        bbox = union_bbox([t["item"].bbox for t in involved if t["item"]])
        R.findings.append(ctx.finding(
            rule=6, category="Titles", severity=sev,
            description="Potential floor-level mismatch between titles in the same drawing",
            explanation=("Titles refer to different floor/slab levels. Dominant level: " + _label(dom) + ". " if dom else
                         "Titles refer to different floor/slab levels and no level is dominant. ") + "All titles: " + shown,
            expected=_label(dom) if dom else None,
            detected="; ".join(_label(t["levels"]) for t in involved),
            layout=lay, floor_level=ctx.floor_for(lay),
            entity_handles=[t["item"].handle for t in involved if t["item"]], bbox=bbox, confidence=conf,
            reason="Different level words/ordinals found in titles that should describe the same level"
                   + ("" if not is_model or ctx.p.single_floor_per_drawing else " (model space may hold several floors - convention not confirmed)"),
            recommended_action="Check which floor the sheet is for and correct the conflicting title(s). Set 'single_floor_per_drawing' in the profile if this file holds several floors."))
    # titles with no recognisable level in a drawing that otherwise names levels
    if not R.findings:
        R.notes.append("No conflicting level references found among recognised titles.")
    if not with_lv:
        R.status = "PARTIAL"
        R.notes.append("Titles were found but none contained a recognisable floor/level word; semantic comparison not possible.")
        R.findings.append(ctx.finding(rule=6, category="Titles", severity=Severity.REVIEW,
                                      description="Titles found but no floor/level could be interpreted",
                                      explanation="Check approved abbreviations in the profile.", confidence=0.5,
                                      reason="No level tokens recognised", recommended_action="Add title abbreviations to the profile."))
    return R
