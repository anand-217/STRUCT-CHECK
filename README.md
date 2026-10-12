# StructCheck — Stage 1 (engine) 

Offline structural drawing QC. **Stage 1 = working Python engine + CLI + tests.** It parses a DXF, recognises schedules,
runs all eight rules, and exports JSON / CSV / XLSX. The source drawing is never opened for writing (SHA-256 checked before/after).

## Run
```
cd backend
pip install -r requirements.txt
python -m pytest -q                                   # 39 tests
python -m structcheck ../samples/sample_with_errors.dxf --profile ../samples/sample_profile.json --out out
```
`samples/sample_clean.dxf` must give zero findings; `sample_with_errors.dxf` has 19 intentionally injected errors
(see `backend/tests/sample_factory.py`).

## What is done / not done
| Area | Status |
|---|---|
| DXF ingestion, hashing, working copy, units, nested blocks, MINSERT, attributes, MLEADER, dimensions | Done |
| Schedule recognition (loose TEXT/MTEXT) + configurable column keywords + manual regions | Done (heuristic, see limits) |
| Rules 1-8 with ERROR / WARNING / REVIEW / NOT CHECKED semantics | Done, tested on synthetic drawings only |
| JSON, CSV, XLSX export | Done |
| **Real-world validation on your drawings** | **Not done - needed before trusting results** |
| PDF report, snapshots | Not done (Stage 3) |
| DWG input (needs a local converter: ODA File Converter or LibreDWG; check each licence before bundling) | Not done (Stage 3) |
| React/Electron UI, CAD preview, highlighting overlay, review-status UI | Not done (Stage 2) |
| Windows installer / packaging, SQLite history | Not done (Stage 4) |

## Key behaviours
- Uncertain = REVIEW; a rule that cannot run = NOT CHECKED (never PASS). Crashing rules are reported as skipped.
- Column numbering mode (`column_id_mode`: unique / types / unknown) is set in the profile; unknown gives REVIEW only.
- B1 vs B-1 are not merged unless `hyphen_equivalent` / `leading_zero_equivalent` is enabled.
- Text height: configured standard => ERROR; inferred (>=80% dominant) => WARNING; 60-80% => REVIEW; no dominant => REVIEW only.
  Notes, title blocks, headings, revision data excluded by default (heuristics + profile rules).

## Known limitations (be aware)
- Schedules: header must be one line of TEXT/MTEXT with left-aligned columns; merged cells, multi-line headers and
  centre-aligned cells may misassign. Native ACAD_TABLE is read from its rendered block only (not verified here).
  Use `schedule_regions` and the keyword maps in the profile.
- Beams: MLINE (offset span x scale; rotation-safe), parallel LINE pairs and thin closed rectangles. Hatches, arcs
  (treated as chords), beams drawn as single centrelines and MLINE justification are not interpreted. Layers inferred
  from the name BEAM when not configured (lower confidence).
- Slab panels: closed polylines of plausible area only; panels formed by beams/grids are not inferred.
- Viewport / annotative scale: detected, but plotted height is NOT computed; such text is reported as REVIEW with raw
  heights. Xrefs, IMAGE, proxy and 3D entities are listed as unsupported, never silently skipped.
- Line pairing is O(n^2) per layout; very large drawings need layer filtering (not performance-tested).
- Schedule widths are assumed to be in mm.

## Desktop app / no Python for end users
`python -m structcheck.gui` opens the window (open DXF, run, filter findings, export Excel/CSV/JSON).
To get a standalone **StructCheck.exe**: on any Windows PC with Python, double-click `build_windows.bat`
(result: `backend\dist\StructCheck.exe`). Copy that single file anywhere; Python is not needed to run it.
Alternative without installing Python: push this folder to a GitHub repo and run the "Build StructCheck.exe"
workflow (Actions tab); download the exe from the run's artifacts. The .exe has not been built or run on Windows by me.
