import argparse, os, sys, traceback
from .engine import run_checks
from .profile import ProjectProfile
from . import export

def main(argv=None):
    ap = argparse.ArgumentParser(prog="structcheck", description="Offline structural drawing QC (never modifies the source drawing)")
    ap.add_argument("drawing"); ap.add_argument("--profile"); ap.add_argument("--out", default="structcheck_out")
    ap.add_argument("--formats", default="json,csv,xlsx"); ap.add_argument("--rules", help="comma list, e.g. 1,2,8")
    ap.add_argument("--mark", action="store_true", help="also write <name>_REVIEW.dxf and <name>_REVIEW.pdf with circles on findings")
    ap.add_argument("--errors-only", action="store_true", help="circle ERROR findings only")
    ap.add_argument("--lisp", action="store_true", help="AutoCAD add-on mode: write <name>_marks.tsv and <name>_summary.txt (written last)")
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
    if a.lisp:
        from . import review, __version__
        sev = ("ERROR",) if a.errors_only else review.MARKABLE
        tsv = os.path.join(a.out, f"{stem}_marks.tsv")
        n, skipped = review.write_marks_tsv(a.drawing, res.findings, tsv, res.drawing["unit_mm_per_drawing_unit"], sev)
        tmp = os.path.join(a.out, f"{stem}_summary.tmp"); fin = os.path.join(a.out, f"{stem}_summary.txt")
        order = {"ERROR": 0, "WARNING": 1, "REVIEW": 2, "NOT CHECKED": 3}
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(f"version={__version__}\nerrors={s['errors']}\nwarnings={s['warnings']}\nreview={s['review']}\n"
                    f"not_checked={s['not_checked_items']}\nmarks={n}\nunmarked={len(skipped)}\nunchanged={res.integrity['unchanged']}\n")
            for r in res.rules:
                f.write(f"R\t{r['rule']}\t{r['status']}\t{r['finding_count']}\t{r['name']}\n")
            for x in sorted(res.findings, key=lambda x: (order[x.severity.value], x.rule)):
                f.write("F\t" + "\t".join([x.id, x.severity.value, (x.description or "").replace("\t", " ").replace("\n", " ")]) + "\n")
        os.replace(tmp, fin)                      # the add-on waits for this file: it appears only when everything is written
    print(f"{res.drawing['filename']}: {s['errors']} errors, {s['warnings']} warnings, {s['review']} review, {s['not_checked_items']} not-checked items")
    for r in res.rules: print(f"  Rule {r['rule']}: {r['status']:9} findings={r['finding_count']} {r['name']}")
    print("Source drawing unchanged:", res.integrity["unchanged"])
    return 0

def safe_main(argv=None):
    """Used by the windowed .exe (no console): never crashes silently, writes structcheck_error.txt next to the output."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    try:
        return main(argv)
    except SystemExit as e:
        return e.code or 0
    except Exception:
        out = "structcheck_out"
        args = argv if argv is not None else sys.argv[1:]
        if "--out" in args and args.index("--out") + 1 < len(args):
            out = args[args.index("--out") + 1]
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "structcheck_error.txt"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(safe_main())
