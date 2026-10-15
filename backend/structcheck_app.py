import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] != "--gui":
        from structcheck.cli import safe_main      # command-line mode (used by the AutoCAD add-on)
        sys.exit(safe_main(sys.argv[1:]))
    from structcheck.gui import main
    main()
