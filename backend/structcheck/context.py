from __future__ import annotations
import re
from dataclasses import dataclass, field, replace
from .findings import FindingFactory, Severity
from .schedule import detect_schedules
from .geom import in_bbox
from .ids import strict_key, clean_label

@dataclass
class RuleResult:
    rule: int
    name: str
    findings: list = field(default_factory=list)
    status: str = "COMPLETED"        # COMPLETED | PARTIAL | SKIPPED
    notes: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

class Context:
    def __init__(self, drawing, profile):
        self.d, self.p = drawing, profile
        self.ff = FindingFactory(drawing.filename)
        self.unit = drawing.unit_mm
        self.schedules = detect_schedules(drawing, profile)
        from .rules.titles import title_levels_by_layout
        self._levels = title_levels_by_layout(self)

    def mm(self, du): return du * self.unit
    def du(self, mm): return mm / self.unit

    def sched(self, typ):
        return [s for s in self.schedules if s.type == typ]

    def layer_excluded(self, layer):
        return any(re.search(r, layer, re.I) for r in self.p.excluded_layers)

    def in_schedule(self, item):
        pt = (item.x, item.y)
        return any(s.layout == item.layout and in_bbox(pt, s.bbox) for s in self.schedules)

    def point_in_schedule(self, layout, pt):
        return any(s.layout == layout and in_bbox(pt, s.bbox) for s in self.schedules)

    def plan_texts(self):
        return [t for t in self.d.texts if t.kind in ("TEXT", "MTEXT", "ATTRIB", "MLEADER")
                and not self.in_schedule(t) and not self.layer_excluded(t.layer)]

    def labels(self, regex, kind=None):
        """Plan labels. If the text sits on a configured label layer (e.g. 'BEAM NO') every short token on it is a label
        (numeric tags such as 12 or 12C work); otherwise the id regex is applied to all plan text."""
        layers = {"beam": self.p.beam_label_layers, "slab": self.p.slab_label_layers, "column": self.p.column_label_layers}.get(kind, [])
        rx = re.compile(regex, re.I)
        out = []
        for t in self.plan_texts():
            first = clean_label(t.text.split("\n")[0])
            if not first:
                continue
            on_layer = any(re.search(l, t.layer, re.I) for l in layers)
            if (on_layer and re.fullmatch(r"[A-Za-z0-9\- ]{1,8}", first)) or rx.fullmatch(first):
                out.append(replace(t, text=first) if first != t.text else t)
        return out

    def beam_labels(self): return self.labels(self.p.beam_id_regex, "beam")
    def slab_labels(self): return self.labels(self.p.slab_id_regex, "slab")
    def column_labels(self): return self.labels(self.p.column_id_regex, "column")

    def mentions(self, ident):
        """Another (non-schedule) text in the drawing that mentions this id, e.g. 'WAIST SLAB S1'. Only for ids with a letter."""
        if not re.search(r"[A-Za-z]", ident):
            return None
        rx = re.compile(r"(?<![A-Z0-9])" + r"\s?".join(re.escape(ch) for ch in strict_key(ident)) + r"(?![A-Z0-9])")
        for t in self.d.texts:
            if t.kind in ("TEXT", "MTEXT", "ATTRIB", "MLEADER") and not self.in_schedule(t) and rx.search(t.text.upper()):
                return t
        return None

    @staticmethod
    def centre(t):
        b = t.bbox
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def floor_for(self, layout):
        lv = self._levels.get(layout)
        return lv or None

    def finding(self, **kw):
        return self.ff.make(**kw)

    def not_checked(self, rule, category, what, why, action="Map the schedule/region manually in the project profile and re-run."):
        return self.finding(rule=rule, category=category, severity=Severity.NOT_CHECKED, description=what,
                            explanation=why, confidence=1.0, reason=why, recommended_action=action)
