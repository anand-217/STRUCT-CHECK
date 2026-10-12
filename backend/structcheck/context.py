from __future__ import annotations
import re
from dataclasses import dataclass, field
from .findings import FindingFactory, Severity
from .schedule import detect_schedules
from .geom import in_bbox
from .ids import strict_key

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

    def labels(self, regex):
        rx = re.compile(regex, re.I)
        out = []
        for t in self.plan_texts():
            first = t.text.split("\n")[0].strip()
            if rx.fullmatch(first):
                out.append(t)
        return out

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
