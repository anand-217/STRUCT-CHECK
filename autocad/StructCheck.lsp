;;; ============================================================================
;;; StructCheck.lsp  -  runs StructCheck on the drawing that is open in AutoCAD
;;;
;;; Commands
;;;   SCHECK        export the open drawing to a temporary DXF, run StructCheck, draw the findings
;;;                 as circles/ellipses on layer STRUCTCHECK_REVIEW in THIS drawing and list them
;;;   SCHECKE       same, but circle ERROR findings only
;;;   SCHECKCLEAR   delete all StructCheck marks from the drawing (do this before issuing it)
;;;   SCHECKPDF     also write a marked PDF (overview + zoomed pages) and open it
;;;   SCHECKFOLDER  open the folder with the Excel/CSV/JSON reports
;;;   SCHECKSETUP   choose / change the location of StructCheck.exe
;;;
;;; Your drawing geometry is never edited: only entities on layer STRUCTCHECK_REVIEW are added
;;; (one UNDO removes them).  Reports go to <drawing folder>\StructCheck_Reports\.
;;; Needs the StructCheck.exe built from StructCheck v0.5 or later.
;;; ============================================================================

(setq sc:layer "STRUCTCHECK_REVIEW")
(setq sc:last-outdir nil sc:last-base nil sc:last-dxf nil)

;; ---------------------------------------------------------------- helpers
(defun sc:repl (s from to / i out ch)
  (setq i 1 out "")
  (while (<= i (strlen s))
    (setq ch (substr s i 1))
    (setq out (strcat out (if (= ch from) to ch)))
    (setq i (1+ i)))
  out)

(defun sc:fwd (s) (sc:repl s "\\" "/"))
(defun sc:bck (s) (sc:repl s "/" "\\"))

(defun sc:split (s ch / out i start)
  (setq out nil start 1 i 1)
  (while (<= i (strlen s))
    (if (= (substr s i 1) ch)
      (progn
        (setq out (cons (substr s start (- i start)) out))
        (setq start (1+ i))))
    (setq i (1+ i)))
  (reverse (cons (substr s start) out)))

(defun sc:cfgdir () (strcat (getenv "APPDATA") "\\StructCheck"))
(defun sc:cfgfile () (strcat (sc:cfgdir) "\\exe_path.txt"))

(defun sc:read-exe ( / f p)
  (if (findfile (sc:cfgfile))
    (progn
      (setq f (open (sc:cfgfile) "r"))
      (if f (progn (setq p (read-line f)) (close f)))
      (if (and p (findfile p)) p nil))
    nil))

(defun sc:save-exe (p / f)
  (vl-mkdir (sc:cfgdir))
  (setq f (open (sc:cfgfile) "w"))
  (if f (progn (write-line p f) (close f))))

(defun sc:ask-exe ( / p)
  (setq p (getfiled "Locate StructCheck.exe" "" "exe" 4))
  (if (and p (findfile p)) (progn (sc:save-exe p) p) nil))

(defun sc:get-exe () (or (sc:read-exe) (sc:ask-exe)))

(defun sc:base-name ( / n)
  (setq n (getvar "DWGNAME"))
  (if (and (> (strlen n) 4) (= (strcase (substr n (- (strlen n) 3))) ".DWG"))
    (substr n 1 (- (strlen n) 4))
    n))

(defun sc:outdir ( / d)
  (setq d (strcat (getvar "DWGPREFIX") "StructCheck_Reports\\"))
  (if (not (vl-file-directory-p d)) (vl-mkdir (substr d 1 (1- (strlen d)))))
  (if (not (vl-file-directory-p d))
    (progn
      (setq d (strcat (getenv "TEMP") "\\StructCheck\\"))
      (if (not (vl-file-directory-p d)) (vl-mkdir (substr d 1 (1- (strlen d)))))))
  d)

(defun sc:col (sev) (cond ((= sev "ERROR") 1) ((= sev "WARNING") 30) (T 40)))

(defun sc:ensure-layer ()
  (if (not (tblsearch "LAYER" sc:layer))
    (entmake (list '(0 . "LAYER") '(100 . "AcDbSymbolTableRecord") '(100 . "AcDbLayerTableRecord")
                   (cons 2 sc:layer) '(70 . 0) '(62 . 1) '(6 . "Continuous"))))
  (command "_.-LAYER" "_ON" sc:layer "_Thaw" sc:layer "_Unlock" sc:layer ""))

;; ---------------------------------------------------------------- drawing the marks
(defun sc:mk-circle (cx cy r col)
  (entmake (list '(0 . "CIRCLE") (cons 8 sc:layer) (cons 62 col) '(370 . 50) (list 10 cx cy 0.0) (cons 40 r))))

(defun sc:mk-ellipse (cx cy a b kind col / mx my ratio)
  (if (= kind "ELLIPSE_X")
    (setq mx a my 0.0 ratio (/ b a))
    (setq mx 0.0 my b ratio (/ a b)))
  (entmake (list '(0 . "ELLIPSE") '(100 . "AcDbEntity") (cons 8 sc:layer) (cons 62 col) '(370 . 50)
                 '(100 . "AcDbEllipse") (list 10 cx cy 0.0) (list 11 mx my 0.0) '(210 0.0 0.0 1.0)
                 (cons 40 ratio) '(41 . 0.0) (cons 42 6.283185307179586))))

(defun sc:mk-text (x y h txt col)
  (entmake (list '(0 . "TEXT") '(100 . "AcDbEntity") (cons 8 sc:layer) (cons 62 col) '(100 . "AcDbText")
                 (list 10 x y 0.0) (cons 40 h) (cons 1 txt))))

(defun sc:draw-marks (tsv / f line p kind sev cx cy a b h col n minx miny maxx maxy r)
  (setq n 0 f (open tsv "r"))
  (if f
    (progn
      (while (setq line (read-line f))
        (if (> (strlen line) 0)
          (progn
            (setq p (sc:split line (chr 9)))
            (setq sev (nth 1 p) kind (nth 2 p)
                  cx (atof (nth 3 p)) cy (atof (nth 4 p)) a (atof (nth 5 p)) b (atof (nth 6 p))
                  h (atof (nth 7 p)) col (sc:col sev))
            (if (= kind "CIRCLE")
              (progn (sc:mk-circle cx cy a col) (sc:mk-circle cx cy (* a 1.04) col))
              (sc:mk-ellipse cx cy a b kind col))
            (setq r (max a b))
            (sc:mk-text (+ cx (* r 1.08)) (+ cy (* r 0.4)) h (nth 0 p) col)
            (setq minx (if minx (min minx (- cx r)) (- cx r))
                  miny (if miny (min miny (- cy r)) (- cy r))
                  maxx (if maxx (max maxx (+ cx r)) (+ cx r))
                  maxy (if maxy (max maxy (+ cy r)) (+ cy r)))
            (setq n (1+ n)))))
      (close f)))
  (list n minx miny maxx maxy))

(defun c:SCHECKCLEAR ( / ss i n)
  (if (setq ss (ssget "_X" (list (cons 8 sc:layer))))
    (progn
      (setq n (sslength ss) i 0)
      (while (< i n) (entdel (ssname ss i)) (setq i (1+ i)))
      (princ (strcat "\nStructCheck: " (itoa n) " mark objects removed.")))
    (princ "\nStructCheck: no marks found."))
  (princ))

;; ---------------------------------------------------------------- running the exe
(defun sc:run (exe dxf outdir extra / args base summ errf secs)
  (setq base (sc:base-name))
  (setq summ (strcat outdir (sc:base-name) "_sc_summary.txt")
        errf (strcat outdir "structcheck_error.txt"))
  (if (findfile summ) (vl-file-delete summ))
  (if (findfile errf) (vl-file-delete errf))
  (setq args (strcat "\"" (sc:fwd dxf) "\" --out \"" (sc:fwd (substr outdir 1 (1- (strlen outdir)))) "\" --lisp --formats xlsx" extra))
  (if (findfile (strcat (getvar "DWGPREFIX") "structcheck_profile.json"))
    (setq args (strcat args " --profile \"" (sc:fwd (strcat (getvar "DWGPREFIX") "structcheck_profile.json")) "\"")))
  (startapp (strcat "\"" exe "\"") args)
  (setq secs 0)
  (princ "\nStructCheck is checking the drawing ")
  (while (and (not (findfile summ)) (not (findfile errf)) (< secs 340))
    (command "_.DELAY" 700)
    (setq secs (1+ secs))
    (if (= (rem secs 4) 0) (princ ".")))
  (cond
    ((findfile summ) summ)
    ((findfile errf)
     (alert (strcat "StructCheck could not finish. Details are in:\n" errf))
     nil)
    (T (alert "StructCheck did not answer within 4 minutes. Check that StructCheck.exe v0.5 or later is selected (SCHECKSETUP).") nil)))

(defun sc:export-dxf (dxf / oldfd)
  (setq oldfd (getvar "FILEDIA"))
  (setvar "FILEDIA" 0)
  (if (findfile dxf) (vl-file-delete dxf))
  (command "_.DXFOUT" (sc:fwd dxf) "16")
  (while (> (getvar "CMDACTIVE") 0) (command ""))
  (setvar "FILEDIA" oldfd)
  (findfile dxf))

(defun sc:read-summary (summ / f line p kv res findings rules)
  (setq f (open summ "r"))
  (while (and f (setq line (read-line f)))
    (setq p (sc:split line (chr 9)))
    (cond
      ((= (car p) "F") (setq findings (cons (cdr p) findings)))
      ((= (car p) "R") (setq rules (cons (cdr p) rules)))
      ((wcmatch line "*=*")
       (setq kv (sc:split line "="))
       (setq res (cons (cons (car kv) (cadr kv)) res)))))
  (if f (close f))
  (list res (reverse findings) (reverse rules)))

(defun sc:main (errors-only / *error* oldce oldfd exe base outdir dxf summ data kv fl rl marks i msg f r)
  (setq oldce (getvar "CMDECHO") oldfd (getvar "FILEDIA"))
  (defun *error* (m)
    (setvar "CMDECHO" oldce) (setvar "FILEDIA" oldfd)
    (if (and m (not (wcmatch (strcase m) "*CANCEL*,*QUIT*,*EXIT*")))
      (princ (strcat "\nStructCheck error: " m)))
    (princ))
  (setvar "CMDECHO" 0)
  (cond
    ((= (getvar "TILEMODE") 0)
     (alert "Please switch to the Model tab (marks are drawn in model space) and run the command again."))
    ((not (setq exe (sc:get-exe)))
     (princ "\nStructCheck: StructCheck.exe not selected. Run SCHECKSETUP."))
    (T
    (progn
      (setq base (sc:base-name) outdir (sc:outdir)
            dxf (strcat outdir base "_sc.dxf"))
      (princ "\nStructCheck: exporting the drawing to DXF...")
      (if (not (sc:export-dxf dxf))
        (alert "StructCheck could not export the drawing to DXF (DXFOUT). Export it manually and use the StructCheck window instead.")
        (progn
          (setq sc:last-outdir outdir sc:last-base base sc:last-dxf dxf)
          (setq summ (sc:run exe dxf outdir (if errors-only " --errors-only" "")))
          (if summ
            (progn
              (setq data (sc:read-summary summ) kv (car data) fl (cadr data) rl (caddr data))
              (c:SCHECKCLEAR)
              (sc:ensure-layer)
              (command "_.UNDO" "_Begin")
              (setq marks (sc:draw-marks (strcat outdir base "_sc_marks.tsv")))
              (command "_.UNDO" "_End")
              (if (car (cdr marks))
                (command "_.ZOOM" "_W"
                         (list (- (nth 1 marks) 2000.0) (- (nth 2 marks) 2000.0))
                         (list (+ (nth 3 marks) 2000.0) (+ (nth 4 marks) 2000.0))))
              (princ (strcat "\n\n=== StructCheck " (cdr (assoc "version" kv)) " ==="))
              (foreach r rl
                (princ (strcat "\n  Rule " (car r) ": " (cadr r) "  findings=" (caddr r) "  " (cadddr r))))
              (princ "\n")
              (setq i 0)
              (foreach f fl
                (if (< i 40)
                  (princ (strcat "\n  " (car f) "  [" (cadr f) "]  " (caddr f))))
                (setq i (1+ i)))
              (if (> i 40) (princ (strcat "\n  ... and " (itoa (- i 40)) " more (see the Excel report).")))
              (setq msg (strcat "StructCheck finished.\n\nErrors: " (cdr (assoc "errors" kv))
                                "\nWarnings: " (cdr (assoc "warnings" kv))
                                "\nReview: " (cdr (assoc "review" kv))
                                "\nNot-checked items: " (cdr (assoc "not_checked" kv))
                                "\n\nCircled in the drawing: " (itoa (car marks)) " marks (layer " sc:layer ")."
                                "\nUnmarked (no location): " (cdr (assoc "unmarked" kv))
                                "\n\nPress F2 for the full list. Reports: " outdir
                                "\nRun SCHECKCLEAR before issuing the drawing."))
              (alert msg))))))))
  (setvar "CMDECHO" oldce)
  (princ))

(defun c:SCHECK () (sc:main nil))
(defun c:SCHECKE () (sc:main T))

(defun c:SCHECKPDF ( / exe summ pdf)
  (if (not sc:last-dxf)
    (princ "\nStructCheck: run SCHECK first.")
    (progn
      (setq exe (sc:get-exe))
      (if exe
        (progn
          (princ "\nStructCheck: writing the marked PDF (can take a minute)...")
          (setq summ (sc:run exe sc:last-dxf sc:last-outdir " --mark"))
          (setq pdf (strcat sc:last-outdir sc:last-base "_sc_REVIEW.pdf"))
          (if (and summ (findfile pdf))
            (startapp "explorer" (strcat "\"" (sc:bck pdf) "\""))
            (princ "\nStructCheck: the PDF was not created (matplotlib missing in the .exe?).")))))
    )
  (princ))

(defun c:SCHECKFOLDER ()
  (if sc:last-outdir
    (startapp "explorer" (strcat "\"" (sc:bck (substr sc:last-outdir 1 (1- (strlen sc:last-outdir)))) "\""))
    (princ "\nStructCheck: run SCHECK first."))
  (princ))

(defun c:SCHECKSETUP ( / p)
  (setq p (sc:ask-exe))
  (if p (princ (strcat "\nStructCheck: using " p)) (princ "\nStructCheck: nothing selected."))
  (princ))

(vl-load-com)
(princ "\nStructCheck add-on loaded.  Commands: SCHECK  SCHECKE  SCHECKCLEAR  SCHECKPDF  SCHECKFOLDER  SCHECKSETUP")
(princ)
