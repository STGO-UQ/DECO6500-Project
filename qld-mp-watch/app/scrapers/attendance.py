from __future__ import annotations
import hashlib
import io
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import DATA_DIR, HANSARD_BROWSE_URLS, HANSARD_DOC_BASE, PARLIAMENT_START, USER_AGENT
from ..models import Attendance, Member, SittingDay
from .common import norm

PDF_RE = re.compile(r"https?://documents\.parliament\.qld\.gov\.au/events/han/(20\d{2})/(20\d{2}_\d{2}_\d{2})_(DAILY|WEEKLY)\.pdf", re.I)


def discover_hansard_links(timeout: int = 30) -> dict[date, str]:
    links: dict[date, str] = {}
    for browse_url in HANSARD_BROWSE_URLS:
        try:
            r = requests.get(browse_url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            candidates = [a.get("href") for a in soup.find_all("a", href=True)]
            for href in candidates:
                if not isinstance(href, str):
                    continue
                absolute = urljoin(browse_url, href)
                m = PDF_RE.search(absolute)
                if not m:
                    continue
                d = datetime.strptime(m.group(2), "%Y_%m_%d").date()
                if d not in links or "_DAILY.pdf" in absolute:
                    links[d] = absolute
        except requests.RequestException:
            continue
    return links


def probe_hansard_links(start: date, end: date, timeout: int = 12) -> dict[date, str]:
    links: dict[date, str] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    d = start
    while d <= end:
        # The Assembly ordinarily sits Tue-Thu, but Fridays are included for unusual sittings.
        if d.weekday() in (1, 2, 3, 4):
            stem = d.strftime("%Y_%m_%d")
            for kind in ("DAILY", "WEEKLY"):
                url = f"{HANSARD_DOC_BASE}/{d.year}/{stem}_{kind}.pdf"
                try:
                    r = session.get(url, timeout=timeout, stream=True)
                    ctype = r.headers.get("content-type", "")
                    if r.status_code == 200 and ("pdf" in ctype.lower() or r.url.lower().endswith(".pdf")):
                        links[d] = url
                        r.close()
                        break
                    r.close()
                except requests.RequestException:
                    continue
                time.sleep(0.12)
        d += timedelta(days=1)
    return links


def download_pdf(url: str, timeout: int = 45) -> bytes:
    # Hansard PDFs are immutable official records. Cache them locally so running the
    # attendance and division scrapers does not hit Parliament twice for the same file.
    cache_dir = DATA_DIR / "hansard_cache"
    cache_dir.mkdir(exist_ok=True)
    filename = url.rsplit("/", 1)[-1].split("?", 1)[0] or hashlib.sha256(url.encode()).hexdigest() + ".pdf"
    cache_path = cache_dir / filename
    if cache_path.exists():
        cached = cache_path.read_bytes()
        if cached.startswith(b"%PDF"):
            return cached
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise RuntimeError(f"Expected PDF from {url}")
    cache_path.write_bytes(r.content)
    return r.content


def extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    # The official ATTENDANCE section is at the end of the Record of Proceedings.
    # Reading only the tail makes historical backfills far faster and lighter.
    pages = reader.pages[max(0, len(reader.pages) - 8):]
    return "\n".join((p.extract_text() or "") for p in pages)


def parse_attendance_tokens(text: str) -> list[str]:
    # Attendance is printed at the end of the official Record of Proceedings.
    matches = list(re.finditer(r"(?mi)^\s*ATTENDANCE\s*$", text))
    if not matches:
        return []
    tail = text[matches[-1].end():]
    tail = tail[:5000]
    # Strip common extracted page header/footer fragments before tokenising.
    tail = re.sub(r"(?m)^\s*\d+\s+Attendance\s+\d+\s+\w+\s+\d{4}\s*$", "", tail)
    tail = re.sub(r"(?m)^\s*\d+\s+\w+\s+\d{4}\s+Attendance\s+\d+\s*$", "", tail)
    tail = tail.replace("\n", " ")
    tail = re.sub(r"\s+", " ", tail).strip()
    # An attendance list is comma-separated surnames, occasionally with an initial.
    raw = [re.sub(r"\s+", " ", x).strip(" .;:") for x in tail.split(",")]
    tokens = []
    for token in raw:
        token = re.sub(r"\s+", " ", token).strip()
        if not token:
            continue
        # Last token may have trailing unrelated text if a source format changes.
        token = re.split(r"\b(?:ISSN|RECORD OF PROCEEDINGS|Queensland Parliament)\b", token, maxsplit=1, flags=re.I)[0].strip()
        if 1 <= len(token) <= 60 and re.fullmatch(r"[A-Za-z'’ -]+(?:\s[A-Z])?", token):
            tokens.append(token)
    return tokens


def _member_lookup(db: Session):
    members = db.scalars(select(Member).where(Member.is_current == True)).all()  # noqa: E712
    by_alias = {norm(m.attendance_alias): m for m in members if m.attendance_alias}
    return members, by_alias


def ingest_attendance_document(db: Session, sitting_date: date, url: str, pdf_bytes: bytes) -> tuple[int, list[str]]:
    text = extract_pdf_text(pdf_bytes)
    tokens = parse_attendance_tokens(text)
    if not tokens:
        return 0, ["No ATTENDANCE list found"]
    members, by_alias = _member_lookup(db)
    matched: dict[int, str] = {}
    unmatched = []
    for token in tokens:
        m = by_alias.get(norm(token))
        if m:
            matched[m.id] = token
        else:
            unmatched.append(token)

    day = db.scalar(select(SittingDay).where(SittingDay.date == sitting_date))
    if not day:
        day = SittingDay(date=sitting_date, evidence_url=url)
        db.add(day)
        db.flush()
    day.evidence_url = url
    day.document_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    day.attendance_count = len(matched)
    day.scrape_status = "ok" if len(matched) >= max(1, len(members) - 15) else "partial"
    day.scraped_at = datetime.utcnow()
    db.execute(delete(Attendance).where(Attendance.sitting_day_id == day.id))
    for member_id, token in matched.items():
        db.add(Attendance(sitting_day_id=day.id, member_id=member_id, status="present", source_token=token))
    db.commit()
    return len(matched), unmatched


def scrape_attendance(db: Session, start: date | None = None, end: date | None = None, probe_if_needed: bool = True) -> dict:
    start = start or datetime.strptime(PARLIAMENT_START, "%Y-%m-%d").date()
    end = end or date.today()
    links = {d: u for d, u in discover_hansard_links().items() if start <= d <= end}
    if not links and probe_if_needed:
        links = probe_hansard_links(start, end)
    processed = matched = 0
    errors = []
    for d, url in sorted(links.items()):
        try:
            content = download_pdf(url)
            n, unmatched = ingest_attendance_document(db, d, url, content)
            processed += 1
            matched += n
            if unmatched:
                errors.append(f"{d}: unmatched attendance tokens: {', '.join(unmatched[:8])}")
        except Exception as exc:
            errors.append(f"{d}: {exc}")
        time.sleep(0.12)
    return {"documents": processed, "attendance_rows": matched, "errors": errors, "discovered": len(links)}
