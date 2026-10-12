from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    ERROR = "ERROR"          # reliable evidence of a discrepancy
    WARNING = "WARNING"      # probable discrepancy, needs confirmation
    REVIEW = "REVIEW"        # ambiguous interpretation / insufficient evidence
    PASS = "PASS"            # check performed and passed
    NOT_CHECKED = "NOT CHECKED"  # check could not be completed reliably


# overlay colours used by the (Stage 2) preview
SEVERITY_COLOUR = {
    Severity.ERROR: "#D92D20",
    Severity.WARNING: "#F58220",
    Severity.REVIEW: "#E8A317",
    Severity.PASS: "#16803C",
    Severity.NOT_CHECKED: "#6B7280",
}

REVIEW_STATUSES = ("Unreviewed", "Reviewed", "Confirmed Error", "False Positive", "Needs Clarification")


@dataclass
class Finding:
    rule: int
    category: str
    severity: Severity
    description: str
    explanation: str = ""
    expected: Optional[str] = None
    detected: Optional[str] = None
    difference: Optional[str] = None
    identifier: Optional[str] = None
    layout: Optional[str] = None
    floor_level: Optional[str] = None
    schedule_ref: Optional[str] = None
    entity_handles: list = field(default_factory=list)
    bbox: Optional[tuple] = None          # (minx, miny, maxx, maxy) in drawing units; None = unknown (never invented)
    confidence: float = 0.0
    reason: str = ""
    recommended_action: str = ""
    review_status: str = "Unreviewed"
    sub_check: str = ""
    drawing_file: str = ""
    id: str = ""

    def to_dict(self):
        d = asdict(self)
        d["severity"] = self.severity.value
        d["colour"] = SEVERITY_COLOUR[self.severity]
        return d


class FindingFactory:
    """Issues stable, sequential finding IDs per rule."""
    def __init__(self, drawing_file: str):
        self.drawing_file = drawing_file
        self.counters: dict[int, int] = {}

    def make(self, **kw) -> Finding:
        rule = kw["rule"]
        self.counters[rule] = self.counters.get(rule, 0) + 1
        f = Finding(**kw)
        f.id = f"R{rule}-{self.counters[rule]:04d}"
        f.drawing_file = self.drawing_file
        f.confidence = round(f.confidence, 2)
        return f
