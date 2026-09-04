from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import PARLIAMENT_START
from .models import Attendance, Division, DivisionVote, Donation, Member, SittingDay
from .scrapers.common import norm


PARTY_ALIASES = {
    "LNP": (
        "liberal national party of queensland",
        "liberal national party of qld",
        "liberal national party",
        "lnp queensland",
        "lnp",
    ),
    "Labor": (
        "australian labor party (state of queensland)",
        "australian labor party state of queensland",
        "australian labor party",
        "australian labor party queensland branch",
        "queensland labor",
        "alp state of queensland",
    ),
    "Greens": (
        "queensland greens",
        "the greens queensland",
        "australian greens queensland",
    ),
    "KAP": (
        "katter's australian party (kap)",
        "katter's australian party",
        "katters australian party",
        "katter s australian party",
        "katters australian party queensland division",
    ),
}


def canonical_party(party: str | None) -> str | None:
    value = norm(party)
    if not value:
        return None
    if value in {"lnp", "liberal national party", "liberal national party of queensland"}:
        return "LNP"
    if value in {"labor", "alp", "australian labor party", "australian labor party state of queensland"}:
        return "Labor"
    if value in {"greens", "green", "queensland greens", "australian greens"}:
        return "Greens"
    if value in {"kap", "katters australian party", "katter s australian party"}:
        return "KAP"
    if "independent" in value:
        return "Independent"
    return party.strip() if party else None


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


def _donations_in_range(db: Session, from_: date | None, to: date | None) -> list[Donation]:
    start, end = date_bounds(from_, to)
    stmt = (
        select(Donation)
        .where((Donation.gift_date == None) | Donation.gift_date.between(start, end))  # noqa: E711
        .order_by(Donation.gift_date.desc().nullslast(), Donation.amount.desc())
    )
    return db.scalars(stmt).all()


def _party_from_donation(row: Donation) -> str | None:
    """Return a party only for party-level disclosures, never for an MP/candidate-linked gift."""
    if row.member_id is not None:
        return None

    recipient = norm(row.recipient)
    recipient_type = norm(row.recipient_type)

    # Explicit candidate/electoral-committee records should never become party funding merely
    # because a party abbreviation appears in the recipient label.
    if any(token in recipient_type for token in ("candidate", "electoral committee", "member")):
        return None

    # When ECQ supplies a recipient type, require it to identify a political party.
    is_party_type = "party" in recipient_type if recipient_type else False

    for party, aliases in PARTY_ALIASES.items():
        for alias in aliases:
            alias_n = norm(alias)
            if not alias_n:
                continue
            if is_party_type and alias_n in recipient:
                return party
            # Older/alternate CSV exports can omit recipient type. In that case be conservative:
            # accept only an exact or official-name-prefix match, not a loose candidate label.
            if not recipient_type and (recipient == alias_n or recipient.startswith(alias_n + " ")):
                return party
    return None


def _donor_summary(rows: list[Donation], limit: int = 20) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        key = norm(row.donor) or "unnamed donor"
        if key not in grouped:
            grouped[key] = {
                "donor": row.donor or "Unnamed donor",
                "total": 0.0,
                "count": 0,
                "latest_date": None,
            }
        item = grouped[key]
        item["total"] += float(row.amount or 0)
        item["count"] += 1
        if row.gift_date and (item["latest_date"] is None or row.gift_date > item["latest_date"]):
            item["latest_date"] = row.gift_date
    result = sorted(grouped.values(), key=lambda x: (-x["total"], x["donor"].casefold()))[:limit]
    for item in result:
        item["total"] = round(item["total"], 2)
        item["latest_date"] = item["latest_date"].isoformat() if item["latest_date"] else None
    return result


def _gift_rows(rows: list[Donation], limit: int) -> list[dict]:
    return [{
        "id": x.id,
        "donor": x.donor,
        "recipient": x.recipient,
        "value": x.amount,
        "date": x.gift_date.isoformat() if x.gift_date else None,
        "election": x.election,
        "political_donation": x.political_donation,
        "reconciliation_status": x.reconciliation_status,
        "electorate": x.electorate,
        "recipient_type": x.recipient_type,
        "source_url": x.source_url,
    } for x in rows[:limit]]


def donation_summary(db: Session, member_id: int, from_: date | None = None, to: date | None = None, limit: int = 100):
    start, end = date_bounds(from_, to)
    q = select(Donation).where(Donation.member_id == member_id)
    q = q.where((Donation.gift_date == None) | Donation.gift_date.between(start, end)).order_by(Donation.gift_date.desc().nullslast(), Donation.amount.desc())  # noqa: E711
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
        "donor_count": len({norm(x.donor) for x in all_rows if norm(x.donor)}),
        "donors": _donor_summary(all_rows, limit=min(limit, 25)),
        "gifts": _gift_rows(all_rows, limit),
        "attribution_note": (
            "These totals include only disclosures matched to this member/candidate or their electorate/electoral committee. "
            "Party-level gifts are excluded from the member total and are reported separately as party funding context."
        ),
    }


def party_funding_totals(db: Session, from_: date | None = None, to: date | None = None) -> dict[str, dict]:
    totals = {party: {"total": 0.0, "count": 0} for party in PARTY_ALIASES}
    for row in _donations_in_range(db, from_, to):
        party = _party_from_donation(row)
        if party in totals:
            totals[party]["total"] += float(row.amount or 0)
            totals[party]["count"] += 1
    for value in totals.values():
        value["total"] = round(value["total"], 2)
    totals["Independent"] = {"total": 0.0, "count": 0}
    return totals


def party_funding_summary(
    db: Session,
    party: str,
    from_: date | None = None,
    to: date | None = None,
    limit: int = 50,
    donor_limit: int = 20,
):
    canonical = canonical_party(party)
    if canonical not in PARTY_ALIASES:
        return {
            "party": canonical or party,
            "total": 0.0,
            "count": 0,
            "donor_count": 0,
            "reconciled_total": 0.0,
            "unreconciled_total": 0.0,
            "donors": [],
            "gifts": [],
            "attribution_note": (
                "No party-wide funding is assigned to independent MPs. Direct/candidate-linked disclosures remain available separately."
            ),
        }

    rows = [row for row in _donations_in_range(db, from_, to) if _party_from_donation(row) == canonical]
    total = sum(float(x.amount or 0) for x in rows)
    reconciled = sum(float(x.amount or 0) for x in rows if (x.reconciliation_status or "").casefold().startswith("recon"))
    unreconciled = sum(float(x.amount or 0) for x in rows if (x.reconciliation_status or "").casefold().startswith("unrecon"))
    return {
        "party": canonical,
        "total": round(total, 2),
        "count": len(rows),
        "donor_count": len({norm(x.donor) for x in rows if norm(x.donor)}),
        "reconciled_total": round(reconciled, 2),
        "unreconciled_total": round(unreconciled, 2),
        "donors": _donor_summary(rows, donor_limit),
        "gifts": _gift_rows(rows, limit),
        "attribution_note": (
            f"These disclosures were made to {canonical} as a party, not personally to this MP. "
            "They are shown only as party-wide political funding context and are not apportioned among MPs."
        ),
    }


def member_card(
    db: Session,
    m: Member,
    from_: date | None = None,
    to: date | None = None,
    party_context: dict[str, dict] | None = None,
):
    a = attendance_summary(db, m.id, from_, to)
    v = division_summary(db, m.id, from_, to, limit=5)
    d = donation_summary(db, m.id, from_, to, limit=5)
    canonical = canonical_party(m.party) or m.party
    context = (party_context or {}).get(canonical)
    if context is None:
        context = party_funding_summary(db, canonical, from_, to, limit=0, donor_limit=0)
    return {
        "id": m.id,
        "name": m.full_name,
        "electorate": m.electorate,
        "party": m.party,
        "role": m.role,
        "parliament_url": m.parliament_url,
        "term_start": m.term_start.isoformat() if m.term_start else None,
        "attendance_rate": a["attendance_rate"],
        "present_sitting_days": a["present_sitting_days"],
        "total_sitting_days": a["total_sitting_days"],
        "vote_confirmed_corrections": a["vote_confirmed_corrections"],
        "voting_participation_rate": v["participation_rate"],
        "ballots_cast": v["ballots_cast"],
        "total_divisions": v["total_divisions"],
        "paired_divisions": v["paired"],
        "donations_total": d["total"],
        "donations_count": d["count"],
        "party_funding_total": context.get("total", 0.0),
        "party_funding_count": context.get("count", 0),
    }
