import argparse, os, sys
from .engine import run_checks
from .profile import ProjectProfile
from . import export

def main(argv=None):
    ap = argparse.ArgumentParser(prog="structcheck", description="Offline structural drawing QC (never modifies the source drawing)")
    ap.add_argument("drawing"); ap.add_argument("--profile"); ap.add_argument("--out", default="structcheck_out")
    ap.add_argument("--formats", default="json,csv,xlsx"); ap.add_argument("--rules", help="comma list, e.g. 1,2,8")
    ap.add_argument("--mark", action="store_true", help="also write <name>_REVIEW.dxf and <name>_REVIEW.pdf with circles on findings")
    ap.add_argument("--errors-only", action="store_true", help="circle ERROR findings only")
    a = ap.parse_args(argv)
    prof = ProjectProfile.load(a.profile) if a.profile else ProjectProfile()
    res = run_checks(a.drawing, prof, [int(x) for x in a.rules.split(",")] if a.rules else None)
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.drawing))[0]
    for fmt in a.formats.split(","):
        getattr(export, "to_" + fmt)(res, os.path.join(a.out, f"{stem}_report.{fmt}"))
    if a.mark:
        from . import review
        sev = ("ERROR",) if a.errors_only else review.MARKABLE
        dxf_out = os.path.join(a.out, f"{stem}_REVIEW.dxf")
        n, skipped = review.mark_dxf(a.drawing, res.findings, dxf_out, res.drawing["unit_mm_per_drawing_unit"], sev)
        print(f"Marked DXF copy: {dxf_out} ({n} circles; {len(skipped)} findings have no drawable location)")
        try:
            review.mark_pdf(dxf_out, res.findings, os.path.join(a.out, f"{stem}_REVIEW.pdf"), res.drawing["unit_mm_per_drawing_unit"], severities=sev)
            print("Marked PDF written")
        except ImportError:
            print("PDF skipped: matplotlib not installed")
    s = res.summary()
    print(f"{res.drawing['filename']}: {s['errors']} errors, {s['warnings']} warnings, {s['review']} review, {s['not_checked_items']} not-checked items")
    for r in res.rules: print(f"  Rule {r['rule']}: {r['status']:9} findings={r['finding_count']} {r['name']}")
    print("Source drawing unchanged:", res.integrity["unchanged"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
