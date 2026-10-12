import hashlib, os, sys
import ezdxf
import pytest
from ezdxf import units

sys.path.insert(0, os.path.dirname(__file__))
from sample_factory import build, ALL_ERRORS
from structcheck.engine import run_checks
from structcheck.profile import ProjectProfile
from structcheck.findings import Severity


def prof(**kw):
    p = ProjectProfile(column_id_mode="unique")
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def run(tmp_path, inject=(), profile=None, only=None):
    f = str(tmp_path / "t.dxf")
    build(f, set(inject))
    return run_checks(f, profile or prof(), only)


def has(res, rule, sub=None, text=None, sev=None):
    for f in res.findings:
        if f.rule != rule:
            continue
        if sub and sub.lower() not in f.sub_check.lower():
            continue
        if text and text.lower() not in (f.description + f.explanation + str(f.identifier)).lower():
            continue
        if sev and f.severity != sev:
            continue
        return True
    return False


# ---- false-positive control / baseline -------------------------------------------------
def test_clean_drawing_has_no_findings(tmp_path):
    res = run(tmp_path)
    assert [f.description for f in res.findings] == []
    assert all(r["status"] == "COMPLETED" for r in res.rules)
    assert len(res.rules) == 8


# ---- Rule 1 ----------------------------------------------------------------------------
def test_r1_beam_without_label(tmp_path):
    assert has(run(tmp_path, ["b5_nolabel"]), 1, "instance without label")

def test_r1_schedule_beam_not_in_plan(tmp_path):
    assert has(run(tmp_path, ["b7_in_sched_only"]), 1, "type not in plan", "B7")

def test_r1_repeated_beam_label_is_not_an_error(tmp_path):
    # B-types may occur many times: clean drawing has B3 tag via block + others; no instance finding
    assert not has(run(tmp_path), 1)


# ---- Rule 2 ----------------------------------------------------------------------------
def test_r2_width_mismatch_mline(tmp_path):
    res = run(tmp_path, ["b4_width"])
    f = [f for f in res.findings if f.rule == 2][0]
    assert f.identifier == "B4" and f.severity == Severity.ERROR
    assert f.expected == "230 mm" and f.detected == "150 mm" and f.difference.startswith("-80")

def test_r2_line_pair_mismatch(tmp_path):
    assert has(run(tmp_path, ["pair_width"]), 2, text="B9")

def test_r2_rotated_mline_not_flagged(tmp_path):
    # B8 is a 30-degree MLINE; a bounding-box width would be wrong. Must pass at 200 mm.
    assert not has(run(tmp_path), 2, text="B8")


# ---- Rule 3 ----------------------------------------------------------------------------
def test_r3_plan_beam_not_in_schedule(tmp_path):
    assert has(run(tmp_path, ["b6_not_in_sched"]), 3, "A not in schedule", "B6", Severity.ERROR)

def test_r3_missing_design_data(tmp_path):
    res = run(tmp_path, ["b10_incomplete"])
    assert has(res, 3, "B dimensions", "depth") and has(res, 3, "C reinforcement", "stirrups")

def test_r3_format_difference_is_review_not_merged(tmp_path):
    res = run(tmp_path, ["b11_format"])
    assert has(res, 3, "E identifier", sev=Severity.REVIEW)
    assert not has(res, 3, "A not in schedule", "B-11")

def test_r3_format_difference_merged_only_when_profile_allows(tmp_path):
    res = run(tmp_path, ["b11_format"], prof(hyphen_equivalent=True))
    assert not has(res, 3, "E identifier") and not has(res, 3, "A not in schedule")


# ---- Rule 4 ----------------------------------------------------------------------------
def test_r4_variants(tmp_path):
    res = run(tmp_path, ["slab_nolabel", "slab_dup_label", "slab_s4_missing_in_sched", "slab_s5_in_sched_only", "slab_s1_no_thk"])
    assert has(res, 4, "C panel without label")
    assert has(res, 4, "D multiple labels")
    assert has(res, 4, "B plan not in schedule", "S4")
    assert has(res, 4, "A schedule not in plan", "S5")
    assert has(res, 4, "F required", "S1")

def test_r4_repeated_slab_type_is_legit(tmp_path):
    # same slab type in several panels must not be reported (single type label repeated)
    res = run(tmp_path)
    assert not has(res, 4)


# ---- Rule 5 ----------------------------------------------------------------------------
def test_r5_duplicate_conflicting(tmp_path):
    res = run(tmp_path, ["b12_dup"])
    f = [f for f in res.findings if f.rule == 5][0]
    assert f.severity == Severity.ERROR and "CONFLICTING" in f.explanation and "B12" in f.description

def test_r5_repeated_plan_labels_not_flagged(tmp_path):
    assert not has(run(tmp_path, ["slab_dup_label"]), 5)


# ---- Rule 6 ----------------------------------------------------------------------------
def test_r6_floor_level_conflict(tmp_path):
    res = run(tmp_path, ["title_conflict"])
    assert has(res, 6, sev=Severity.WARNING)

def test_r6_different_title_types_do_not_conflict(tmp_path):
    # BEAM SCHEDULE / SLAB SCHEDULE / LAYOUT / DETAILS all carry different wording; clean file has none flagged
    assert not has(run(tmp_path), 6)

def test_r6_multi_floor_model_space_is_review(tmp_path):
    res = run(tmp_path, ["title_conflict"], prof(single_floor_per_drawing=False))
    assert has(res, 6, sev=Severity.REVIEW)


# ---- Rule 7 ----------------------------------------------------------------------------
def test_r7_duplicate_unique_mode_is_error(tmp_path):
    assert has(run(tmp_path, ["col_dup_label"]), 7, "A same id", "C2", Severity.ERROR)

def test_r7_repeated_types_not_flagged_in_types_mode(tmp_path):
    res = run(tmp_path, ["col_dup_label"], prof(column_id_mode="types"))
    assert not has(res, 7, "A same id")

def test_r7_unknown_convention_is_review(tmp_path):
    res = run(tmp_path, ["col_dup_label"], prof(column_id_mode="unknown"))
    assert has(res, 7, "A same id", sev=Severity.REVIEW) and not has(res, 7, "A same id", sev=Severity.ERROR)

def test_r7_schedule_conflict(tmp_path):
    assert has(run(tmp_path, ["col_sched_conflict"]), 7, "E conflicting", "C2", Severity.ERROR)

def test_r7_two_labels_one_column(tmp_path):
    res = run(tmp_path, ["col_two_labels"])
    assert has(res, 7, "B several") or has(res, 7, "C labels overlap")


# ---- Rule 8 ----------------------------------------------------------------------------
def test_r8_inferred_outlier_is_warning(tmp_path):
    res = run(tmp_path, ["beam_label_height"])
    f = [f for f in res.findings if f.rule == 8][0]
    assert f.severity == Severity.WARNING and f.identifier == "B2" and "inferred" in f.expected
    assert f.detected == "100" and f.difference == "-50"

def test_r8_configured_standard_is_error(tmp_path):
    res = run(tmp_path, ["slab_label_big"], prof(text_categories_standard={"Slab numbers": 180.0}))
    f = [f for f in res.findings if f.rule == 8][0]
    assert f.severity == Severity.ERROR and "configured" in f.expected

def test_r8_notes_and_titleblock_excluded_by_default(tmp_path):
    res = run(tmp_path)
    rows = res.text_height_analysis["analysis"]
    notes = [r for r in rows if r["text"].startswith(("NOTES", "1. ALL", "2. CONCRETE"))]
    tb = [r for r in rows if r["text"].startswith(("PROJECT:", "DRG NO", "SCALE"))]
    titles = [r for r in rows if r["text"].startswith(("RCC DETAILS", "LAYOUT AT"))]
    assert notes and tb and titles
    assert all(not r["included"] and r["exclusion_reason"] for r in notes + tb + titles)

def test_r8_equivalent_effective_heights_not_flagged(tmp_path):
    res = run(tmp_path)
    b3 = [r for r in res.text_height_analysis["analysis"] if r["text"] == "B3"][0]
    assert b3["raw_height"] == 100 and b3["effective_height"] == 150 and b3["included"]
    assert not has(res, 8)

def test_r8_minority_height_not_error_without_configured_standard(tmp_path):
    res = run(tmp_path, ["beam_label_height"])
    assert not has(res, 8, sev=Severity.ERROR)

def test_r8_engineer_exclusion_by_layer(tmp_path):
    res = run(tmp_path, ["beam_label_height"], prof(exclude_text_layers=["BEAM_TXT"]))
    assert not has(res, 8)

def test_r8_never_modifies_text_and_reports_distribution(tmp_path):
    res = run(tmp_path, ["beam_label_height"])
    assert "Beam numbers [Model]" in res.text_height_analysis["distribution"]


# ---- units, unsupported entities, unrecognised schedules, integrity ------------------------
def mini(path, ins, k, width_mm=230, with_schedule=True, add_image=False):
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = ins
    msp = doc.modelspace()
    msp.add_mline([(0, 0), (5000 * k, 0)], dxfattribs={"scale_factor": width_mm * k, "layer": "BEAM"})
    msp.add_text("B1", height=150 * k, dxfattribs={"insert": (2000 * k, 300 * k), "layer": "BEAM_TXT"})
    if with_schedule:
        for x, h in ((8000, "BEAM NO"), (9500, "WIDTH"), (11000, "DEPTH")):
            msp.add_text(h, height=150 * k, dxfattribs={"insert": (x * k, 2000 * k)})
        for x, v in ((8000, "B1"), (9500, "230"), (11000, "450")):
            msp.add_text(v, height=150 * k, dxfattribs={"insert": (x * k, 1600 * k)})
    if add_image:
        idef = doc.add_image_def("x.png", size_in_pixel=(10, 10))
        msp.add_image(idef, (0, -5000 * k), size_in_units=(100 * k, 100 * k))
    doc.saveas(path)

@pytest.mark.parametrize("ins,k", [(4, 1.0), (5, 0.1), (6, 0.001)])
def test_units_mm_cm_m(tmp_path, ins, k):
    f = str(tmp_path / "m.dxf"); mini(f, ins, k)
    assert not run_checks(f, ProjectProfile(), [1, 2]).findings
    f2 = str(tmp_path / "m2.dxf"); mini(f2, ins, k, width_mm=300)
    res = run_checks(f2, ProjectProfile(), [2])
    assert res.findings and res.findings[0].difference.startswith("+70")

def test_unsupported_entity_is_reported_not_ignored(tmp_path):
    f = str(tmp_path / "u.dxf"); mini(f, 4, 1.0, add_image=True)
    res = run_checks(f, ProjectProfile(), [1])
    assert res.drawing["unsupported_entities"].get("IMAGE") == 1
    assert any("IMAGE" in n for r in res.rules for n in r["notes"])

def test_unrecognised_schedule_is_not_checked_not_passed(tmp_path):
    f = str(tmp_path / "n.dxf"); mini(f, 4, 1.0, with_schedule=False)
    res = run_checks(f, ProjectProfile())
    for r in res.rules:
        if r["rule"] in (1, 2, 3, 4, 5):
            assert r["status"] == "SKIPPED"
    assert res.summary()["not_checked_items"] >= 5
    # rules that depend on the unrecognised schedules must never count as passed
    assert all(not (r["status"] == "COMPLETED" and r["finding_count"] == 0) for r in res.rules if r["rule"] in (1, 2, 3, 4, 5))

def test_source_file_integrity(tmp_path):
    f = str(tmp_path / "i.dxf"); build(f, ALL_ERRORS)
    before = hashlib.sha256(open(f, "rb").read()).hexdigest()
    mtime = os.path.getmtime(f)
    res = run_checks(f, prof())
    assert res.integrity["unchanged"] and res.integrity["sha256_before"] == before
    assert hashlib.sha256(open(f, "rb").read()).hexdigest() == before and os.path.getmtime(f) == mtime

def test_viewport_scales_make_model_text_height_review(tmp_path):
    f = str(tmp_path / "v.dxf"); build(f)
    doc = ezdxf.readfile(f)
    lay = doc.layouts.new("Sheet1")
    lay.add_viewport(center=(100, 100), size=(100, 100), view_center_point=(5000, 2000), view_height=5000)
    lay.add_viewport(center=(250, 100), size=(100, 100), view_center_point=(5000, 2000), view_height=10000)
    doc.saveas(f)
    res = run_checks(f, prof(), [8])
    assert any(x.sub_check == "effective height uncertain" for x in res.findings)
    assert res.rules[0]["status"] == "PARTIAL"
    assert not any(x.severity == Severity.ERROR for x in res.findings)

def test_findings_have_required_fields(tmp_path):
    res = run(tmp_path, ALL_ERRORS)
    d = res.to_dict()
    assert "does not replace professional engineering review" in d["disclaimer"]
    for f in d["findings"]:
        for k in ("id", "rule", "severity", "description", "reason", "confidence", "review_status", "entity_handles", "recommended_action"):
            assert k in f
    ids = [f["id"] for f in d["findings"]]
    assert len(ids) == len(set(ids))

def test_exports(tmp_path):
    from structcheck import export
    res = run(tmp_path, ALL_ERRORS)
    for fmt in ("json", "csv", "xlsx"):
        p = tmp_path / f"r.{fmt}"
        getattr(export, "to_" + fmt)(res, str(p))
        assert p.stat().st_size > 500
