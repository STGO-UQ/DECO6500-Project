from __future__ import annotations
import csv
import io
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ECQ_CSV_URL, ECQ_MAP_URL, USER_AGENT
from ..models import Donation, Member
from .common import compact_name, norm, parse_date, parse_money, stable_key

HEADER_ALIASES = {
    "government_type": ["government type", "government", "jurisdiction"],
    "donor": ["donor", "donor name", "gift giver", "giver"],
    "recipient": ["recipient", "receiver", "gift recipient", "recipient name"],
    "gift_date": ["date gift made", "gift date", "date made", "date"],
    "amount": ["gift value", "amount", "value"],
    "election": ["election"],
    "political_donation": ["political donation?", "political donation", "is political donation"],
    "reconciliation_status": ["reconciliation status", "reconciled", "status"],
    "electorate": ["electoral committee", "electorate", "state electorate", "electoral district"],
    "recipient_type": ["recipient type", "receiver type"],
    "source_url": ["source url", "form url", "return url", "link"],
}


def _canonical_headers(fieldnames: list[str] | None) -> dict[str, str]:
    available = {norm(h): h for h in (fieldnames or [])}
    result = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if norm(alias) in available:
                result[canonical] = available[norm(alias)]
                break
    return result


def parse_ecq_csv(data: bytes | str) -> list[dict]:
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = _canonical_headers(reader.fieldnames)
    required = {"donor", "recipient", "amount"}
    if not required.issubset(headers):
        raise RuntimeError(f"ECQ CSV columns not recognised. Found: {reader.fieldnames}")
    rows = []
    for raw in reader:
        row = {k: (raw.get(v) or "").strip() for k, v in headers.items()}
        if not row.get("donor") and not row.get("recipient"):
            continue
        government_type = norm(row.get("government_type"))
        if government_type and government_type != "state":
            continue
        row["amount"] = parse_money(row.get("amount"))
        row["gift_date"] = parse_date(row.get("gift_date"))
        row["raw"] = raw
        rows.append(row)
    return rows


def download_ecq_csv_via_url(url: str, timeout: int = 120) -> bytes:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    return r.content


def download_ecq_csv_via_browser(headless: bool = True) -> bytes:
    """Use the ECQ public UI's CSV export without depending on undocumented internal endpoints."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed; run `pip install -r requirements.txt`") from exc
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(accept_downloads=True)
        page.goto(ECQ_MAP_URL, wait_until="networkidle", timeout=120_000)
        # Current EDS exposes a CSV action on the public gift table/map. Try direct
        # visible CSV first, then a Download menu followed by CSV.
        download = None
        try:
            with page.expect_download(timeout=20_000) as info:
                page.get_by_text("CSV", exact=True).first.click()
            download = info.value
        except Exception:
            try:
                page.get_by_text(re.compile("Download", re.I)).first.click()
                with page.expect_download(timeout=20_000) as info:
                    page.get_by_text("CSV", exact=True).first.click()
                download = info.value
            except Exception as exc:
                browser.close()
                raise RuntimeError("Could not trigger ECQ CSV export; the EDS UI may have changed") from exc
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = Path(f.name)
        download.save_as(str(path))
        content = path.read_bytes()
        path.unlink(missing_ok=True)
        browser.close()
        return content


def _member_matchers(db: Session):
    members = db.scalars(select(Member).where(Member.is_current == True)).all()  # noqa: E712
    by_electorate = {norm(m.electorate): m for m in members}
    by_name = []
    for m in members:
        cleaned = compact_name(m.full_name)
        variants = {norm(cleaned), norm(m.full_name)}
        # ECQ candidate records frequently omit preferred names in parentheses.
        by_name.append((m, {v for v in variants if v}))
    return members, by_electorate, by_name


def match_member(row: dict, db: Session | None = None, matchers=None) -> Member | None:
    if matchers is None:
        if db is None:
            raise ValueError("db or matchers is required")
        matchers = _member_matchers(db)
    _, by_electorate, by_name = matchers
    electorate = norm(row.get("electorate"))
    if electorate and electorate in by_electorate:
        return by_electorate[electorate]

    recipient = norm(compact_name(row.get("recipient")))
    recipient_type = norm(row.get("recipient_type"))
    # Do not attribute party-level gifts to an individual MP.
    if any(x in recipient_type for x in ("party", "associated entity")):
        return None
    if "liberal national party" in recipient or "australian labor party" in recipient or recipient == "queensland greens":
        return None
    for member, variants in by_name:
        if recipient in variants:
            return member
        # Accept candidate-style labels containing the member's full cleaned name.
        if any(v and v in recipient for v in variants):
            return member
    return None


def ingest_donations(db: Session, rows: list[dict]) -> dict:
    written = matched = 0
    matchers = _member_matchers(db)
    existing = {d.source_key: d for d in db.scalars(select(Donation)).all()}
    for row in rows:
        key = stable_key(
            row.get("donor"), row.get("recipient"), row.get("gift_date"), row.get("amount"),
            row.get("election"), row.get("electorate"), row.get("source_url")
        )
        obj = existing.get(key)
        if not obj:
            obj = Donation(source_key=key, donor=row.get("donor", ""), recipient=row.get("recipient", ""))
            db.add(obj)
            existing[key] = obj
            written += 1
        member = match_member(row, matchers=matchers)
        obj.donor = row.get("donor", "")
        obj.recipient = row.get("recipient", "")
        obj.gift_date = row.get("gift_date")
        obj.amount = float(row.get("amount") or 0)
        obj.election = row.get("election") or None
        obj.political_donation = row.get("political_donation") or None
        obj.reconciliation_status = row.get("reconciliation_status") or None
        obj.electorate = row.get("electorate") or None
        obj.recipient_type = row.get("recipient_type") or None
        obj.source_url = row.get("source_url") or ECQ_MAP_URL
        obj.raw_json = json.dumps(row.get("raw") or {}, ensure_ascii=False, default=str)
        obj.member_id = member.id if member else None
        obj.scraped_at = datetime.utcnow()
        matched += int(member is not None)
    db.commit()
    return {"seen": len(rows), "inserted": written, "matched_to_members": matched}


def scrape_donations(db: Session, csv_path: str | None = None, headless: bool = True) -> dict:
    if csv_path:
        content = Path(csv_path).read_bytes()
        source = csv_path
    elif ECQ_CSV_URL:
        content = download_ecq_csv_via_url(ECQ_CSV_URL)
        source = ECQ_CSV_URL
    else:
        content = download_ecq_csv_via_browser(headless=headless)
        source = "ECQ public CSV export"
    rows = parse_ecq_csv(content)
    result = ingest_donations(db, rows)
    result["source"] = source
    return result
