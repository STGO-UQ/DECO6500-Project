from __future__ import annotations

import hashlib
import io
import re
import time
from datetime import date, datetime

from pypdf import PdfReader
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import PARLIAMENT_START
from ..models import Division, DivisionVote, Member, SittingDay
from .attendance import discover_hansard_links, download_pdf, probe_hansard_links
from .common import norm, stable_key

DIVISION_MARKER_RE = re.compile(r"(?i)\bDivision:\s*Question\s+put\s*[—–-]\s*")
AYES_RE = re.compile(r"(?i)\bAYES\s*,\s*(\d+)\s*:\s*")
NOES_RE = re.compile(r"(?i)\bNOES\s*,\s*(\d+)\s*:\s*")
PAIR_RE = re.compile(r"(?i)\bPairs?\s*:\s*")
RESULT_RE = re.compile(r"(?i)\bResolved\s+in\s+the\s+(affirmative|negative)\b")
PARTY_PREFIX_RE = re.compile(r"(?i)(?:^|\s)(?:ALP|LNP|Grn|Greens?|KAP|Ind|Independent)\s*,\s*\d+\s*[—–-]\s*")
PAGE_NOISE_RE = re.compile(
    r"(?im)^\s*(?:\d+\s+.+?\s+\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2}|\d{1,2}\s+[A-Z][a-z]{2}\s+20\d{2}\s+.+?\s+\d+)\s*$"
)


def extract_pdf_pages(pdf_bytes: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(p.extract_text() or "") for p in reader.pages]


def _clean_question(value: str) -> str:
    value = PAGE_NOISE_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" .\n\t")
    return value[:2000]


def _nearest_context(text: str, start: int) -> str | None:
    """Best-effort section/bill title preceding a division.

    Hansard commonly prints the bill/motion heading in uppercase above the division.
    Context is descriptive only; the official question remains the authoritative field.
    """
    window = text[max(0, start - 3500):start]
    lines = [re.sub(r"\s+", " ", x).strip() for x in window.splitlines()]
    candidates: list[str] = []
    for line in lines:
        if not (4 <= len(line) <= 260):
            continue
        if re.search(r"\b(?:AYES|NOES|ATTENDANCE|Resolved in the|Division:)\b", line, re.I):
            continue
        letters = re.sub(r"[^A-Za-z]", "", line)
        if len(letters) < 4:
            continue
        # Headings can contain punctuation/numbers, but their alphabetic characters are uppercase.
        if letters == letters.upper():
            candidates.append(line)
    return candidates[-1][:500] if candidates else None


def _name_tokens(block: str) -> list[str]:
    block = PAGE_NOISE_RE.sub(" ", block)
    block = PARTY_PREFIX_RE.sub(", ", block)
    block = re.sub(r"\s+", " ", block).strip()
    out: list[str] = []
    for token in re.split(r"[,;]", block):
        token = token.strip(" .;:\n\t")
        if not token:
            continue
        # Current Hansard names are surnames, sometimes prefixed by an initial (e.g. B. James).
        if re.fullmatch(r"(?:[A-Z]\.?\s+)?[A-Za-z'’ -]{1,60}", token):
            out.append(token)
    return out


def parse_divisions(text: str) -> list[dict]:
    """Parse current-format Queensland Hansard division blocks.

    Returns question, context, Aye/No name tokens, pairs and result. Table-of-contents
    references are ignored because they do not contain the AYES/NOES blocks.
    """
    markers = list(DIVISION_MARKER_RE.finditer(text))
    divisions: list[dict] = []
    for index, marker in enumerate(markers):
        next_start = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        # Keep a generous cap so a long division list is retained without consuming a later debate.
        segment_end = min(next_start, marker.start() + 30000)
        segment = text[marker.end():segment_end]
        ayes_match = AYES_RE.search(segment)
        if not ayes_match:
            continue
        noes_match = NOES_RE.search(segment, ayes_match.end())
        if not noes_match:
            continue

        question = _clean_question(segment[:ayes_match.start()])
        if not question:
            continue

        after_noes = segment[noes_match.end():]
        pair_match = PAIR_RE.search(after_noes)
        result_match = RESULT_RE.search(after_noes)
        noes_stop_candidates = [m.start() for m in (pair_match, result_match) if m]
        noes_stop = min(noes_stop_candidates) if noes_stop_candidates else len(after_noes)
        ayes_block = segment[ayes_match.end():noes_match.start()]
        noes_block = after_noes[:noes_stop]

        pair_tokens: list[str] = []
        if pair_match:
            pair_tail = after_noes[pair_match.end():]
            pair_result = RESULT_RE.search(pair_tail)
            pair_block = pair_tail[:pair_result.start()] if pair_result else pair_tail[:500]
            pair_tokens = _name_tokens(pair_block)

        result = result_match.group(1).lower() if result_match else None
        divisions.append({
            "question": question,
            "context": _nearest_context(text, marker.start()),
            "ayes_count": int(ayes_match.group(1)),
            "noes_count": int(noes_match.group(1)),
            "ayes": _name_tokens(ayes_block),
            "noes": _name_tokens(noes_block),
            "pairs": pair_tokens,
            "result": result,
            "char_offset": marker.start(),
        })
    return divisions


def _vote_norm(value: str) -> str:
    value = norm(value).replace(".", "")
    return re.sub(r"\s+", " ", value).strip()


def _member_vote_lookup(db: Session) -> dict[str, Member]:
    members = db.scalars(select(Member).where(Member.is_current == True)).all()  # noqa: E712
    lookup: dict[str, Member] = {}
    for m in members:
        alias = (m.attendance_alias or "").strip()
        if not alias:
            continue
        lookup[_vote_norm(alias)] = m
        # Attendance duplicate aliases are stored as "James B" while divisions use "B. James".
        match = re.fullmatch(r"(.+?)\s+([A-Z])", alias)
        if match:
            lookup[_vote_norm(f"{match.group(2)}. {match.group(1)}")] = m
    return lookup


def ingest_division_document(db: Session, sitting_date: date, url: str, pdf_bytes: bytes) -> tuple[int, int, list[str]]:
    pages = extract_pdf_pages(pdf_bytes)
    text = "\n".join(pages)
    parsed = parse_divisions(text)
    if not parsed:
        return 0, 0, []

    # Ensure the date exists in the sitting-day catalogue without pretending the attendance list was parsed.
    day = db.scalar(select(SittingDay).where(SittingDay.date == sitting_date))
    if not day:
        day = SittingDay(date=sitting_date, evidence_url=url, scrape_status="vote_only", attendance_count=0)
        db.add(day)
    elif day.scrape_status not in ("ok", "partial"):
        day.scrape_status = "vote_only"
    day.evidence_url = url
    day.document_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    day.scraped_at = datetime.utcnow()
    db.flush()

    lookup = _member_vote_lookup(db)
    # Replace divisions from this date. Hansard records are immutable once finalised, and this
    # keeps re-runs idempotent if parsing improves.
    existing = db.scalars(select(Division).where(Division.sitting_date == sitting_date)).all()
    for div in existing:
        db.delete(div)
    db.flush()

    unmatched: list[str] = []
    vote_rows = 0
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    for seq, item in enumerate(parsed, start=1):
        div = Division(
            source_key=stable_key(sitting_date, seq, item["question"]),
            sitting_date=sitting_date,
            sequence=seq,
            question=item["question"],
            context=item.get("context"),
            result=item.get("result"),
            evidence_url=url,
            document_sha256=sha,
            ayes_count=item.get("ayes_count", 0),
            noes_count=item.get("noes_count", 0),
            pair_count=len(item.get("pairs", [])),
        )
        db.add(div)
        db.flush()

        seen_members: set[int] = set()
        for choice, tokens in (("aye", item["ayes"]), ("no", item["noes"]), ("pair", item["pairs"])):
            for token in tokens:
                member = lookup.get(_vote_norm(token))
                if not member:
                    unmatched.append(f"{sitting_date} division {seq}: {token}")
                    continue
                if member.id in seen_members:
                    continue
                seen_members.add(member.id)
                db.add(DivisionVote(division_id=div.id, member_id=member.id, choice=choice, source_token=token))
                vote_rows += 1

    db.commit()
    return len(parsed), vote_rows, unmatched


def scrape_votes(db: Session, start: date | None = None, end: date | None = None, probe_if_needed: bool = True) -> dict:
    start = start or datetime.strptime(PARLIAMENT_START, "%Y-%m-%d").date()
    end = end or date.today()
    links = {d: u for d, u in discover_hansard_links().items() if start <= d <= end}
    if not links and probe_if_needed:
        links = probe_hansard_links(start, end)

    documents = divisions = vote_rows = 0
    errors: list[str] = []
    for d, url in sorted(links.items()):
        try:
            content = download_pdf(url)
            n_div, n_votes, unmatched = ingest_division_document(db, d, url, content)
            documents += 1
            divisions += n_div
            vote_rows += n_votes
            if unmatched:
                errors.append(f"{d}: unmatched division tokens: {', '.join(unmatched[:10])}")
        except Exception as exc:
            errors.append(f"{d}: {exc}")
        time.sleep(0.12)
    return {
        "documents": documents,
        "divisions": divisions,
        "vote_rows": vote_rows,
        "discovered": len(links),
        "errors": errors,
    }
