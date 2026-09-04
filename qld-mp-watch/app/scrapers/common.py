from __future__ import annotations
import hashlib
import re
import unicodedata
from datetime import datetime


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.replace("’", "'").replace("–", "-")
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def compact_name(text: str | None) -> str:
    text = re.sub(r"\([^)]*\)", " ", text or "")
    text = re.sub(r"\b(hon|mr|mrs|ms|miss|dr|mp)\.?\b", " ", text, flags=re.I)
    text = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' -]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value: str | None):
    if not value:
        return None
    value = value.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def parse_money(value: str | None) -> float:
    if not value:
        return 0.0
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def stable_key(*parts: object) -> str:
    blob = "|".join(norm(str(p)) for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
