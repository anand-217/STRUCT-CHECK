"""Review copies with findings marked by circles. The ORIGINAL drawing is never written to: marks go into a new
DXF copy (layer STRUCTCHECK_REVIEW) and/or a PDF."""
from __future__ import annotations
import math, os
import ezdxf

REVIEW_LAYER = "STRUCTCHECK_REVIEW"
ACI = {"ERROR": 1, "WARNING": 30, "REVIEW": 40}          # red, orange, amber
HEX = {"ERROR": "#D92D20", "WARNING": "#F58220", "REVIEW": "#E8A317"}
MARKABLE = ("ERROR", "WARNING", "REVIEW")


def _shape(f, unit_mm):
    """(cx, cy, a, b) = centre and half-axes in drawing units, or None when the finding has no reliable location."""
    if not f.bbox or (f.layout or "Model").lower() != "model":
        return None
    x0, y0, x1, y1 = f.bbox
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rmin = 450.0 / unit_mm
    if max(w, h) > 2.2 * min(max(w, h), max(min(w, h), 1e-9)) and max(w, h) > 4 * rmin:     # wide strip -> ellipse
        a, b = max(w, h) / 2 * 1.12 + rmin, max(min(w, h) / 2 * 1.4, rmin)
        if h > w:
            a, b = b, a
        return cx, cy, a, b
    r = max(math.hypot(w, h) / 2 * 1.25, rmin)
    return cx, cy, r, r


def _boxes_for(f, doc):
    """Individual extents of the entities a finding refers to, merged into clusters (so a finding spread over the
    sheet gets one circle per place, not one giant circle)."""
    from ezdxf import bbox as ebbox
    boxes = []
    for h in dict.fromkeys(f.entity_handles):
        try:
            e = doc.entitydb.get(h)
            if e is None:
                continue
            ext = ebbox.extents([e], fast=True)
            if ext.has_data:
                boxes.append([ext.extmin.x, ext.extmin.y, ext.extmax.x, ext.extmax.y])
        except Exception:
            continue
    merged = True
    while merged and len(boxes) > 1:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                gap = max(max(a[0], b[0]) - min(a[2], b[2]), max(a[1], b[1]) - min(a[3], b[3]))
                if gap < 2500:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]; merged = True; break
            if merged:
                break
    return boxes


def _marks(f, doc, unit_mm):
    one = _shape(f, unit_mm)
    if not one:
        return []
    x0, y0, x1, y1 = f.bbox
    if math.hypot(x1 - x0, y1 - y0) * unit_mm > 3000 and len(f.entity_handles) > 1:
        boxes = _boxes_for(f, doc)
        if 1 < len(boxes) <= 8:
            from types import SimpleNamespace as NS
            return [_shape(NS(bbox=tuple(bx), layout="Model"), unit_mm) for bx in boxes]
    return [one]


def collect_marks(doc, findings, unit_mm: float = 1.0, severities=MARKABLE):
    """List of mark dicts (drawing units) + ids of findings that have no reliable location."""
    marks, skipped = [], []
    for f in findings:
        sev = f.severity.value
        if sev not in severities:
            continue
        shapes = _marks(f, doc, unit_mm)
        if not shapes:
            skipped.append(f.id)
            continue
        for cx, cy, a, b in shapes:
            th = min(320.0 / unit_mm, max(min(a, b) * 0.5, 120.0 / unit_mm))
            marks.append({"id": f.id, "severity": sev, "cx": cx, "cy": cy, "a": a, "b": b, "height": th,
                          "desc": f.description.replace("\t", " ").replace("\n", " ")})
    return marks, skipped


def mark_dxf(src: str, findings, out: str, unit_mm: float = 1.0, severities=MARKABLE):
    """Write a COPY of src with red/orange/amber circles. Returns (marked, skipped_ids)."""
    if os.path.abspath(src) == os.path.abspath(out):
        raise ValueError("Refusing to overwrite the source drawing; choose a different output file.")
    doc = ezdxf.readfile(src)
    if REVIEW_LAYER not in doc.layers:
        doc.layers.add(REVIEW_LAYER, color=1)
    msp = doc.modelspace()
    marks, skipped = collect_marks(doc, findings, unit_mm, severities)
    for m in marks:
        cx, cy, a, b, sev = m["cx"], m["cy"], m["a"], m["b"], m["severity"]
        attr = {"layer": REVIEW_LAYER, "color": ACI[sev], "lineweight": 50}
        if abs(a - b) < 1e-6:
            msp.add_circle((cx, cy), a, dxfattribs=attr)
            msp.add_circle((cx, cy), a * 1.04, dxfattribs=attr)           # double ring: easy to see when zoomed out
        else:
            major = (a, 0, 0) if a >= b else (0, b, 0)
            ratio = (b / a) if a >= b else (a / b)
            msp.add_ellipse((cx, cy), major_axis=major, ratio=max(min(ratio, 1.0), 0.01), dxfattribs=attr)
        t = msp.add_text(m["id"], height=m["height"], dxfattribs={"layer": REVIEW_LAYER, "color": ACI[sev]})
        t.set_placement((cx + max(a, b) * 1.08, cy + max(a, b) * 0.4))
    doc.saveas(out)
    return len(marks), skipped


def write_marks_tsv(src: str, findings, out_tsv: str, unit_mm: float = 1.0, severities=MARKABLE):
    """Tab-separated marks for the AutoLISP add-on (it draws them straight into the open drawing)."""
    doc = ezdxf.readfile(src)
    marks, skipped = collect_marks(doc, findings, unit_mm, severities)
    with open(out_tsv, "w", encoding="utf-8", newline="") as f:
        for m in marks:
            kind = "CIRCLE" if abs(m["a"] - m["b"]) < 1e-6 else ("ELLIPSE_X" if m["a"] > m["b"] else "ELLIPSE_Y")
            f.write("\t".join([m["id"], m["severity"], kind, f"{m['cx']:.4f}", f"{m['cy']:.4f}", f"{m['a']:.4f}",
                               f"{m['b']:.4f}", f"{m['height']:.4f}", m["desc"]]) + "\n")
    return len(marks), skipped


def mark_pdf(review_dxf: str, findings, out_pdf: str, unit_mm: float = 1.0, detail_pages: int = 40, severities=MARKABLE):
    """PDF: page 1 = whole drawing with circles; then one zoomed page per marked finding (up to detail_pages)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    doc = ezdxf.readfile(review_dxf)
    fig = plt.figure(figsize=(16.5, 11.7))                       # A3 landscape
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.92])
    cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR)
    Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    ax.set_aspect("equal")
    full = (ax.get_xlim(), ax.get_ylim())
    pages = [f for f in findings if f.severity.value in severities and _shape(f, unit_mm)]
    with PdfPages(out_pdf) as pdf:
        # overview: zoom to the area that contains findings (the full sheet is usually mostly empty)
        if pages:
            xs = [v for f in pages for v in (f.bbox[0], f.bbox[2])]; ys = [v for f in pages for v in (f.bbox[1], f.bbox[3])]
            padx, pady = (max(xs) - min(xs)) * 0.06 + 1500, (max(ys) - min(ys)) * 0.06 + 1500
            ax.set_xlim(min(xs) - padx, max(xs) + padx); ax.set_ylim(min(ys) - pady, max(ys) + pady)
        fig.suptitle(f"StructCheck review - {os.path.basename(review_dxf)}  ({len(pages)} marked findings)\n"
                     "red = ERROR    orange = WARNING    amber = REVIEW", fontsize=9)
        fig.text(0.5, 0.005, "StructCheck assists drawing QC and does not replace professional engineering review. Original drawing unchanged.",
                 ha="center", fontsize=7, color="#6B7280")
        pdf.savefig(fig)
        import io
        for f in pages[:detail_pages]:             # detail pages are raster snapshots so the PDF stays small
            cx, cy, a, b = _shape(f, unit_mm)
            half = max(max(a, b) * 3.5, 3500.0 / unit_mm)
            ax.set_xlim(cx - half * 1.4, cx + half * 1.4); ax.set_ylim(cy - half, cy + half)
            fig.suptitle(f"{f.id} [{f.severity.value}] {f.description}\n"
                         f"expected {f.expected}  detected {f.detected}  {f.difference or ''}", fontsize=10, color=HEX[f.severity.value])
            buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=110); buf.seek(0)
            img = plt.imread(buf)
            pf = plt.figure(figsize=(16.5, 11.7)); pa = pf.add_axes([0, 0, 1, 1]); pa.imshow(img); pa.axis("off")
            pdf.savefig(pf); plt.close(pf)
    plt.close(fig)
    return len(pages), max(0, len(pages) - detail_pages)
