import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Division, DivisionVote, Member, SittingDay
from app.services import attendance_summary, division_summary


class ServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_aye_vote_can_confirm_presence_but_missing_vote_cannot(self):
        with self.Session() as db:
            member = Member(full_name="Example Member", electorate="Example", party="Independent", term_start=date(2026, 1, 1), attendance_alias="Member")
            db.add(member); db.flush()
            day1 = SittingDay(date=date(2026, 2, 1), evidence_url="https://example/1.pdf", scrape_status="ok")
            day2 = SittingDay(date=date(2026, 2, 2), evidence_url="https://example/2.pdf", scrape_status="ok")
            db.add_all([day1, day2]); db.flush()
            division = Division(source_key="d1", sitting_date=day1.date, sequence=1, question="That the motion be agreed to", evidence_url=day1.evidence_url, ayes_count=1, noes_count=1)
            db.add(division); db.flush()
            db.add(DivisionVote(division_id=division.id, member_id=member.id, choice="aye", source_token="Member")); db.commit()

            result = attendance_summary(db, member.id)
            self.assertEqual(result["present_sitting_days"], 1)
            self.assertEqual(result["total_sitting_days"], 2)
            self.assertEqual(result["attendance_rate"], 50.0)
            self.assertEqual(result["days"][0]["status"], "present_vote_confirmed")
            self.assertEqual(result["days"][1]["status"], "not_listed")

    def test_pair_is_not_a_cast_vote_or_presence_evidence(self):
        with self.Session() as db:
            member = Member(full_name="Example Member", electorate="Example", party="Independent", term_start=date(2026, 1, 1), attendance_alias="Member")
            db.add(member); db.flush()
            day = SittingDay(date=date(2026, 2, 1), evidence_url="https://example/1.pdf", scrape_status="ok")
            db.add(day); db.flush()
            division = Division(source_key="d1", sitting_date=day.date, sequence=1, question="That the motion be agreed to", evidence_url=day.evidence_url, ayes_count=40, noes_count=40, pair_count=2)
            db.add(division); db.flush()
            db.add(DivisionVote(division_id=division.id, member_id=member.id, choice="pair", source_token="Member")); db.commit()

            attendance = attendance_summary(db, member.id)
            voting = division_summary(db, member.id)
            self.assertEqual(attendance["present_sitting_days"], 0)
            self.assertEqual(voting["ballots_cast"], 0)
            self.assertEqual(voting["paired"], 1)
            self.assertEqual(voting["participation_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
