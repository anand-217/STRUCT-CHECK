import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from sample_factory_rja import build
from structcheck.engine import run_checks
from structcheck.loader import load_drawing
from structcheck.context import Context
from structcheck.profile import ProjectProfile
from structcheck.findings import Severity


def go(tmp_path, inj=(), only=None):
    f = str(tmp_path / "r.dxf"); build(f, set(inj))
    return f, run_checks(f, ProjectProfile(), only)


def test_multiline_headers_id_lists_and_slab_ids_are_read(tmp_path):
    f, _ = go(tmp_path)
    p = ProjectProfile(); c = Context(load_drawing(f, p), p)
    beam = c.sched("beam")[0]
    assert {"id", "size", "bottom", "top_anchor"} <= set(beam.header)
    ids = [r.cells["id"] for r in beam.rows]
    assert ids == ["1", "2", "8", "19", "3"]                 # '2, 8, 19.' expanded into three beams
    assert [r.cells["width"] for r in beam.rows][1:4] == ["150"] * 3
    assert [r.cells["id"] for r in c.sched("slab")[0].rows] == ["S2", "S3"]   # 'S 2.' normalised
    assert [r.cells["id"] for r in c.sched("column")[0].rows] == ["FC16", "FC9"]

def test_clean_real_format_has_no_errors(tmp_path):
    _, res = go(tmp_path, only=[1, 2, 3, 5])
    assert not [f for f in res.findings if f.severity in (Severity.ERROR, Severity.WARNING)], [f.description for f in res.findings]

def test_span_by_span_beam_is_one_run_needing_one_label(tmp_path):
    _, res = go(tmp_path, only=[1])
    assert not [f for f in res.findings if f.sub_check == "instance without label"]

def test_numeric_label_width_mismatch(tmp_path):
    _, res = go(tmp_path, ["width3"], [2])
    assert [f for f in res.findings if f.identifier == "3" and f.difference.startswith("-80")]

def test_plan_beam_not_in_schedule_numeric(tmp_path):
    _, res = go(tmp_path, ["no12"], [3])
    assert [f for f in res.findings if f.sub_check == "A not in schedule" and f.identifier == "12"]

def test_unlabelled_beam_run(tmp_path):
    _, res = go(tmp_path, ["nolabel"], [1])
    assert [f for f in res.findings if f.sub_check == "instance without label"]

def test_slab_plan_id_missing_in_schedule(tmp_path):
    _, res = go(tmp_path, ["s4"], [4])
    assert [f for f in res.findings if f.sub_check.startswith("B plan not in schedule") and f.identifier == "S4"]

def test_column_typo_hint(tmp_path):
    _, res = go(tmp_path, ["fc16"], [7])
    f = [x for x in res.findings if x.sub_check.startswith("G")][0]
    assert "FC16" in f.explanation


def _network(path, label_right=True):
    import ezdxf
    from ezdxf import units
    doc = ezdxf.new("R2018", setup=True); doc.units = units.MM
    msp = doc.modelspace()
    for a, b in (((0, 0), (8000, 0)), ((8000, 0), (8000, 4000)), ((8000, 4000), (0, 4000)), ((0, 4000), (0, 0)), ((4000, 0), (4000, 4000))):
        msp.add_mline([a, b], dxfattribs={"layer": "BEAM", "scale_factor": 230, "style_name": "Standard"})
    for x, n in ((2000, "S1"), (6000, "S2" if label_right else None)):
        if n:
            msp.add_text(n, height=200, dxfattribs={"insert": (x, 2000), "layer": "SLAB"})
    for dx, t in ((0, "SLAB NOS."), (1500, "THK.")):
        msp.add_text(t, height=200, dxfattribs={"insert": (20000 + dx, 0)})
    msp.add_text("SCHEDULE OF SLAB AT FIRST SLAB LEVEL", height=300, dxfattribs={"insert": (20000, 800), "layer": "TXT"})
    for i, (n, t) in enumerate((("S 1.", "100"), ("S 2.", "125")), start=1):
        msp.add_text(n, height=200, dxfattribs={"insert": (20000, -600 * i)}); msp.add_text(t, height=200, dxfattribs={"insert": (21500, -600 * i)})
    doc.saveas(path)


def test_slab_panels_inferred_from_beam_network(tmp_path):
    f = str(tmp_path / "n.dxf"); _network(f)
    res = run_checks(f, ProjectProfile(), [4])
    assert any("INFERRED" in n for n in res.rules[0]["notes"]) and "2 panels" in " ".join(res.rules[0]["notes"])
    assert not [x for x in res.findings if x.severity in (Severity.ERROR, Severity.WARNING)]

def test_inferred_panel_without_label_is_review_not_error(tmp_path):
    f = str(tmp_path / "n2.dxf"); _network(f, label_right=False)
    res = run_checks(f, ProjectProfile(), [4])
    c = [x for x in res.findings if x.sub_check.startswith("C panel")]
    assert c and all(x.severity == Severity.REVIEW for x in c)


def test_marked_dxf_is_a_copy_with_circles(tmp_path):
    import hashlib, ezdxf
    from structcheck import review
    src = str(tmp_path / "s.dxf")
    from sample_factory import build, ALL_ERRORS
    build(src, ALL_ERRORS)
    before = hashlib.sha256(open(src, "rb").read()).hexdigest()
    res = run_checks(src, ProjectProfile(column_id_mode="unique"))
    out = str(tmp_path / "s_REVIEW.dxf")
    n, skipped = review.mark_dxf(src, res.findings, out)
    assert n >= 20 and hashlib.sha256(open(src, "rb").read()).hexdigest() == before
    d = ezdxf.readfile(out)
    kinds = [e.dxftype() for e in d.modelspace() if e.dxf.layer == review.REVIEW_LAYER]
    assert kinds.count("CIRCLE") >= 20 and "TEXT" in kinds
    src_layers = {e.dxf.layer for e in ezdxf.readfile(src).modelspace()}
    assert review.REVIEW_LAYER not in src_layers          # original has no review layer

def test_marking_refuses_to_overwrite_source(tmp_path):
    import pytest
    from structcheck import review
    src = str(tmp_path / "s.dxf")
    from sample_factory import build
    build(src)
    with pytest.raises(ValueError):
        review.mark_dxf(src, [], src)

def test_marked_pdf_written(tmp_path):
    import pytest
    pytest.importorskip("matplotlib")
    from structcheck import review
    from sample_factory import build, ALL_ERRORS
    src = str(tmp_path / "s.dxf"); build(src, ALL_ERRORS)
    res = run_checks(src, ProjectProfile(column_id_mode="unique"))
    d = str(tmp_path / "m.dxf"); review.mark_dxf(src, res.findings, d)
    pdf = str(tmp_path / "m.pdf"); n, _ = review.mark_pdf(d, res.findings, pdf, detail_pages=3)
    assert n >= 20 and open(pdf, "rb").read(4) == b"%PDF"
