"""Regenerates the sample drawings: python samples/build_samples.py (run from repo root, with backend on PYTHONPATH)."""
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "backend", "tests"))
from sample_factory import build, ALL_ERRORS
build(os.path.join(here, "sample_clean.dxf"))
build(os.path.join(here, "sample_with_errors.dxf"), ALL_ERRORS)
print("written")
