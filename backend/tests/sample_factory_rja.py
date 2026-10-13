"""Small replica of a real-world drawing convention: numeric beam tags on layer 'BEAM NO', beams drawn span-by-span as
MLINEs between columns, multi-line schedule headers, one schedule row for several beams ('2, 8, 19.'), slab ids 'S 1.',
column schedule listing only FC columns.  inject: width3 | no12 | s4 | fc16 | nolabel"""
import ezdxf
from ezdxf import units


def T(msp, s, x, y, h, layer, **kw):
    return msp.add_text(s, height=h, dxfattribs={"insert": (x, y), "layer": layer, **kw})


def build(path, inject=frozenset()):
    inj = set(inject)
    doc = ezdxf.new("R2018", setup=True); doc.units = units.MM
    for n in ("BEAM", "BEAM NO", "SLAB", "COL-NO", "TXT MAIN", "SCHEDTXT"):
        doc.layers.add(n)
    msp = doc.modelspace()
    X0, Y0 = 2175000, -200000                    # large coordinates, like real drawings
    def ml(a, b, w): msp.add_mline([(X0 + a[0], Y0 + a[1]), (X0 + b[0], Y0 + b[1])], dxfattribs={"layer": "BEAM", "scale_factor": w, "style_name": "Standard"})
    # beam 1: two spans 230 wide with a 500 mm column gap; beam 2: 150 wide
    ml((0, 0), (4000, 0), 230); ml((4500, 0), (9000, 0), 230)
    ml((0, 4000), (9000, 4000), 150 if False else 150)
    ml((0, 0), (0, 4000), 150 if "width3" in inj else 230)       # beam 3 (schedule: 230)
    ml((0, 12000), (5000, 12000), 150); T(msp, "8", X0 + 2000, Y0 + 12300, 225, "BEAM NO")
    ml((0, 16000), (5000, 16000), 150); T(msp, "19", X0 + 2000, Y0 + 16300, 225, "BEAM NO")
    T(msp, "1", X0 + 2000, Y0 + 300, 225, "BEAM NO")
    T(msp, "2", X0 + 4000, Y0 + 4300, 225, "BEAM NO")
    T(msp, "3", X0 + 350, Y0 + 2000, 225, "BEAM NO")
    if "no12" in inj:
        ml((9000, 0), (9000, 4000), 230); T(msp, "12", X0 + 9350, Y0 + 2000, 225, "BEAM NO")
    if "nolabel" in inj:
        ml((0, 8000), (9000, 8000), 230)
    for i, (n, x, y) in enumerate((("S2", 2000, 2000), ("S3", 6000, 2000), ("S4" if "s4" in inj else "S3", 6000, 3300))):
        T(msp, n, X0 + x, Y0 + y, 200, "SLAB")
    T(msp, "FC6" if "fc16" in inj else "FC16", X0 + 4500, Y0 + 2000, 225, "COL-NO")
    # schedules (multi-line headers)
    SX = X0 + 20000
    T(msp, "SCHEDULE OF BEAMS AT SECOND SLAB LEVEL", SX, Y0 + 800, 300, "TXT MAIN")
    cols = [0, 1500, 3500, 5500]
    for (dx, l1, l2) in zip(cols, ("BEAM", "OVERALL", "BOTTOM", "ANCHOR"), ("NUMBERS", "SIZE ( B x D )", "STEEL STRAIGHT", "BAR AT TOP")):
        T(msp, l1, SX + dx, Y0 + 400, 200, "SCHEDTXT"); T(msp, l2, SX + dx, Y0 + 100, 200, "SCHEDTXT")
    rows = [("1.", "230 X 600", "2-T16", "2-T12"), ("2, 8, 19.", "150 X 300", "2-T12", "2-T10"), ("3.", "230 X 600", "3-T16", "2-T10")]
    y = Y0 - 500
    for r in rows:
        for dx, v in zip(cols, r):
            T(msp, v, SX + dx, y, 200, "SCHEDTXT")
        y -= 550
    T(msp, "SCHEDULE OF SLAB AT SECOND SLAB LEVEL", SX, Y0 - 5000, 300, "TXT MAIN")
    for dx, l1, l2 in ((0, "SLAB", "NOS."), (1500, "THK.", ""), (3000, "MAIN STEEL", "(TOR)")):
        T(msp, l1, SX + dx, Y0 - 5600, 200, "SCHEDTXT")
        if l2: T(msp, l2, SX + dx, Y0 - 5900, 200, "SCHEDTXT")
    y = Y0 - 6500
    for n, thk, st in (("S 2.", "100", "8mm @ 115 C/C"), ("S 3.", "100", "8mm @ 150 C/C")):
        for dx, v in zip((0, 1500, 3000), (n, thk, st)):
            T(msp, v, SX + dx, y, 200, "SCHEDTXT")
        y -= 550
    T(msp, "SCHEDULE OF COLUMNS.", SX + 12000, Y0 - 5000, 300, "TXT MAIN")
    T(msp, "COLUMN  NOS.", SX + 12000, Y0 - 5700, 300, "TXT MAIN"); T(msp, "FC16, FC9.", SX + 16000, Y0 - 5700, 300, "TXT MAIN")
    T(msp, "450 X 150", SX + 16000, Y0 - 6400, 200, "SCHEDTXT"); T(msp, "8-12mm", SX + 16000, Y0 - 6900, 200, "SCHEDTXT")
    T(msp, "PLAN AT SECOND SLAB LEVEL", X0, Y0 - 2500, 300, "TXT MAIN")
    doc.saveas(path); return path
