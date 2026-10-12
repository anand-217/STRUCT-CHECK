"""Builds synthetic RCC drawings (DXF, mm) with a switchable set of intentional errors.
build(path, inject=set()) with an empty set gives a CLEAN drawing that must produce no ERROR/WARNING findings."""
import math
import ezdxf
from ezdxf import units

ALL_ERRORS = {
    "b5_nolabel", "b4_width", "b6_not_in_sched", "b7_in_sched_only", "b10_incomplete", "b12_dup", "pair_width",
    "b11_format", "slab_nolabel", "slab_dup_label", "slab_s4_missing_in_sched", "slab_s5_in_sched_only", "slab_s1_no_thk",
    "title_conflict", "col_dup_label", "col_two_labels", "col_sched_conflict", "beam_label_height", "slab_label_big",
}


def _t(msp, text, x, y, h, layer, **kw):
    return msp.add_text(text, height=h, dxfattribs={"insert": (x, y), "layer": layer, **kw})


def build(path, inject=frozenset()):
    inj = set(inject)
    doc = ezdxf.new("R2018", setup=True)
    doc.units = units.MM
    for name in ("BEAM", "BEAM_TXT", "SLAB", "SLAB_TXT", "COLUMN", "COLUMN_TXT", "SCHEDULE", "NOTES", "TITLE", "DIM"):
        doc.layers.add(name)
    msp = doc.modelspace()

    # block whose raw text height (100) differs from its effective height (100 x 1.5 = 150)
    tag = doc.blocks.new("BEAMTAG")
    tag.add_text("B3", height=100, dxfattribs={"insert": (0, 0)})
    tb = doc.blocks.new("TITLE_BLOCK")
    tb.add_text("PROJECT: DEMO RESIDENCE", height=120, dxfattribs={"insert": (0, 0)})
    tb.add_text("DRG NO: S-101", height=80, dxfattribs={"insert": (0, -300)})
    tb.add_text("SCALE 1:100", height=60, dxfattribs={"insert": (0, -500)})

    # ---- columns ----
    cols = {"C1": (0, 0), "C2": (5000, 0), "C3": (10000, 0), "C4": (0, 4000), "C5": (5000, 4000), "C6": (10000, 4000)}
    for name, (cx, cy) in cols.items():
        msp.add_lwpolyline([(cx - 150, cy - 150), (cx + 150, cy - 150), (cx + 150, cy + 150), (cx - 150, cy + 150)],
                           close=True, dxfattribs={"layer": "COLUMN"})
        label = "C2" if (name == "C6" and "col_dup_label" in inj) else name
        _t(msp, label, cx + 250, cy + 250, 150, "COLUMN_TXT")
    if "col_two_labels" in inj:
        _t(msp, "C8", 5100, 4100, 150, "COLUMN_TXT")       # inside / next to column C5

    # ---- beams (MLINE, boundary representation) ----
    def mline(pts, w):
        msp.add_mline(pts, dxfattribs={"layer": "BEAM", "scale_factor": w, "style_name": "Standard"})

    mline([(0, 0), (10000, 0)], 230);       _t(msp, "B1", 2500, 300, 150, "BEAM_TXT")
    mline([(0, 4000), (10000, 4000)], 230)
    _t(msp, "B2", 2500, 4300, 100 if "beam_label_height" in inj else 150, "BEAM_TXT")
    mline([(0, 0), (0, 4000)], 230)
    msp.add_blockref("BEAMTAG", (350, 2000), dxfattribs={"xscale": 1.5, "yscale": 1.5, "layer": "BEAM_TXT"})
    mline([(5000, 0), (5000, 4000)], 150 if "b4_width" in inj else 230);  _t(msp, "B4", 5350, 2000, 150, "BEAM_TXT")
    mline([(10000, 0), (10000, 4000)], 230)
    if "b5_nolabel" not in inj:
        _t(msp, "B5", 10350, 2000, 150, "BEAM_TXT")
    mline([(0, 8000), (10000, 8000)], 230); _t(msp, "B6", 2500, 8300, 150, "BEAM_TXT")
    # rotated MLINE, 30 degrees, width 200 -> a bounding-box approach would get this wrong
    a = math.radians(30)
    p0, p1 = (12000, 8000), (12000 + 4000 * math.cos(a), 8000 + 4000 * math.sin(a))
    mline([p0, p1], 200)
    mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    _t(msp, "B8", mid[0] - 150 - 150, mid[1] + 260, 150, "BEAM_TXT")
    # beam drawn as two parallel LINEs
    gap = 300 if "pair_width" in inj else 230
    msp.add_line((0, 12000), (6000, 12000), dxfattribs={"layer": "BEAM"})
    msp.add_line((0, 12000 + gap), (6000, 12000 + gap), dxfattribs={"layer": "BEAM"})
    _t(msp, "B9", 3000, 12700, 150, "BEAM_TXT")
    mline([(0, 16000), (6000, 16000)], 230)
    _t(msp, "B-11" if "b11_format" in inj else "B11", 3000, 16300, 150, "BEAM_TXT")

    # ---- slabs ----
    panels = {"P1": (150, 150, 4850, 3850), "P2": (5150, 150, 9850, 3850), "P3": (150, 4150, 4850, 7850), "P4": (5150, 4150, 9850, 7850)}
    for n, (x0, y0, x1, y1) in panels.items():
        msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "SLAB"})
    _t(msp, "S1", 2400, 2000, 180, "SLAB_TXT")
    _t(msp, "S2", 7400, 2000, 180, "SLAB_TXT")
    if "slab_dup_label" in inj:
        _t(msp, "S2", 7400, 3000, 180, "SLAB_TXT")
    if "slab_nolabel" not in inj:
        _t(msp, "S3", 2400, 6000, 180, "SLAB_TXT")
    _t(msp, "S4", 7400, 6000, 250 if "slab_label_big" in inj else 180, "SLAB_TXT")

    # ---- schedules ----
    def table(x, y, title, headers, xs, rows, pitch=400):
        _t(msp, title, x, y + 800, 200, "SCHEDULE")
        for hx, h in zip(xs, headers):
            _t(msp, h, x + hx, y, 180, "SCHEDULE")
        for i, row in enumerate(rows, start=1):
            for hx, v in zip(xs, row):
                if v is not None:
                    _t(msp, v, x + hx, y - pitch * i, 150, "SCHEDULE")

    lvl = "FIRST"
    bs = [("B1", "230", "450"), ("B2", "230", "450"), ("B3", "230", "450"), ("B4", "230", "450"), ("B5", "230", "450"),
          ("B8", "200", "450"), ("B9", "230", "450"), ("B11", "230", "450")]
    if "b6_not_in_sched" not in inj:
        bs.insert(5, ("B6", "230", "450"))
    rows = [(i, w, d, "2-16T", "3-16T", "8T@150") for i, w, d in bs]
    if "b7_in_sched_only" in inj:
        rows.append(("B7", "230", "450", "2-16T", "3-16T", "8T@150"))
    if "b10_incomplete" in inj:
        rows.append(("B10", "230", "-", "2-16T", "3-16T", None))
    if "b12_dup" in inj:
        rows.append(("B12", "230", "450", "2-16T", "3-16T", "8T@150"))
        rows.append(("B12", "300", "600", "3-20T", "4-20T", "8T@125"))
    table(22000, 20000, f"BEAM SCHEDULE AT {lvl} SLAB LEVEL", ["BEAM NO", "WIDTH", "DEPTH", "TOP", "BOTTOM", "STIRRUPS"],
          [0, 1500, 3000, 4500, 7000, 9500], rows)

    srows = [("S1", None if "slab_s1_no_thk" in inj else "125", "10T@150", "8T@200"), ("S2", "125", "10T@150", "8T@200"),
             ("S3", "150", "10T@125", "8T@200")]
    if "slab_s4_missing_in_sched" not in inj:
        srows.append(("S4", "125", "10T@150", "8T@200"))
    if "slab_s5_in_sched_only" in inj:
        srows.append(("S5", "125", "10T@150", "8T@200"))
    table(22000, 10000, f"SLAB SCHEDULE AT {lvl} SLAB LEVEL", ["SLAB NO", "THICKNESS", "MAIN", "DIST"], [0, 1800, 3800, 6000], srows)

    crow = [(k, "300x300", "8-16T", "8T@150") for k in cols]
    if "col_sched_conflict" in inj:
        crow.append(("C2", "300x450", "8-20T", "8T@150"))
    table(22000, 4000, f"COLUMN SCHEDULE AT {lvl} SLAB LEVEL", ["COLUMN NO", "SIZE", "MAIN", "TIES"], [0, 2200, 4200, 6200], crow)

    # ---- titles, notes, title block ----
    _t(msp, f"RCC DETAILS OF {lvl} SLAB LEVEL", 0, -3000, 400, "TITLE")
    _t(msp, f"LAYOUT AT {'SECOND' if 'title_conflict' in inj else lvl} SLAB LEVEL", 0, -2000, 300, "TITLE")
    _t(msp, "NOTES:", 0, -6000, 100, "NOTES")
    _t(msp, "1. ALL DIMENSIONS ARE IN MM UNLESS NOTED OTHERWISE.", 0, -6300, 120, "NOTES")
    _t(msp, "2. CONCRETE GRADE M25 AND STEEL Fe500D.", 0, -6600, 90, "NOTES")
    msp.add_blockref("TITLE_BLOCK", (0, -9000), dxfattribs={"layer": "TITLE"})
    doc.saveas(path)
    return path
