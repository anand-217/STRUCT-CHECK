# Layer names and drawing format - what StructCheck needs

**No fixed layer names are required.** It reads text by content and position. Layer names only help it, and every
pattern is editable in the project profile (JSON).

| Item | How it is recognised | Profile key |
|---|---|---|
| Beam number tags | Any short text on a layer matching `BEAM NO / BEAM_TXT / BEAM TAG / BM NO`; else text matching the beam id pattern (B1, BM-2...) | `beam_label_layers`, `beam_id_regex` |
| Slab numbers | Text on layer `SLAB` (or `SLAB NO / SLAB_TXT`), else pattern S1, S-2... | `slab_label_layers`, `slab_id_regex` |
| Column numbers | Text on layer `COL-NO / COLUMN_TXT / COL NO`, else pattern C1, COL2... | `column_label_layers`, `column_id_regex` |
| Beam geometry | MLINE (width = style offsets x scale), two parallel LINEs, or a thin closed polyline; layers containing `BEAM` preferred | `beam_layers` |
| Schedules | A title text containing SCHEDULE plus BEAM / SLAB / COLUMN (e.g. "SCHEDULE OF BEAMS AT SECOND SLAB LEVEL"); header lines may span several rows | `beam_columns`, `slab_columns`, `column_columns` |

If your layers are named differently, put a regex for them in the matching `*_label_layers` list.

## Supported schedule conventions (from your TRY_RUN_01 drawing)
- Multi-line column headers ("BOTTOM / STEEL / STRAIGHT / FULL SPAN") are joined per column.
- One schedule row may list several beams: `2, 8, 19.` / `26. 27.` (also `1 TO 4`). Each beam is checked separately.
- Size column `230 X 600` is split into width and depth.
- Ids like `S 1.`, `8/`, `1C.` are cleaned (spaces, trailing dots).
- A beam drawn span-by-span (separate MLINE pieces with a column between) counts as ONE beam needing one label.
- Column schedules that list only some columns (here FC16, FC9) are compared only with plan labels of the same prefix.

## Known gaps on this format
- Slab panels are inferred from the beam network (shapely); they need beams that close the panel, small gaps at columns are bridged (panel_close_gap_mm). Findings on inferred panels are REVIEW-level.
- A label placed between two beams is reported as ambiguous (REVIEW), not guessed.
- Hidden beams drawn as parallel lines are measured as such; confirm against your drawing convention.
