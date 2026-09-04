from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import ADMIN_TOKEN, ROOT
from .db import SessionLocal, get_db, init_db
from .models import Division, DivisionVote, Donation, Member, SittingDay
from .services import attendance_summary, division_summary, donation_summary, member_card
from .scrapers.boundaries import fetch_boundaries
from .scrapers.members import load_bootstrap, upsert_members

app = FastAPI(
    title="QLD MP Watch API",
    version="0.3.0",
    description="Queensland state MP sitting attendance, division voting and ECQ donation transparency API",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    init_db()
    db = SessionLocal()
    try:
        if not db.scalar(select(func.count(Member.id))):
            upsert_members(db, load_bootstrap())
    finally:
        db.close()


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    return {
        "ok": True,
        "members": db.scalar(select(func.count(Member.id)).where(Member.is_current == True)) or 0,  # noqa: E712
        "sitting_days": db.scalar(select(func.count(SittingDay.id))) or 0,
        "divisions": db.scalar(select(func.count(Division.id))) or 0,
        "division_votes": db.scalar(select(func.count(DivisionVote.id))) or 0,
        "donations": db.scalar(select(func.count(Donation.id))) or 0,
    }


@app.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    latest_day = db.scalar(
        select(func.max(SittingDay.date)).where(SittingDay.scrape_status.in_(["ok", "partial"]))
    )
    latest_division = db.scalar(select(func.max(Division.sitting_date)))
    latest_gift = db.scalar(select(func.max(Donation.gift_date)))
    return {
        "latest_attendance_date": latest_day.isoformat() if latest_day else None,
        "latest_division_date": latest_division.isoformat() if latest_division else None,
        "latest_gift_date": latest_gift.isoformat() if latest_gift else None,
        "attendance_method": (
            "Official Record of Proceedings ATTENDANCE list, supplemented only by positive Aye/No division evidence. "
            "Missing votes never imply absence."
        ),
        "voting_method": (
            "Official Hansard divisions. Participation is Aye/No ballots cast divided by recorded divisions during the member's tenure. "
            "Pairs are reported separately."
        ),
        "donation_method": (
            "ECQ public disclosure export; only member/candidate/electorate-matched gifts are attributed to an MP. "
            "Party-wide gifts are not apportioned."
        ),
        "ecq_caveat": "ECQ states EDS data appears as uploaded by users and may not be verified or validated before publication.",
    }


@app.get("/api/members")
def members(
    party: str | None = None,
    q: str | None = None,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Member).where(Member.is_current == True).order_by(Member.electorate)  # noqa: E712
    rows = db.scalars(stmt).all()
    if party and party.casefold() != "all":
        rows = [m for m in rows if m.party.casefold() == party.casefold()]
    if q:
        needle = q.casefold()
        rows = [m for m in rows if needle in m.full_name.casefold() or needle in m.electorate.casefold()]
    return [member_card(db, m, from_, to) for m in rows]


@app.get("/api/members/{member_id}")
def member_detail(member_id: int, db: Session = Depends(get_db)):
    m = db.get(Member, member_id)
    if not m:
        raise HTTPException(404, "Member not found")
    return member_card(db, m)


@app.get("/api/electorates/{electorate}/member")
def electorate_member(electorate: str, db: Session = Depends(get_db)):
    m = db.scalar(
        select(Member).where(func.lower(Member.electorate) == electorate.casefold(), Member.is_current == True)  # noqa: E712
    )
    if not m:
        raise HTTPException(404, "Electorate not found")
    return member_card(db, m)


@app.get("/api/members/{member_id}/attendance")
def member_attendance(
    member_id: int,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    db: Session = Depends(get_db),
):
    if not db.get(Member, member_id):
        raise HTTPException(404, "Member not found")
    return attendance_summary(db, member_id, from_, to)


@app.get("/api/members/{member_id}/votes")
def member_votes(
    member_id: int,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    if not db.get(Member, member_id):
        raise HTTPException(404, "Member not found")
    return division_summary(db, member_id, from_, to, limit)


@app.get("/api/divisions")
def divisions(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    stmt = select(Division).order_by(Division.sitting_date.desc(), Division.sequence.desc())
    if from_:
        stmt = stmt.where(Division.sitting_date >= from_)
    if to:
        stmt = stmt.where(Division.sitting_date <= to)
    rows = db.scalars(stmt.limit(limit)).all()
    return [{
        "id": d.id,
        "date": d.sitting_date.isoformat(),
        "sequence": d.sequence,
        "context": d.context,
        "question": d.question,
        "result": d.result,
        "ayes_count": d.ayes_count,
        "noes_count": d.noes_count,
        "pair_count": d.pair_count,
        "evidence_url": d.evidence_url,
    } for d in rows]


@app.get("/api/members/{member_id}/donations")
def member_donations(
    member_id: int,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    if not db.get(Member, member_id):
        raise HTTPException(404, "Member not found")
    return donation_summary(db, member_id, from_, to, limit)


@app.get("/api/electorates/geojson")
def electorate_geojson():
    try:
        return fetch_boundaries()
    except Exception as exc:
        raise HTTPException(502, f"Queensland boundary service unavailable: {exc}")


@app.post("/api/admin/scrape")
def run_scrape(
    kind: str = Query("all", pattern="^(all|members|attendance|votes|donations)$"),
    x_admin_token: str | None = Header(None),
    db: Session = Depends(get_db),
):
    if not ADMIN_TOKEN:
        raise HTTPException(403, "Admin scrape endpoint disabled; use the CLI")
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "Invalid admin token")
    from .cli import run_selected
    return run_selected(db, kind)


frontend = ROOT / "frontend"
app.mount("/assets", StaticFiles(directory=frontend), name="assets")


@app.get("/")
def index():
    return FileResponse(frontend / "index.html")
