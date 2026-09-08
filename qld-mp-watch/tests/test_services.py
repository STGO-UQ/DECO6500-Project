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



class FundingServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_party_funding_is_separate_from_direct_member_gifts_and_groups_donors(self):
        from app.models import Donation
        from app.services import donation_summary, party_funding_summary, party_funding_totals

        with self.Session() as db:
            member = Member(
                full_name="Example Labor MP",
                electorate="Example",
                party="Labor",
                term_start=date(2024, 11, 26),
                attendance_alias="Example",
            )
            db.add(member); db.flush()
            db.add_all([
                Donation(source_key="direct", donor="Local Donor", recipient="Example Labor MP", gift_date=date(2026, 1, 10), amount=2500, member_id=member.id),
                Donation(source_key="p1", donor="Company A", recipient="Australian Labor Party (State of Queensland)", gift_date=date(2026, 1, 11), amount=10000),
                Donation(source_key="p2", donor="Company A", recipient="Australian Labor Party (State of Queensland)", gift_date=date(2026, 2, 11), amount=5000),
                Donation(source_key="p3", donor="Company B", recipient="Australian Labor Party (State of Queensland)", gift_date=date(2026, 3, 11), amount=3000),
            ])
            db.commit()

            direct = donation_summary(db, member.id, date(2026, 1, 1), date(2026, 12, 31))
            party = party_funding_summary(db, "Labor", date(2026, 1, 1), date(2026, 12, 31))
            totals = party_funding_totals(db, date(2026, 1, 1), date(2026, 12, 31))

            self.assertEqual(direct["total"], 2500)
            self.assertEqual(direct["count"], 1)
            self.assertEqual(party["total"], 18000)
            self.assertEqual(party["count"], 3)
            self.assertEqual(party["donor_count"], 2)
            self.assertEqual(party["donors"][0]["donor"], "Company A")
            self.assertEqual(party["donors"][0]["total"], 15000)
            self.assertEqual(totals["Labor"]["total"], 18000)

    def test_known_ecq_party_recipient_names_are_classified(self):
        from app.models import Donation
        from app.services import party_funding_totals

        with self.Session() as db:
            rows = [
                ("lnp", "PEXA Group Limited", "Liberal National Party of Queensland", 8307),
                ("lab", "Braidwood farm Pty Ltd", "Australian Labor Party (State of Queensland)", 2500),
                ("grn", "ELEANOR KATE FORREST", "Queensland Greens", 2000),
                ("kap", "Australian Country Choice Production Pty Ltd", "Katter's Australian Party (KAP)", 3500),
            ]
            for key, donor, recipient, amount in rows:
                db.add(Donation(source_key=key, donor=donor, recipient=recipient, gift_date=date(2026, 8, 24), amount=amount))
            db.commit()
            totals = party_funding_totals(db, date(2026, 1, 1), date(2026, 12, 31))
            self.assertEqual(totals["LNP"]["total"], 8307)
            self.assertEqual(totals["Labor"]["total"], 2500)
            self.assertEqual(totals["Greens"]["total"], 2000)
            self.assertEqual(totals["KAP"]["total"], 3500)


if __name__ == "__main__":
    unittest.main()
