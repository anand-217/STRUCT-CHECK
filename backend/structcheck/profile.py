"""Reusable project profile (saved as JSON, fully local)."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# Column maps: field -> list of phrases. A header (all header lines of a column joined) matches a field when ALL
# words of ANY phrase are present in it. Fields are tried in the order listed, first match wins.
def _beam_cols():
    return {
        "id": ["BEAM NUMBERS", "BEAM NOS", "BEAM NO", "BEAM MARK", "BEAM", "BM NO", "MARK"],
        "size": ["SIZE", "B X D"],
        "width": ["WIDTH", "BREADTH"],
        "depth": ["DEPTH", "OVERALL DEPTH"],
        "bottom_curtailed": ["CURTAILED"],
        "top_anchor": ["ANCHOR"],
        "top_left": ["LEFT"],
        "top_right": ["RIGHT"],
        "bottom": ["BOTTOM", "STRAIGHT"],
        "top": ["TOP"],
        "stirrups": ["STIRRUPS", "STIRRUP", "SHEAR", "LINKS"],
    }


def _slab_cols():
    return {
        "id": ["SLAB NOS", "SLAB NO", "SLAB MARK", "SLAB", "MARK"],
        "thickness": ["THK", "THICKNESS", "DEPTH"],
        "bottom_dist": ["DISTRIBUTION", "DIST"],
        "bottom_main": ["MAIN", "SHORT SPAN"],
        "top": ["TOP"],
        "remarks": ["REMARKS", "REMARK"],
    }


def _col_cols():
    return {
        "id": ["COLUMN NOS", "COLUMN NO", "COL NO", "COLUMN MARK", "COLUMN", "COL", "MARK"],
        "size": ["SIZE", "DIMENSION", "B X D", "SECTION"],
        "main": ["MAIN", "VERTICAL", "REINFORCEMENT", "LONGITUDINAL"],
        "ties": ["TIES", "STIRRUPS", "LINKS", "LATERAL"],
    }


@dataclass
class ProjectProfile:
    name: str = "Default"
    # --- units ---
    drawing_unit: str = "auto"            # auto | mm | cm | m | in | ft
    # --- identifier patterns ---
    beam_id_regex: str = r"(?:B|BM|FB|PB|SB)[- ]?\d+[A-Za-z]?"
    slab_id_regex: str = r"S[- ]?\d+[A-Za-z]?"
    column_id_regex: str = r"(?:C|COL|K)[- ]?\d+[A-Za-z]?"
    hyphen_equivalent: bool = False       # treat B1 == B-1 (only when engineer allows)
    leading_zero_equivalent: bool = False
    # --- schedule column keyword maps (engineer can override per project) ---
    beam_columns: dict = field(default_factory=_beam_cols)
    slab_columns: dict = field(default_factory=_slab_cols)
    column_columns: dict = field(default_factory=_col_cols)
    beam_required_fields: list = field(default_factory=lambda: ["id", "width", "depth", "bottom"])
    slab_required_fields: list = field(default_factory=lambda: ["id", "thickness", "bottom_main", "bottom_dist"])
    column_required_fields: list = field(default_factory=lambda: ["id", "size"])
    # Layers that carry the label text. Patterns are regex (case-insensitive). When a layer matches, EVERY text on it
    # is a label (so numeric tags like "12" or "12C" work); otherwise the id regex above is used on all plan text.
    beam_label_layers: list = field(default_factory=lambda: [r"BEAM[ _-]?(NO|NUM|TXT|TEXT|MARK|TAG)", r"^BM[ _-]?(NO|TXT)"])
    slab_label_layers: list = field(default_factory=lambda: [r"^SLAB([ _-]?(NO|NUM|TXT|TEXT|MARK|TAG))?$"])
    column_label_layers: list = field(default_factory=lambda: [r"COL(UMN)?[ _-]?(NO|NUM|TXT|TEXT|MARK|TAG)"])
    schedule_max_gap_mm: float = 3500.0       # horizontal gap that ends a schedule
    schedule_max_row_gap_factor: float = 4.0  # vertical gap (x typical row pitch) that ends a schedule
    plan_margin_mm: float = 4000.0            # beams farther than this from every beam label are treated as details, not plan
    beam_chain_gap_mm: float = 1500.0         # collinear MLINE pieces closer than this form one beam run (columns between spans)
    schedule_regions: list = field(default_factory=list)   # [{"type":"beam","layout":"Model","bbox":[x0,y0,x1,y1]}]
    schedule_row_tol_factor: float = 0.7
    # --- Rule 1/2 beams ---
    beam_layers: list = field(default_factory=list)        # regex list; empty = auto
    excluded_layers: list = field(default_factory=list)    # regex list, applies to all geometry/text
    beam_width_tolerance_mm: float = 5.0
    beam_min_width_mm: float = 75.0
    beam_max_width_mm: float = 1200.0
    beam_min_length_mm: float = 800.0
    label_search_radius_mm: float = 600.0
    # --- Rule 4 slabs ---
    panel_layers: list = field(default_factory=list)
    min_panel_area_m2: float = 1.5
    max_panel_area_m2: float = 150.0
    allow_multiple_slab_labels: bool = False
    # --- Rule 6 titles ---
    title_abbreviations: dict = field(default_factory=lambda: {"GF": "GROUND", "G.F.": "GROUND", "FF": "FIRST", "SF": "SECOND", "TF": "THIRD"})
    single_floor_per_drawing: bool = True
    # --- Rule 7 columns ---
    column_id_mode: str = "unknown"       # unique | types | unknown
    column_schedule_check: bool = True
    column_label_conflict_dist_mm: float = 300.0
    column_max_dim_mm: float = 1500.0
    # --- Rule 8 text height ---
    text_categories_standard: dict = field(default_factory=dict)   # {"Beam numbers": 150.0} effective drawing units
    text_height_tolerance_pct: float = 3.0
    text_min_dominance: float = 0.6
    text_likely_dominance: float = 0.8
    text_min_group_size: int = 3
    exclude_text_layers: list = field(default_factory=list)
    exclude_text_styles: list = field(default_factory=list)
    exclude_text_blocks: list = field(default_factory=list)
    exclude_text_patterns: list = field(default_factory=list)
    exclude_entity_types: list = field(default_factory=list)
    exclude_text_handles: list = field(default_factory=list)
    exclude_regions: list = field(default_factory=list)   # [{"layout":"Model","bbox":[...],"kind":"notes"|"titleblock"}]
    include_notes_check: bool = False
    plot_scale: Optional[float] = None    # e.g. 100 for 1:100 model-space plotting
    min_plotted_text_mm: float = 1.8
    # --- housekeeping ---
    default_report_formats: list = field(default_factory=lambda: ["json", "csv", "xlsx"])
    keep_temp_files: bool = False

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        base = cls()
        for k, v in data.items():
            if hasattr(base, k):
                setattr(base, k, v)
        return base
