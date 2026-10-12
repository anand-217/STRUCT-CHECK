"""Identifier normalisation. Strict key is always used; the loose key (B-1 == B01 == B1)
is only used to MATCH when the engineer allows it, otherwise it only raises REVIEW findings."""
import re

def strict_key(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").upper().replace("\u00a0", " "))

def loose_key(s: str) -> str:
    k = strict_key(s)
    k = re.sub(r"[-_.]", "", k)
    return re.sub(r"(?<=[A-Z])0+(?=\d)", "", k)

def match_key(s: str, profile) -> str:
    k = strict_key(s)
    if profile.hyphen_equivalent:
        k = re.sub(r"[-_.]", "", k)
    if profile.leading_zero_equivalent:
        k = re.sub(r"(?<=[A-Z])0+(?=\d)", "", k)
    return k

def is_blank(v) -> bool:
    return v is None or strict_key(v) in ("", "-", "--", "—", "NIL", "N/A", "NA", "?")

def first_number(s):
    m = re.search(r"\d+(?:\.\d+)?", s or "")
    return float(m.group()) if m else None
