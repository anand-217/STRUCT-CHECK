import argparse, os, sys
from .engine import run_checks
from .profile import ProjectProfile
from . import export

def main(argv=None):
    ap = argparse.ArgumentParser(prog="structcheck", description="Offline structural drawing QC (never modifies the source drawing)")
    ap.add_argument("drawing"); ap.add_argument("--profile"); ap.add_argument("--out", default="structcheck_out")
    ap.add_argument("--formats", default="json,csv,xlsx"); ap.add_argument("--rules", help="comma list, e.g. 1,2,8")
    a = ap.parse_args(argv)
    prof = ProjectProfile.load(a.profile) if a.profile else ProjectProfile()
    res = run_checks(a.drawing, prof, [int(x) for x in a.rules.split(",")] if a.rules else None)
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.drawing))[0]
    for fmt in a.formats.split(","):
        getattr(export, "to_" + fmt)(res, os.path.join(a.out, f"{stem}_report.{fmt}"))
    s = res.summary()
    print(f"{res.drawing['filename']}: {s['errors']} errors, {s['warnings']} warnings, {s['review']} review, {s['not_checked_items']} not-checked items")
    for r in res.rules: print(f"  Rule {r['rule']}: {r['status']:9} findings={r['finding_count']} {r['name']}")
    print("Source drawing unchanged:", res.integrity["unchanged"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
