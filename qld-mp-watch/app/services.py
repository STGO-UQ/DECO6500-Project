from __future__ import annotations

from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import PARLIAMENT_START
from .models import Attendance, Division, DivisionVote, Donation, Member, SittingDay


def date_bounds(from_: date | None, to: date | None):
    start = from_ or datetime.strptime(PARLIAMENT_START, "%Y-%m-%d").date()
    end = to or date.today()
    return start, end


def _member_bounds(db: Session, member_id: int, from_: date | None, to: date | None):
    start, end = date_bounds(from_, to)
    member = db.get(Member, member_id)
    if member and member.term_start and member.term_start > start:
        start = member.term_start
    return member, start, end


def attendance_summary(db: Session, member_id: int, from_: date | None = None, to: date | None = None):
    member, start, end = _member_bounds(db, member_id, from_, to)
    days = db.scalars(
        select(SittingDay)
        .where(
            SittingDay.date.between(start, end),
            SittingDay.scrape_status.in_(["ok", "partial"]),
        )
        .order_by(SittingDay.date)
    ).all()
    present_by_day = {
        a.sitting_day_id: a
        for a in db.scalars(
            select(Attendance)
            .join(SittingDay)
            .where(Attendance.member_id == member_id, SittingDay.date.between(start, end))
        ).all()
    }

    # A recorded Aye/No is positive evidence that the member was in the chamber for that division.
    # Pairs are deliberately excluded: a pair is not a cast vote and should not prove presence.
    vote_dates = set(
        db.scalars(
            select(Division.sitting_date)
            .join(DivisionVote, DivisionVote.division_id == Division.id)
            .where(
                DivisionVote.member_id == member_id,
                DivisionVote.choice.in_(["aye", "no"]),
                Division.sitting_date.between(start, end),
            )
            .distinct()
        ).all()
    )

    details = []
    present = 0
    official_present = 0
    vote_rescued = 0
    denominator_dates = {day.date for day in days}
    for day in days:
        listed = day.id in present_by_day
        voted = day.date in vote_dates
        is_present = listed or voted
        present += int(is_present)
        official_present += int(listed)
        vote_rescued += int(voted and not listed)
        if listed:
            status = "present"
            method = "official_attendance_list"
        elif voted:
            status = "present_vote_confirmed"
            method = "division_vote"
        else:
            status = "not_listed"
            method = "official_attendance_list"
        details.append({
            "date": day.date.isoformat(),
            "status": status,
            "listed_in_attendance": listed,
            "voted_in_division": voted,
            "evidence_method": method,
            "evidence_url": day.evidence_url,
            "source": "Queensland Parliament Record of Proceedings / Hansard",
        })

    total = len(days)
    rate = round((present / total * 100), 1) if total else None
    outside = sorted(d for d in vote_dates if d not in denominator_dates)
    return {
        "member_id": member_id,
        "present_sitting_days": present,
        "official_listed_days": official_present,
        "vote_confirmed_corrections": vote_rescued,
        "total_sitting_days": total,
        "attendance_rate": rate,
        "days": details,
        "additional_vote_confirmed_days": [d.isoformat() for d in outside],
        "coverage_note": (
            "The denominator includes only sitting days with a successfully parsed official ATTENDANCE list. "
            "A recorded Aye/No vote can confirm presence if a member was not matched in that list. "
            "Failure to vote is never treated as proof of absence, and paired members are not treated as present."
        ),
    }


def division_summary(db: Session, member_id: int, from_: date | None = None, to: date | None = None, limit: int = 100):
    member, start, end = _member_bounds(db, member_id, from_, to)
    divisions = db.scalars(
        select(Division)
        .where(Division.sitting_date.between(start, end))
        .order_by(Division.sitting_date.desc(), Division.sequence.desc())
    ).all()
    votes = db.scalars(
        select(DivisionVote)
        .join(Division)
        .where(
            DivisionVote.member_id == member_id,
            Division.sitting_date.between(start, end),
        )
    ).all()
    by_division = {v.division_id: v for v in votes}

    aye = sum(1 for v in votes if v.choice == "aye")
    no = sum(1 for v in votes if v.choice == "no")
    pairs = sum(1 for v in votes if v.choice == "pair")
    ballots = aye + no
    total = len(divisions)
    rate = round(ballots / total * 100, 1) if total else None
    vote_confirmed_days = len({v.division.sitting_date for v in votes if v.choice in ("aye", "no")})

    rows = []
    for div in divisions[:limit]:
        vote = by_division.get(div.id)
        rows.append({
            "division_id": div.id,
            "date": div.sitting_date.isoformat(),
            "sequence": div.sequence,
            "context": div.context,
            "question": div.question,
            "result": div.result,
            "ayes_count": div.ayes_count,
            "noes_count": div.noes_count,
            "pair_count": div.pair_count,
            "choice": vote.choice if vote else None,
            "source_token": vote.source_token if vote else None,
            "evidence_url": div.evidence_url,
        })

    return {
        "member_id": member_id,
        "total_divisions": total,
        "ballots_cast": ballots,
        "ayes": aye,
        "noes": no,
        "paired": pairs,
        "no_vote_recorded": max(0, total - ballots - pairs),
        "participation_rate": rate,
        "vote_confirmed_sitting_days": vote_confirmed_days,
        "divisions": rows,
        "participation_note": (
            "Voting participation is Aye/No ballots cast divided by recorded divisions held while the member was in office. "
            "A missing vote does not prove the member was absent. Pair records are shown separately and do not count as a cast ballot."
        ),
    }


def donation_summary(db: Session, member_id: int, from_: date | None = None, to: date | None = None, limit: int = 100):
    start, end = date_bounds(from_, to)
    q = select(Donation).where(Donation.member_id == member_id)
    q = q.where((Donation.gift_date == None) | Donation.gift_date.between(start, end)).order_by(Donation.gift_date.desc().nullslast(), Donation.amount.desc())  # noqa: E711
    gifts = db.scalars(q.limit(limit)).all()
    all_rows = db.scalars(q).all()
    total = sum(x.amount for x in all_rows)
    reconciled = sum(x.amount for x in all_rows if (x.reconciliation_status or "").casefold().startswith("recon"))
    unreconciled = sum(x.amount for x in all_rows if (x.reconciliation_status or "").casefold().startswith("unrecon"))
    return {
        "member_id": member_id,
        "total": round(total, 2),
        "reconciled_total": round(reconciled, 2),
        "unreconciled_total": round(unreconciled, 2),
        "count": len(all_rows),
        "gifts": [{
            "id": x.id, "donor": x.donor, "recipient": x.recipient,
            "value": x.amount, "date": x.gift_date.isoformat() if x.gift_date else None,
            "election": x.election, "political_donation": x.political_donation,
            "reconciliation_status": x.reconciliation_status, "electorate": x.electorate,
            "source_url": x.source_url,
        } for x in gifts],
        "attribution_note": "Party-level gifts are not allocated to individual MPs. Totals include only disclosures matched to the member/candidate or their electorate/electoral committee.",
    }


def member_card(db: Session, m: Member, from_: date | None = None, to: date | None = None):
    a = attendance_summary(db, m.id, from_, to)
    v = division_summary(db, m.id, from_, to, limit=5)
    d = donation_summary(db, m.id, from_, to, limit=5)
    return {
        "id": m.id, "name": m.full_name, "electorate": m.electorate, "party": m.party,
        "role": m.role, "parliament_url": m.parliament_url, "term_start": m.term_start.isoformat() if m.term_start else None,
        "attendance_rate": a["attendance_rate"], "present_sitting_days": a["present_sitting_days"],
        "total_sitting_days": a["total_sitting_days"], "vote_confirmed_corrections": a["vote_confirmed_corrections"],
        "voting_participation_rate": v["participation_rate"], "ballots_cast": v["ballots_cast"],
        "total_divisions": v["total_divisions"], "paired_divisions": v["paired"],
        "donations_total": d["total"], "donations_count": d["count"],
    }
