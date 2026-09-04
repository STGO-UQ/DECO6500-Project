from __future__ import annotations
import json
import re
from collections import Counter
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import MEMBERS_URL, USER_AGENT, ROOT
from ..models import Member
from .common import compact_name, norm, parse_date

PARTY_MAP = {"ALP": "Labor", "LNP": "LNP", "GRN": "Greens", "KAP": "KAP", "IND": "Independent"}
TERM_START_OVERRIDES = {"hinchinbrook": "2025-12-09", "stafford": "2026-06-02"}


def _surname(full_name: str) -> str:
    name = compact_name(full_name)
    parts = name.split()
    if len(parts) >= 2 and parts[-2].casefold() == "de":
        return f"de {parts[-1]}"
    return parts[-1] if parts else name


def assign_attendance_aliases(rows: list[dict]) -> list[dict]:
    surnames = [_surname(r["full_name"]) for r in rows]
    counts = Counter(norm(x) for x in surnames)
    for row, surname in zip(rows, surnames):
        if counts[norm(surname)] > 1:
            given = compact_name(row["full_name"]).split()[0]
            row["attendance_alias"] = f"{surname} {given[0].upper()}"
        else:
            row["attendance_alias"] = surname
    return rows


def parse_member_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    # Works against the current Parliament page's rendered text and is deliberately
    # tolerant of titles/roles between the party marker and the next member.
    pattern = re.compile(
        r"(?P<name>(?:Hon\s+)?(?:Mr|Mrs|Ms|Miss|Dr)\s+.+?)\s+Member for\s+"
        r"(?P<electorate>[A-Za-z][A-Za-z '\-]+?)\s+\((?P<party>ALP|LNP|GRN|KAP|IND)\)",
        re.I,
    )
    out = []
    seen = set()
    for m in pattern.finditer(text):
        electorate = re.sub(r"\s+", " ", m.group("electorate")).strip()
        key = norm(electorate)
        if key in seen:
            continue
        seen.add(key)
        name = re.sub(r"^(Hon\s+)?(Mr|Mrs|Ms|Miss|Dr)\s+", "", m.group("name"), flags=re.I).strip()
        out.append({
            "full_name": name,
            "electorate": electorate,
            "party": PARTY_MAP.get(m.group("party").upper(), m.group("party").upper()),
            "parliament_url": MEMBERS_URL,
        })
    return assign_attendance_aliases(out)


def load_bootstrap() -> list[dict]:
    path = ROOT / "data" / "bootstrap_members.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return assign_attendance_aliases(rows)


def fetch_members(timeout: int = 30) -> list[dict]:
    r = requests.get(MEMBERS_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    rows = parse_member_page(r.text)
    if len(rows) < 80:
        raise RuntimeError(f"Member parser only found {len(rows)} rows; refusing to replace current members")
    return rows


def upsert_members(db: Session, rows: list[dict]) -> int:
    current = {norm(m.electorate): m for m in db.scalars(select(Member)).all()}
    seen = set()
    written = 0
    for row in rows:
        key = norm(row["electorate"])
        seen.add(key)
        obj = current.get(key)
        if not obj:
            obj = Member(electorate=row["electorate"], full_name=row["full_name"], party=row["party"])
            db.add(obj)
        obj.full_name = row["full_name"]
        obj.party = row["party"]
        obj.parliament_url = row.get("parliament_url") or MEMBERS_URL
        obj.attendance_alias = row.get("attendance_alias")
        obj.role = row.get("role")
        if row.get("term_start"):
            obj.term_start = parse_date(row.get("term_start")) if isinstance(row.get("term_start"), str) else row.get("term_start")
        elif obj.term_start is None:
            obj.term_start = parse_date(TERM_START_OVERRIDES.get(key, "2024-11-26"))
        obj.is_current = True
        written += 1
    for key, obj in current.items():
        if key not in seen:
            obj.is_current = False
    db.commit()
    return written
