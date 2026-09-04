import unittest

from app.scrapers.attendance import parse_attendance_tokens
from app.scrapers.donations import parse_ecq_csv
from app.scrapers.members import assign_attendance_aliases
from app.scrapers.votes import parse_divisions


class ScraperTests(unittest.TestCase):
    def test_attendance_list(self):
        text = """some hansard text\nATTENDANCE\nAsif, Bailey, James B, James T, Kelly G, Kelly J, O'Connor, O'Shea, de Brenni, Young"""
        self.assertEqual(parse_attendance_tokens(text)[-3:], ["O'Shea", "de Brenni", "Young"])

    def test_alias_collision(self):
        rows = assign_attendance_aliases([
            {"full_name": "Bree James", "electorate": "Barron River", "party": "LNP"},
            {"full_name": "Terry James", "electorate": "Mulgrave", "party": "LNP"},
            {"full_name": "Michael (Mick) de Brenni", "electorate": "Springwood", "party": "Labor"},
        ])
        self.assertEqual(rows[0]["attendance_alias"], "James B")
        self.assertEqual(rows[1]["attendance_alias"], "James T")
        self.assertEqual(rows[2]["attendance_alias"], "de Brenni")

    def test_ecq_flexible_csv(self):
        csv_text = 'Donor,Recipient,Date Gift Made,Gift value,Political donation?,Electorate\nJane Citizen,David Example,28-08-2026,"$1,000.00",Political,Example\n'
        rows = parse_ecq_csv(csv_text)
        self.assertEqual(rows[0]["amount"], 1000.0)
        self.assertEqual(rows[0]["gift_date"].isoformat(), "2026-08-28")

    def test_ecq_filters_non_state_rows_when_government_type_present(self):
        csv_text = 'Government Type,Donor,Recipient,Date Gift Made,Gift value\nLocal,Local Donor,Local Candidate,28-08-2026,"$500.00"\nState,State Donor,State Candidate,28-08-2026,"$700.00"\n'
        rows = parse_ecq_csv(csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["donor"], "State Donor")

    def test_modern_hansard_division_with_pair(self):
        text = """
MOTION
LEAVE TO MOVE MOTION
Division: Question put—That leave be granted.
AYES, 4:
ALP, 2—Asif, J. Kelly.
Grn, 1—Berkman.
Ind, 1—Sullivan.
NOES, 4:
LNP, 4—Crisafulli, B. James, T. James, G. Kelly.
Pair: Perrett, Bailey.
Resolved in the negative.
"""
        rows = parse_divisions(text)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["question"], "That leave be granted")
        self.assertEqual(row["ayes_count"], 4)
        self.assertEqual(row["noes_count"], 4)
        self.assertEqual(row["ayes"], ["Asif", "J. Kelly", "Berkman", "Sullivan"])
        self.assertEqual(row["noes"], ["Crisafulli", "B. James", "T. James", "G. Kelly"])
        self.assertEqual(row["pairs"], ["Perrett", "Bailey"])
        self.assertEqual(row["result"], "negative")

    def test_division_toc_reference_is_ignored(self):
        text = "Division: Question put—That the bill be read. ........ 103\nResolved in the affirmative. ........ 103"
        self.assertEqual(parse_divisions(text), [])


if __name__ == "__main__":
    unittest.main()
