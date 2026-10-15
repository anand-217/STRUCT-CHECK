# StructCheck inside AutoCAD (AutoLISP add-on)

Run the check from the drawing you are working on - no manual DXF export, no uploading.

## Install (once)
1. Build/download **StructCheck.exe v0.5 or later** (GitHub workflow, same as before). Keep it somewhere permanent, e.g. `C:\StructCheck\StructCheck.exe`.
2. Copy `autocad\StructCheck.lsp` to e.g. `C:\StructCheck\`.
3. In AutoCAD: type `APPLOAD` -> select `StructCheck.lsp` -> Load. To load it every time: in the same dialog click
   **Contents** (Startup Suite) -> Add -> `StructCheck.lsp`.
4. If AutoCAD blocks the file (SECURELOAD): `OPTIONS` -> Files -> Trusted Locations -> add `C:\StructCheck\`.
5. Type `SCHECK`. The first time it asks for `StructCheck.exe`; the choice is remembered (`SCHECKSETUP` changes it).

## Commands
| Command | What it does |
|---|---|
| `SCHECK` | Exports the open drawing (as it is on screen, even unsaved) to a temporary DXF, runs all eight checks, draws circles/ellipses + finding IDs on layer `STRUCTCHECK_REVIEW`, zooms to them, lists the findings on the command line (F2) and in a summary box |
| `SCHECKE` | Same, circling ERROR findings only |
| `SCHECKCLEAR` | Removes every mark. **Run this before issuing the drawing.** One `UNDO` also removes the marks |
| `SCHECKPDF` | Also writes a marked PDF (overview + zoomed page per finding) and opens it |
| `SCHECKFOLDER` | Opens the folder with the Excel report (`<drawing folder>\StructCheck_Reports\`) |
| `SCHECKSETUP` | Choose / change the location of StructCheck.exe |

Colours: red = ERROR, orange = WARNING, amber = REVIEW. Only entities on `STRUCTCHECK_REVIEW` are added; your drawing
geometry is not edited. Switch to the **Model** tab first.

## Optional project profile
Put `structcheck_profile.json` in the same folder as the DWG; the add-on passes it automatically.

## Requirements and honest limits
- Full AutoCAD (uses `vl-` file functions). AutoCAD LT is not supported.
- **This LISP could not be run inside AutoCAD while it was being written** (no AutoCAD available); the StructCheck side
  (command-line mode, marks file, summary file) is covered by automated tests. Please report any AutoCAD error text.
- If `DXFOUT` behaves differently in your AutoCAD version, the add-on says so; export a DXF manually and use the StructCheck window.
- Large drawings: the check can take a minute (the add-on waits up to ~4 minutes).

## Troubleshooting
| Symptom | Fix |
|---|---|
| "did not answer within 4 minutes" | `SCHECKSETUP` and select the v0.5+ exe (older versions have no command-line mode) |
| "could not finish" + path | open the `structcheck_error.txt` named in the message and send it to me |
| No marks visible | `ZOOM E`; check layer `STRUCTCHECK_REVIEW` is on and not frozen |
| Command not found | `APPLOAD` the file again; check the trusted-location setting |
