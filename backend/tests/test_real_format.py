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
