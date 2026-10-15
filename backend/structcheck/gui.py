"""Simple offline desktop window (Tkinter ships with Python and is bundled into the .exe)."""
import os, sys, threading, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from . import __version__
from .engine import run_checks, DISCLAIMER
from .profile import ProjectProfile
from . import export

ORANGE, DARK, GREY = "#F58220", "#D96B10", "#F7F8FA"
SEV_BG = {"ERROR": "#FDE2E0", "WARNING": "#FDE8D3", "REVIEW": "#FBF0CF", "NOT CHECKED": "#E5E7EB"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"StructCheck v{__version__} - structural drawing QC (offline)")
        self.geometry("1280x760")
        self.configure(bg="white")
        self.result = None
        self.path = tk.StringVar()
        self.profile_path = tk.StringVar()
        self.mode = tk.StringVar(value="unknown")
        self.sev_filter = tk.StringVar(value="All")
        self.rule_filter = tk.StringVar(value="All")
        self._style()
        self._build()

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Accent.TButton", background=ORANGE, foreground="white", padding=8, font=("Segoe UI", 10, "bold"))
        s.map("Accent.TButton", background=[("active", DARK), ("disabled", "#F9C79A")])
        s.configure("Treeview", rowheight=24)
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build(self):
        top = tk.Frame(self, bg="white"); top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="StructCheck", font=("Segoe UI", 18, "bold"), fg=ORANGE, bg="white").pack(side="left")
        tk.Label(top, text="  original drawing is never modified", fg="#16803C", bg="white").pack(side="left")
        row = tk.Frame(self, bg="white"); row.pack(fill="x", padx=12, pady=4)
        ttk.Button(row, text="Open DXF drawing...", style="Accent.TButton", command=self.pick).pack(side="left")
        tk.Label(row, textvariable=self.path, bg="white", fg="#6B7280").pack(side="left", padx=8)
        row2 = tk.Frame(self, bg="white"); row2.pack(fill="x", padx=12, pady=4)
        ttk.Button(row2, text="Profile (optional)...", command=self.pick_profile).pack(side="left")
        tk.Label(row2, textvariable=self.profile_path, bg="white", fg="#6B7280").pack(side="left", padx=8)
        tk.Label(row2, text="Column numbers are:", bg="white").pack(side="left", padx=(20, 4))
        ttk.Combobox(row2, textvariable=self.mode, values=["unknown", "unique", "types"], width=9, state="readonly").pack(side="left")
        self.run_btn = ttk.Button(row2, text="Run drawing checks", style="Accent.TButton", command=self.run)
        self.run_btn.pack(side="right")
        self.prog = ttk.Progressbar(self, mode="indeterminate"); self.prog.pack(fill="x", padx=12)
        self.summary = tk.Label(self, text=f"StructCheck v{__version__}  |  {self._capabilities()}\nOpen a DXF to begin.", anchor="w", bg=GREY, padx=8, pady=6, justify="left")
        self.summary.pack(fill="x", padx=12, pady=6)
        flt = tk.Frame(self, bg="white"); flt.pack(fill="x", padx=12)
        tk.Label(flt, text="Severity", bg="white").pack(side="left")
        ttk.Combobox(flt, textvariable=self.sev_filter, values=["All", "ERROR", "WARNING", "REVIEW", "NOT CHECKED"], width=12, state="readonly").pack(side="left", padx=4)
        tk.Label(flt, text="Rule", bg="white").pack(side="left", padx=(12, 0))
        ttk.Combobox(flt, textvariable=self.rule_filter, values=["All"] + [str(i) for i in range(1, 9)], width=5, state="readonly").pack(side="left", padx=4)
        for v in (self.sev_filter, self.rule_filter):
            v.trace_add("write", lambda *_: self.fill())
        ttk.Button(flt, text="Marked PDF", style="Accent.TButton", command=lambda: self.mark("pdf")).pack(side="right", padx=3)
        ttk.Button(flt, text="Marked DXF", style="Accent.TButton", command=lambda: self.mark("dxf")).pack(side="right", padx=3)
        self.only_err = tk.BooleanVar(value=False)
        tk.Checkbutton(flt, text="circle errors only", variable=self.only_err, bg="white").pack(side="right", padx=6)
        for label, fmt in (("Export Excel", "xlsx"), ("Export CSV", "csv"), ("Export JSON", "json")):
            ttk.Button(flt, text=label, command=lambda f=fmt: self.export(f)).pack(side="right", padx=3)
        pan = ttk.PanedWindow(self, orient="vertical"); pan.pack(fill="both", expand=True, padx=12, pady=6)
        cols = ("id", "sev", "rule", "identifier", "layout", "description", "conf")
        self.tree = ttk.Treeview(pan, columns=cols, show="headings", selectmode="browse")
        for c, w in zip(cols, (80, 90, 50, 110, 80, 700, 60)):
            self.tree.heading(c, text=c.upper()); self.tree.column(c, width=w, anchor="w")
        for sev, bg in SEV_BG.items():
            self.tree.tag_configure(sev, background=bg)
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        pan.add(self.tree, weight=3)
        self.detail = tk.Text(pan, height=10, wrap="word", bg=GREY, relief="flat", padx=8, pady=6); pan.add(self.detail, weight=1)
        tk.Label(self, text=DISCLAIMER, fg="#6B7280", bg="white", wraplength=1200, justify="left").pack(fill="x", padx=12, pady=(0, 8))

    @staticmethod
    def _capabilities():
        def has(m):
            try:
                __import__(m); return "yes"
            except Exception:
                return "NO"
        return f"slab-panel inference (shapely): {has('shapely')}   marked PDF (matplotlib): {has('matplotlib')}"

    def pick(self):
        p = filedialog.askopenfilename(title="Select DXF", filetypes=[("DXF drawing", "*.dxf")])
        if p:
            self.path.set(p)

    def pick_profile(self):
        p = filedialog.askopenfilename(title="Select profile", filetypes=[("JSON profile", "*.json")])
        if p:
            self.profile_path.set(p)

    def run(self):
        if not self.path.get():
            messagebox.showinfo("StructCheck", "Open a DXF drawing first."); return
        self.run_btn.state(["disabled"]); self.prog.start(12); self.summary.config(text="Checking...")
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            prof = ProjectProfile.load(self.profile_path.get()) if self.profile_path.get() else ProjectProfile()
            if not self.profile_path.get():
                prof.column_id_mode = self.mode.get()
            res = run_checks(self.path.get(), prof)
            self.after(0, lambda: self.done(res))
        except Exception as ex:
            msg = f"{type(ex).__name__}: {ex}"
            self.after(0, lambda: self.fail(msg, traceback.format_exc()))

    def fail(self, msg, tb):
        self.prog.stop(); self.run_btn.state(["!disabled"]); self.summary.config(text="Failed: " + msg)
        messagebox.showerror("StructCheck", msg + "\n\nIf this is a DWG, save it as DXF first.")

    def done(self, res):
        self.prog.stop(); self.run_btn.state(["!disabled"]); self.result = res
        s = res.summary()
        lines = [f"v{__version__} | {self._capabilities()}", f"{res.drawing['filename']}  |  units: {res.drawing['unit_source']}  |  source unchanged: {res.integrity['unchanged']}",
                 f"Errors {s['errors']}   Warnings {s['warnings']}   Review {s['review']}   Not-checked items {s['not_checked_items']}   "
                 f"Rules completed {s['rules_completed']}/8, partial {s['rules_partial']}, skipped {s['rules_skipped']}"]
        lines.append("  ".join(f"R{r['rule']}:{r['status'][:4]}" for r in res.rules))
        if res.drawing["unsupported_entities"] or res.drawing["limitations"]:
            lines.append("Limitations: " + "; ".join(res.drawing["limitations"][:2]) + ("  Unsupported: " + str(res.drawing["unsupported_entities"]) if res.drawing["unsupported_entities"] else ""))
        self.summary.config(text="\n".join(lines)); self.fill()

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        if not self.result:
            return
        order = {"ERROR": 0, "WARNING": 1, "REVIEW": 2, "NOT CHECKED": 3}
        for f in sorted(self.result.findings, key=lambda f: (order[f.severity.value], f.rule)):
            if self.sev_filter.get() != "All" and f.severity.value != self.sev_filter.get(): continue
            if self.rule_filter.get() != "All" and str(f.rule) != self.rule_filter.get(): continue
            self.tree.insert("", "end", iid=f.id, tags=(f.severity.value,),
                             values=(f.id, f.severity.value, f.rule, f.identifier or "", f.layout or "", f.description, f.confidence))

    def show_detail(self, _):
        sel = self.tree.selection()
        if not sel: return
        f = next(x for x in self.result.findings if x.id == sel[0])
        self.detail.delete("1.0", "end")
        bb = ", ".join(f"{v:.0f}" for v in f.bbox) if f.bbox else "location not determined"
        self.detail.insert("end", f"{f.id}  [{f.severity.value}]  confidence {f.confidence}\n{f.description}\n\n{f.explanation}\n\n"
                           f"Expected: {f.expected}   Detected: {f.detected}   Difference: {f.difference}\n"
                           f"Layout: {f.layout}   Schedule: {f.schedule_ref}\nEntity handles: {', '.join(f.entity_handles)}\n"
                           f"Location (minx,miny,maxx,maxy): {bb}\nReason: {f.reason}\nAction: {f.recommended_action}")

    def mark(self, kind):
        """Circles on the drawing: written to a NEW file; the original is never touched."""
        if not self.result:
            messagebox.showinfo("StructCheck", "Run the checks first."); return
        from . import review
        stem = os.path.splitext(os.path.basename(self.path.get()))[0]
        out = filedialog.asksaveasfilename(defaultextension="." + kind, initialfile=f"{stem}_REVIEW.{kind}")
        if not out:
            return
        if os.path.abspath(out) == os.path.abspath(self.path.get()):
            messagebox.showerror("StructCheck", "Choose a different file name - the original drawing is never overwritten."); return
        sev = ("ERROR",) if self.only_err.get() else review.MARKABLE
        unit = self.result.drawing["unit_mm_per_drawing_unit"]
        self.prog.start(12); self.summary.config(text="Writing marked " + kind.upper() + " (a PDF of a big drawing can take a minute)...")
        def work():
            try:
                if kind == "dxf":
                    n, sk = review.mark_dxf(self.path.get(), self.result.findings, out, unit, sev)
                    msg = f"{n} circles written.\n{len(sk)} findings have no reliable location and are not circled.\n\n{out}"
                else:
                    import tempfile
                    tmp = os.path.join(tempfile.mkdtemp(prefix="sc_"), "marked.dxf")
                    review.mark_dxf(self.path.get(), self.result.findings, tmp, unit, sev)
                    n, extra = review.mark_pdf(tmp, self.result.findings, out, unit, severities=sev)
                    msg = f"PDF written with {n} marked findings (overview + zoom pages).\n\n{out}"
                self.after(0, lambda: (self.prog.stop(), messagebox.showinfo("StructCheck", msg)))
            except Exception as ex:
                err = f"{type(ex).__name__}: {ex}"
                self.after(0, lambda: (self.prog.stop(), messagebox.showerror("StructCheck", err)))
        threading.Thread(target=work, daemon=True).start()

    def export(self, fmt):
        if not self.result:
            messagebox.showinfo("StructCheck", "Run the checks first."); return
        stem = os.path.splitext(os.path.basename(self.path.get()))[0]
        p = filedialog.asksaveasfilename(defaultextension="." + fmt, initialfile=f"{stem}_report.{fmt}")
        if p:
            getattr(export, "to_" + fmt)(self.result, p)
            messagebox.showinfo("StructCheck", "Saved:\n" + p)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
