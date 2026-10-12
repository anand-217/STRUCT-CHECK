"""DXF ingestion. The original file is never opened for writing; a working copy is parsed."""
from __future__ import annotations
import hashlib, math, os, re, shutil, tempfile
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import ezdxf
from ezdxf import recover

from .profile import ProjectProfile

INSUNITS_TO_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 3: 1609344.0, 7: 1e6, 8: 0.0000254, 9: 0.0254, 10: 914.4}
UNIT_NAME_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}
UNSUPPORTED_TYPES = {"IMAGE", "ACAD_PROXY_ENTITY", "OLE2FRAME", "PDFUNDERLAY", "DGNUNDERLAY", "DWFUNDERLAY",
                     "3DSOLID", "BODY", "REGION", "SURFACE", "LIGHT"}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class TextItem:
    handle: str
    kind: str                 # TEXT MTEXT ATTRIB ATTDEF DIMENSION MLEADER
    text: str
    x: float
    y: float
    raw_height: float
    eff_height: float
    layer: str
    style: str
    layout: str
    is_model: bool
    rotation: float = 0.0
    block_path: tuple = ()
    top_handle: str = ""
    height_certain: bool = True
    height_note: str = ""
    nlines: int = 1

    @property
    def bbox(self):
        w = max(1, len(self.text.split("\n")[0])) * self.eff_height * 0.75
        return (self.x, self.y, self.x + w, self.y + self.eff_height * max(1, self.nlines))


@dataclass
class LineItem:
    handle: str; layer: str; layout: str; p1: tuple; p2: tuple


@dataclass
class PolyItem:
    handle: str; layer: str; layout: str; pts: list; closed: bool


@dataclass
class MLineItem:
    handle: str; layer: str; layout: str; pts: list
    width_du: float; n_elements: int; scale: float; style: str; closed: bool = False


@dataclass
class InsertItem:
    handle: str; layer: str; layout: str; name: str; x: float; y: float; xscale: float; yscale: float


@dataclass
class Drawing:
    path: str
    filename: str
    size_bytes: int
    sha256: str
    unit_mm: float                  # drawing unit expressed in millimetres
    unit_source: str
    layouts: list
    layers: list
    texts: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    polys: list = field(default_factory=list)
    mlines: list = field(default_factory=list)
    inserts: list = field(default_factory=list)
    entity_counts: dict = field(default_factory=dict)
    unsupported: dict = field(default_factory=dict)       # type -> count
    limitations: list = field(default_factory=list)
    viewport_scales: list = field(default_factory=list)
    model_text_scale_ambiguous: bool = False
    dxf_version: str = ""

    def summary(self):
        return {"filename": self.filename, "size_bytes": self.size_bytes, "sha256": self.sha256,
                "unit_mm_per_drawing_unit": self.unit_mm, "unit_source": self.unit_source,
                "layouts": self.layouts, "layer_count": len(self.layers),
                "entity_counts": self.entity_counts, "unsupported_entities": self.unsupported,
                "limitations": self.limitations, "dxf_version": self.dxf_version}


_H_OVERRIDE = re.compile(r"\\H(\d+(?:\.\d+)?)(x?);")


def _mtext_height(e):
    base = float(e.dxf.get("char_height", 0) or 0)
    ov = _H_OVERRIDE.findall(e.text or "")
    if not ov:
        return base, base, True, ""
    vals = {round(float(v) * (base if x else 1.0), 4) for v, x in ov}
    if len(vals) == 1:
        return base, vals.pop(), True, "MTEXT \\H override applied"
    return base, base, False, "MTEXT has several \\H overrides - mixed heights in one entity"


class _Loader:
    def __init__(self, doc, drawing: Drawing, profile: ProjectProfile):
        self.doc, self.d, self.p = doc, drawing, profile
        self.cnt = Counter()

    # -- text ---------------------------------------------------------------
    def _style_height(self, style):
        try:
            return float(self.doc.styles.get(style).dxf.get("height", 0) or 0)
        except Exception:
            return 0.0

    def _annotative(self, e, style):
        try:
            if e.has_xdata("AcadAnnotative"):
                return True
            st = self.doc.styles.get(style)
            return st.has_xdata("AcadAnnotative")
        except Exception:
            return False

    def add_text(self, e, layout, is_model, block_path, top_handle, raw_hint=None):
        t = e.dxftype()
        style = e.dxf.get("style", "Standard")
        note, certain = "", True
        if t in ("TEXT", "ATTRIB", "ATTDEF"):
            txt = e.dxf.get("text", "") or ""
            h = float(e.dxf.get("height", 0) or 0)
            if h == 0:
                h = self._style_height(style)
                note = "height taken from text style" if h else "zero height and no style height"
                certain = bool(h)
            raw = raw_hint if raw_hint else h
            hal, val = e.dxf.get("halign", 0), e.dxf.get("valign", 0)
            pt = e.dxf.align_point if (hal or val) and e.dxf.hasattr("align_point") else e.dxf.insert
            eff = h
            rot = e.dxf.get("rotation", 0)
            nl = 1
        elif t == "MTEXT":
            txt = e.plain_text()
            base, eff, certain, note = _mtext_height(e)
            raw = raw_hint if raw_hint else base
            pt = e.dxf.insert
            rot = e.dxf.get("rotation", 0)
            nl = max(1, txt.count("\n") + 1)
        else:
            return
        if self._annotative(e, style):
            certain, note = False, (note + "; " if note else "") + "annotative text - annotation scale not evaluated"
        if is_model and len(set(self.d.viewport_scales)) > 1:
            certain, note = False, (note + "; " if note else "") + "model-space text shown at several viewport scales"
        it = TextItem(handle=top_handle or e.dxf.handle, kind=t, text=txt.strip(), x=float(pt[0]), y=float(pt[1]),
                      raw_height=float(raw), eff_height=float(eff), layer=e.dxf.get("layer", "0"), style=style,
                      layout=layout, is_model=is_model, rotation=float(rot or 0), block_path=tuple(block_path),
                      top_handle=top_handle or "", height_certain=certain, height_note=note, nlines=nl)
        self.d.texts.append(it)

    def add_dimension(self, e, layout, is_model):
        try:
            ov = e.override()
            h = float(ov.get("dimtxt", 2.5) or 2.5)
            sc = float(ov.get("dimscale", 1.0) or 1.0)
            mp = e.dxf.get("text_midpoint", e.dxf.get("defpoint", (0, 0, 0)))
            txt = e.dxf.get("text", "") or ""
            if txt in ("", "<>"):
                try:
                    txt = f"{e.get_measurement():.0f}"
                except Exception:
                    txt = "<>"
            self.d.texts.append(TextItem(handle=e.dxf.handle, kind="DIMENSION", text=txt, x=mp[0], y=mp[1],
                                         raw_height=h, eff_height=h * sc, layer=e.dxf.get("layer", "0"),
                                         style=str(e.dxf.get("dimstyle", "")), layout=layout, is_model=is_model))
        except Exception as ex:
            self.d.limitations.append(f"DIMENSION {e.dxf.handle}: text height not evaluated ({ex})")

    def add_mleader(self, e, layout, is_model):
        try:
            ctx = e.context
            mt = ctx.mtext
            txt = (mt.default_content or "").strip()
            ins = mt.insert
            h = float(getattr(ctx, "char_height", 0) or 0)
            self.d.texts.append(TextItem(handle=e.dxf.handle, kind="MLEADER", text=re.sub(r"\\[A-Za-z][^;]*;", "", txt),
                                         x=ins[0], y=ins[1], raw_height=h, eff_height=h, layer=e.dxf.get("layer", "0"),
                                         style=str(e.dxf.get("style_handle", "")), layout=layout, is_model=is_model,
                                         height_certain=bool(h)))
        except Exception as ex:
            self.d.limitations.append(f"MULTILEADER {e.dxf.handle}: content not extracted ({ex})")

    # -- inserts (nested blocks, MINSERT, rendered ACAD_TABLE blocks) ------------
    def expand_insert(self, ins, layout, is_model, block_path, top_handle, depth=0):
        if depth > 8:
            self.d.limitations.append(f"Block nesting deeper than 8 under insert {top_handle}: not fully inspected")
            return
        name = ins.dxf.get("name", "")
        try:
            blk = ins.block()
        except Exception:
            blk = None
        if blk is None:
            self.d.limitations.append(f"INSERT {ins.dxf.handle}: block '{name}' not found")
            return
        if getattr(blk.block_record, "is_xref", False) if hasattr(blk, "block_record") else False:
            self.d.unsupported["XREF"] = self.d.unsupported.get("XREF", 0) + 1
            self.d.limitations.append(f"External reference '{name}' is not inspected - review its areas manually")
            return
        src = [x for x in blk]
        try:
            virt = list(ins.virtual_entities())
        except Exception as ex:
            self.d.limitations.append(f"INSERT {ins.dxf.handle} '{name}' could not be transformed ({ex})")
            return
        raw_map = {}
        if len(src) == len(virt):
            for s, v in zip(src, virt):
                if s.dxftype() == "TEXT":
                    raw_map[id(v)] = float(s.dxf.get("height", 0) or 0)
                elif s.dxftype() == "MTEXT":
                    raw_map[id(v)] = float(s.dxf.get("char_height", 0) or 0)
        bp = tuple(block_path) + (name,)
        for v in virt:
            vt = v.dxftype()
            if vt in ("TEXT", "MTEXT", "ATTDEF"):
                if vt == "ATTDEF":
                    continue  # attribute definitions inside a block are templates; the INSERT's ATTRIBs carry the values
                self.add_text(v, layout, is_model, bp, top_handle or ins.dxf.handle, raw_map.get(id(v)))
            elif vt == "INSERT":
                self.expand_insert(v, layout, is_model, bp, top_handle or ins.dxf.handle, depth + 1)
        for a in getattr(ins, "attribs", []):
            self.add_text(a, layout, is_model, bp, top_handle or ins.dxf.handle)

    # -- main -----------------------------------------------------------------
    def run(self):
        for lay in self.doc.layouts:
            is_model = lay.is_modelspace
            name = lay.name
            for e in lay:
                t = e.dxftype()
                self.cnt[t] += 1
                if t in UNSUPPORTED_TYPES:
                    self.d.unsupported[t] = self.d.unsupported.get(t, 0) + 1
                    continue
                if t in ("TEXT", "MTEXT"):
                    self.add_text(e, name, is_model, (), "")
                elif t == "DIMENSION":
                    self.add_dimension(e, name, is_model)
                elif t == "MULTILEADER":
                    self.add_mleader(e, name, is_model)
                elif t == "INSERT" or t == "ACAD_TABLE":
                    try:
                        if getattr(e.dxf, "row_count", 1) is None:
                            pass
                        mcount = getattr(e, "mcount", 1)
                        items = list(e.multi_insert()) if mcount and mcount > 1 else [e]
                    except Exception:
                        items = [e]
                    for ins in items:
                        pos = ins.dxf.get("insert", (0, 0, 0))
                        self.d.inserts.append(InsertItem(e.dxf.handle, e.dxf.get("layer", "0"), name,
                                                         ins.dxf.get("name", ""), pos[0], pos[1],
                                                         ins.dxf.get("xscale", 1.0), ins.dxf.get("yscale", 1.0)))
                        self.expand_insert(ins, name, is_model, (), e.dxf.handle)
                    if t == "ACAD_TABLE":
                        self.d.limitations.append(f"Native table {e.dxf.handle} read from its rendered block only - verify the schedule mapping")
                elif t == "LINE":
                    self.d.lines.append(LineItem(e.dxf.handle, e.dxf.layer, name, tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]))
                elif t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    self.d.polys.append(PolyItem(e.dxf.handle, e.dxf.layer, name, pts, bool(e.closed)))
                    if any(abs(p[0]) > 1e-9 for p in e.get_points("b")):
                        self.d.limitations.append(f"LWPOLYLINE {e.dxf.handle} has arc segments; treated as straight chords")
                elif t == "POLYLINE" and e.is_2d_polyline:
                    pts = [(v.dxf.location[0], v.dxf.location[1]) for v in e.vertices]
                    self.d.polys.append(PolyItem(e.dxf.handle, e.dxf.layer, name, pts, bool(e.is_closed)))
                elif t == "MLINE":
                    self.add_mline(e, name)
        self.d.entity_counts = dict(self.cnt)

    def add_mline(self, e, layout):
        try:
            st = e.style
            offs = [el.offset for el in st.elements]
            scale = float(e.dxf.get("scale_factor", 1.0))
            width = (max(offs) - min(offs)) * abs(scale) if offs else 0.0
            pts = [(p[0], p[1]) for p in e.get_locations()]
            self.d.mlines.append(MLineItem(e.dxf.handle, e.dxf.layer, layout, pts, width, len(offs), scale,
                                           st.dxf.name, bool(e.is_closed)))
        except Exception as ex:
            self.d.limitations.append(f"MLINE {e.dxf.handle}: geometry not interpreted ({ex})")


def load_drawing(path: str, profile: Optional[ProjectProfile] = None, workdir: Optional[str] = None) -> Drawing:
    profile = profile or ProjectProfile()
    if not path.lower().endswith(".dxf"):
        raise ValueError("Stage 1 reads DXF directly. DWG needs the local converter added in Stage 3 (see docs/LIMITATIONS.md).")
    sha = sha256_file(path)
    tmp = workdir or tempfile.mkdtemp(prefix="structcheck_")
    work = os.path.join(tmp, "working_copy.dxf")
    shutil.copy2(path, work)           # all parsing happens on the copy
    try:
        doc = ezdxf.readfile(work)
        recovered = False
    except Exception:
        doc, auditor = recover.readfile(work)
        recovered = True
    # units
    ins = doc.header.get("$INSUNITS", 0)
    if profile.drawing_unit != "auto":
        unit_mm, src = UNIT_NAME_TO_MM[profile.drawing_unit], "profile"
    elif ins in INSUNITS_TO_MM and INSUNITS_TO_MM[ins] > 0:
        unit_mm, src = INSUNITS_TO_MM[ins], f"$INSUNITS={ins}"
    else:
        unit_mm, src = 1.0, "assumed mm ($INSUNITS unset) - confirm in profile"
    d = Drawing(path=path, filename=os.path.basename(path), size_bytes=os.path.getsize(path), sha256=sha,
                unit_mm=unit_mm, unit_source=src, layouts=[l.name for l in doc.layouts],
                layers=[l.dxf.name for l in doc.layers], dxf_version=doc.dxfversion)
    if recovered:
        d.limitations.append("File needed recovery mode; some entities may be missing - verify counts.")
    if src.startswith("assumed"):
        d.limitations.append("Drawing units not stored in the file; assumed millimetres.")
    # viewport scales (paper space)
    for lay in doc.layouts:
        if lay.is_any_paperspace:
            for vp in lay.viewports():
                try:
                    if vp.dxf.height:
                        d.viewport_scales.append(round(vp.dxf.view_height / vp.dxf.height, 4))
                except Exception:
                    pass
    _Loader(doc, d, profile).run()
    d._workdir = tmp
    d._keep_temp = profile.keep_temp_files
    return d
