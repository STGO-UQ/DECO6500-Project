from __future__ import annotations

import argparse
from datetime import date, datetime
from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models import ScrapeRun
from .scrapers.attendance import scrape_attendance
from .scrapers.donations import scrape_donations
from .scrapers.members import fetch_members, load_bootstrap, upsert_members
from .scrapers.votes import scrape_votes


def _run(db: Session, name: str, fn):
    run = ScrapeRun(scraper=name)
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        result = fn()
        run.status = "ok"
        run.records_seen = int(result.get("seen", result.get("discovered", result.get("documents", 0))))
        run.records_written = int(
            result.get("inserted", result.get("attendance_rows", result.get("vote_rows", result.get("written", 0))))
        )
        run.message = str(result)[:5000]
        return result
    except Exception as exc:
        run.status = "error"
        run.message = str(exc)[:5000]
        raise
    finally:
        run.finished_at = datetime.utcnow()
        db.commit()


def run_selected(
    db: Session,
    kind: str,
    csv_path: str | None = None,
    start: date | None = None,
    end: date | None = None,
    headless: bool = True,
):
    result = {}
    if kind in ("all", "members"):
        def member_job():
            try:
                rows = fetch_members()
                source = "live"
            except Exception:
                rows = load_bootstrap()
                source = "bootstrap snapshot"
            n = upsert_members(db, rows)
            return {"seen": len(rows), "written": n, "source": source}
        result["members"] = _run(db, "members", member_job)
    if kind in ("all", "attendance"):
        result["attendance"] = _run(db, "attendance", lambda: scrape_attendance(db, start=start, end=end))
    if kind in ("all", "votes"):
        result["votes"] = _run(db, "votes", lambda: scrape_votes(db, start=start, end=end))
    if kind in ("all", "donations"):
        result["donations"] = _run(db, "donations", lambda: scrape_donations(db, csv_path=csv_path, headless=headless))
    return result


def parse_iso(value: str | None):
    return date.fromisoformat(value) if value else None


def main():
    parser = argparse.ArgumentParser(description="QLD MP Watch data scraper")
    parser.add_argument("kind", choices=["all", "members", "attendance", "votes", "donations", "init"], nargs="?", default="all")
    parser.add_argument("--csv", help="Import a manually-downloaded ECQ CSV instead of browser automation")
    parser.add_argument("--from", dest="from_date", help="Parliament record start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="Parliament record end date YYYY-MM-DD")
    parser.add_argument("--headed", action="store_true", help="Show Chromium during ECQ export")
    args = parser.parse_args()
    init_db()
    if args.kind == "init":
        with SessionLocal() as db:
            print(run_selected(db, "members"))
        return
    with SessionLocal() as db:
        result = run_selected(
            db,
            args.kind,
            csv_path=args.csv,
            start=parse_iso(args.from_date),
            end=parse_iso(args.to_date),
            headless=not args.headed,
        )
        print(result)


if __name__ == "__main__":
    main()
