"""Rule engine: runs every registered rule, verifies source-file integrity, assembles the result."""
from __future__ import annotations
import os, shutil, time
from dataclasses import dataclass, field
from .context import Context, RuleResult
from .findings import Severity
from .loader import load_drawing, sha256_file
from .profile import ProjectProfile
from .rules import beams, slabs, titles, columns, textheight

RULES = [
    (1, beams.run_rule1), (2, beams.run_rule2), (3, beams.run_rule3), (4, slabs.run),
    (5, beams.run_rule5), (6, titles.run), (7, columns.run), (8, textheight.run),
]   # add new rules here (modular registry)

@dataclass
class CheckResult:
    drawing: dict
    profile: dict
    rules: list
    findings: list
    text_height_analysis: dict
    integrity: dict
    schedules: list
    seconds: float

    def summary(self):
        c = {s.value: 0 for s in Severity}
        for f in self.findings:
            c[f.severity.value] += 1
        completed = sum(1 for r in self.rules if r["status"] == "COMPLETED")
        passed = sum(1 for r in self.rules if r["status"] == "COMPLETED" and r["finding_count"] == 0)
        return {"total_findings": sum(v for k, v in c.items() if k not in ("PASS", "NOT CHECKED")),
                "errors": c["ERROR"], "warnings": c["WARNING"], "review": c["REVIEW"], "not_checked_items": c["NOT CHECKED"],
                "rules_completed": completed, "rules_passed": passed,
                "rules_partial": sum(1 for r in self.rules if r["status"] == "PARTIAL"),
                "rules_skipped": sum(1 for r in self.rules if r["status"] == "SKIPPED")}

    def to_dict(self):
        from . import __version__
        return {"structcheck_version": __version__, "disclaimer": DISCLAIMER, "drawing": self.drawing, "integrity": self.integrity, "summary": self.summary(),
                "rules": self.rules, "findings": [f.to_dict() for f in self.findings],
                "text_height_analysis": self.text_height_analysis, "schedules": self.schedules,
                "profile": self.profile, "seconds": round(self.seconds, 2)}

DISCLAIMER = ("StructCheck assists with drawing quality control and does not replace professional engineering review. "
              "Every finding must be verified by the responsible engineer. The source drawing is never modified.")

def run_checks(path: str, profile: ProjectProfile | None = None, only: list[int] | None = None) -> CheckResult:
    t0 = time.time()
    profile = profile or ProjectProfile()
    hash_before = sha256_file(path)
    drawing = load_drawing(path, profile)
    ctx = Context(drawing, profile)
    results: list[RuleResult] = []
    for num, fn in RULES:
        if only and num not in only:
            continue
        try:
            results.append(fn(ctx))
        except Exception as ex:   # a crashing rule must never be reported as passed
            r = RuleResult(num, f"Rule {num}", status="SKIPPED")
            r.findings.append(ctx.not_checked(num, "Engine", f"Rule {num} failed to run", f"Internal error: {type(ex).__name__}: {ex}"))
            results.append(r)
    for tag in drawing.unsupported:
        results[0].notes.append(f"Unsupported entities present: {tag} x{drawing.unsupported[tag]} (not inspected - review manually)")
    hash_after = sha256_file(path)
    integrity = {"sha256_before": hash_before, "sha256_after": hash_after, "unchanged": hash_before == hash_after,
                 "note": "Parsing was done on a temporary working copy; highlights live only in the review overlay/report."}
    if not drawing._keep_temp:
        shutil.rmtree(getattr(drawing, "_workdir", ""), ignore_errors=True)
    findings = [f for r in results for f in r.findings]
    rules = [{"rule": r.rule, "name": r.name, "status": r.status, "finding_count": len([f for f in r.findings if f.severity not in (Severity.NOT_CHECKED,)]),
              "not_checked_count": len([f for f in r.findings if f.severity == Severity.NOT_CHECKED]), "notes": r.notes} for r in results]
    th = next((r.extra for r in results if r.rule == 8), {})
    sch = [{"type": s.type, "layout": s.layout, "title": s.title, "header": s.header, "bbox": s.bbox,
            "rows": [{"index": r.index, "cells": r.cells, "extra": r.extra} for r in s.rows]} for s in ctx.schedules]
    from dataclasses import asdict
    return CheckResult(drawing.summary(), asdict(profile), rules, findings, th, integrity, sch, time.time() - t0)
