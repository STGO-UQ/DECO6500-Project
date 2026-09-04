# QLD MP Watch

QLD MP Watch is a local full-stack transparency app for Queensland state Members of Parliament. It combines an interactive electorate map with official parliamentary attendance, recorded division voting and Electoral Commission of Queensland (ECQ) political gift disclosures.

> **Important:** the project does **not** ship with fake attendance, voting or donation totals. The database includes a bootstrap list of Queensland MPs so the interface can start, but you must run the data-sync tools on an internet-connected computer to populate the live parliamentary and ECQ datasets.

---

## What the app shows

For each Queensland state electorate, the app can display:

- current MP, electorate and party;
- sitting-day attendance;
- voting/division participation;
- individual recorded `AYE`, `NO` and `PAIR` entries;
- political gifts matched to the member/candidate/electorate from ECQ disclosures;
- source links back to the official evidence; and
- an interactive Queensland electorate map that can be coloured by attendance, voting participation or disclosed gifts.

The frontend intentionally shows `—` or `not scraped yet` until the corresponding real dataset has been loaded.

---

# START HERE — Windows

## 1. Unzip the project

Extract the ZIP somewhere convenient, for example:

```text
Downloads\qld-mp-watch
```

Open the extracted `qld-mp-watch` folder.

You should see files including:

```text
start_windows.bat
sync_real_data_windows.bat
update_parliament_data_windows.bat
requirements.txt
README.md
```

## 2. Start the website once

Double-click:

```text
start_windows.bat
```

On the first run it will:

1. create a Python virtual environment in `.venv`;
2. install the Python packages in `requirements.txt`;
3. install Chromium for the ECQ Playwright importer;
4. initialise the SQLite database; and
5. start the FastAPI web server.

When the terminal shows that Uvicorn is running, open:

```text
http://127.0.0.1:8000
```

The API testing page is:

```text
http://127.0.0.1:8000/docs
```

Keep the terminal window open while you use the website. Press `Ctrl+C` in that window to stop the server.

---

# Load the real data

## Easiest method

Close the website server first with `Ctrl+C`, then double-click:

```text
sync_real_data_windows.bat
```

This runs four jobs:

```text
1. Refresh current Queensland MPs
2. Scrape sitting attendance from Parliament Hansard
3. Scrape recorded divisions / voting from Parliament Hansard
4. Download/import ECQ political gift disclosures
```

When it finishes, start the website again with:

```text
start_windows.bat
```

Then refresh `http://127.0.0.1:8000`.

## Parliament-only update

If you only want MPs, attendance and voting, use:

```text
update_parliament_data_windows.bat
```

This skips ECQ donations.

---

# Where the real data comes from

QLD MP Watch is designed around official public sources.

## 1. Current Queensland MPs

Source:

```text
Queensland Parliament — Current Members
https://www.parliament.qld.gov.au/Members/Current-Members/Member-list
```

Run manually with:

```powershell
python -m app members
```

The program first attempts to obtain the live member list. If the Parliament page cannot be retrieved or its structure changes, the importer can fall back to the bundled 93-member bootstrap snapshot instead of inventing members.

The bootstrap list is useful for application startup, but a live refresh is preferable when publishing current information.

---

## 2. Sitting-day attendance

Source:

```text
Queensland Parliament — Record of Proceedings / Hansard
https://www.parliament.qld.gov.au/Work-of-the-Assembly/Record-of-Proceedings
```

Hansard documents are downloaded from the Queensland Parliament documents service and cached locally under:

```text
data\hansard_cache\
```

Run the full attendance scraper with:

```powershell
python -m app attendance
```

Or test a small date range first:

```powershell
python -m app attendance --from 2026-08-01 --to 2026-09-04
```

The attendance scraper:

1. discovers official sitting-day Record of Proceedings documents;
2. downloads the official Hansard PDF;
3. finds the `ATTENDANCE` list;
4. matches the listed members against the MP database;
5. stores the sitting date and official evidence URL; and
6. records the members positively identified as present.

### Attendance formula

Conceptually:

```text
Sitting attendance % = verified present sitting days
                       ----------------------------- × 100
                       eligible verified sitting days
```

A member's term start is respected, so a member is not penalised for sitting days before they entered Parliament.

Only sitting days for which usable official evidence was successfully parsed should contribute to the attendance denominator.

---

# Voting and vote-confirmed attendance

This is the additional feature added after the original QLD MP Watch prototype.

## Source

Recorded divisions are parsed from official Queensland Parliament Hansard.

Run:

```powershell
python -m app votes
```

Or use a limited range:

```powershell
python -m app votes --from 2026-08-01 --to 2026-09-04
```

The scraper recognises modern Hansard division blocks containing information such as:

```text
Division: Question put—...
AYES, ...
...
NOES, ...
...
Pair: ...
Resolved in the affirmative/negative.
```

For each division the database stores, where available:

- sitting date;
- sequence number;
- bill/motion/context heading;
- question put;
- result;
- Ayes count;
- Noes count;
- pair count;
- official Hansard source URL;
- source document hash; and
- each matched MP's `aye`, `no` or `pair` record.

## Voting participation formula

```text
Voting participation % = recorded AYE + NO ballots cast
                         ------------------------------ × 100
                         recorded divisions while in office
```

Pairs are reported separately and are **not** treated as cast ballots.

## Why a recorded vote can confirm attendance

If an MP is recorded as casting an `AYE` or `NO` in a division, the app treats that as positive evidence that the MP was present for that division.

Therefore, if the attendance-list parser did not match the member on that same sitting day but a division records an `AYE` or `NO`, the attendance API can mark the day as:

```text
present_vote_confirmed
```

and count the member as present.

### Very important limitation

The opposite inference is **not** made:

```text
No recorded vote ≠ absent from Parliament for the day
```

A member may have been present at another time, temporarily absent from the chamber, paired, or not required to participate in a particular recorded division.

Likewise:

```text
PAIR ≠ proof of physical presence
```

Pairs are kept separate from both Aye/No votes and vote-confirmed attendance.

This distinction is intentional so the website does not turn a missing division vote into an unsupported accusation of absence.

---

# Political gifts / donations

Source:

```text
Electoral Commission of Queensland — Electronic Disclosure System (EDS)
https://disclosures.ecq.qld.gov.au/
```

## Automatic importer

Run:

```powershell
python -m app donations
```

The project uses Playwright/Chromium to attempt to obtain the public ECQ disclosure export.

## Manual CSV fallback

If ECQ changes its website or the automatic download fails, download a public **Gifts** CSV from ECQ and save it to your computer.

Then run:

```powershell
python -m app donations --csv "C:\Users\YourName\Downloads\ecq-gifts.csv"
```

### Donation attribution rule

QLD MP Watch deliberately uses conservative attribution.

For example, this:

```text
Recipient: Liberal National Party of Queensland
Gift: $20,000
```

is **not** automatically shown as a $20,000 donation to every LNP MP.

Only disclosures that can be matched to the relevant member, candidate or electorate are attributed to an MP in the member-level view. Party-wide gifts remain unassigned at MP level. The Funding tab now reports them separately as **party-wide funding context**, alongside the direct/candidate-linked total. It also groups disclosures by donor so users can see who funded the party, the donor's aggregate amount, and the number of disclosures.

For a party-affiliated MP the interface therefore shows two different figures:

```text
Direct / candidate-linked gifts
$12,500
4 disclosures

Party-wide funding context
$2.84 million
312 disclosures
```

The second figure is **not money personally received by the MP**. It is the total value of ECQ disclosures whose recipient is that MP's registered political party for the selected period. Independent MPs do not receive a party-wide total.

ECQ disclosures should be presented as disclosed information, not described by this application as an independent audit of the donor or recipient.

---

# Electorate map data

Source:

```text
Queensland Government Administrative Boundaries ArcGIS service
State electorate layer (layer 5)
https://spatial-gis.information.qld.gov.au/arcgis/rest/services/Boundaries/AdministrativeBoundaries/MapServer/5
```

The backend requests electorate geometry and exposes it to the frontend as GeoJSON through:

```text
GET /api/electorates/geojson
```

The map geometry is then joined to MPs by electorate name.

---

# Run all data jobs manually

After activating the virtual environment:

```powershell
.venv\Scripts\activate
```

run everything with:

```powershell
python -m app all
```

Equivalent individual commands are:

```powershell
python -m app members
python -m app attendance
python -m app votes
python -m app donations
```

For Parliament scrapers, optional date filters are:

```powershell
--from YYYY-MM-DD
--to YYYY-MM-DD
```

Example:

```powershell
python -m app votes --from 2026-01-01 --to 2026-09-04
```

For ECQ troubleshooting you can show the Chromium browser window with:

```powershell
python -m app donations --headed
```

---

# Verify that real data loaded

Before trusting what appears on the map, check the API.

Start the server:

```powershell
uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000/api/health
```

A populated installation should eventually show counts greater than zero for relevant datasets, for example:

```json
{
  "ok": true,
  "members": 93,
  "sitting_days": 30,
  "divisions": 120,
  "division_votes": 9000,
  "donations": 500
}
```

**Those numbers are examples only.** Your real counts depend on the date range and successful imports.

If you see:

```json
"sitting_days": 0,
"divisions": 0,
"donations": 0
```

then those real datasets have not been loaded yet.

You can also inspect:

```text
http://127.0.0.1:8000/api/meta
```

which reports the newest stored attendance, division and donation dates plus the methodology used by the API.

---

# Useful API endpoints

## Health / methodology

```text
GET /api/health
GET /api/meta
```

## Members

```text
GET /api/members
GET /api/members?party=LNP
GET /api/members?q=moggill
GET /api/members?from=2026-01-01&to=2026-12-31
GET /api/members/{member_id}
GET /api/electorates/{electorate}/member
```

Member summaries can include:

```text
attendance_rate
present_sitting_days
total_sitting_days
vote_confirmed_corrections
voting_participation_rate
ballots_cast
total_divisions
paired_divisions
donations_total
donations_count
party_funding_total
party_funding_count
```

## Attendance

```text
GET /api/members/{member_id}/attendance
GET /api/members/{member_id}/attendance?from=2026-01-01&to=2026-12-31
```

Attendance evidence distinguishes the official attendance-list match from presence independently confirmed by a recorded Aye/No division.

## Voting

```text
GET /api/members/{member_id}/votes
GET /api/members/{member_id}/votes?from=2026-01-01&to=2026-12-31&limit=100
GET /api/divisions
GET /api/divisions?from=2026-01-01&to=2026-12-31&limit=100
```

## Political funding

Direct/candidate-linked disclosures:

```text
GET /api/members/{member_id}/donations
GET /api/members/{member_id}/donations?from=2026-01-01&to=2026-12-31&limit=100
```

Party-wide disclosures and donor aggregation:

```text
GET /api/parties/LNP/funding
GET /api/parties/Labor/funding?from=2026-01-01&to=2026-12-31&limit=50&donor_limit=20
```

The party endpoint returns the party total, disclosure count, distinct donor count, top donors grouped by total value, and recent individual ECQ disclosures.

## Map

```text
GET /api/electorates/geojson
```

Interactive Swagger/OpenAPI documentation is available at:

```text
http://127.0.0.1:8000/docs
```

---

# Database

The default SQLite database is stored at:

```text
data\qld_mp_watch.sqlite3
```

Main tables include:

## `members`

Current MP identity, electorate, party, matching information, source URL and term-start information.

## `sitting_days`

Discovered official parliamentary sitting days and evidence/status information.

## `attendance`

Members positively matched to official sitting-day attendance evidence.

## `divisions`

Recorded parliamentary divisions including question, context, result, counts and source evidence.

## `division_votes`

Individual member records with:

```text
aye
no
pair
```

## `donations`

Normalised ECQ political gift disclosures, including conservative member matching.

## `scrape_runs`

History/status of data importer and scraper runs.

---

# Project structure

```text
qld-mp-watch/
│
├── app/
│   ├── main.py                 FastAPI routes
│   ├── cli.py                  command-line scraper runner
│   ├── db.py                   database setup
│   ├── models.py               SQLAlchemy tables
│   ├── services.py             attendance/vote/donation summaries
│   └── scrapers/
│       ├── members.py
│       ├── attendance.py
│       ├── votes.py
│       ├── donations.py
│       └── boundaries.py
│
├── data/
│   ├── bootstrap_members.json
│   └── qld_mp_watch.sqlite3
│
├── frontend/
│   └── index.html
│
├── tests/
├── start_windows.bat
├── sync_real_data_windows.bat
├── update_parliament_data_windows.bat
├── start.sh
├── requirements.txt
└── README.md
```

---

# Tests

Activate the environment and run:

```powershell
python -m unittest discover -s tests -v
```

The current test suite covers areas including:

- attendance-list parsing;
- duplicate-surname aliases;
- ECQ CSV normalisation;
- modern Hansard Aye/No/Pair parsing; and
- avoiding table-of-contents division references being interpreted as genuine vote records.

---

# Troubleshooting

## `python` is not recognised

Try:

```powershell
py --version
```

If neither `python` nor `py` works, install a current Python 3 release and make sure Python is added to PATH during installation.

## PowerShell says a command cannot be found

Make sure you opened the terminal inside the extracted `qld-mp-watch` folder.

You can confirm by running:

```powershell
dir
```

and checking that `requirements.txt` and `start_windows.bat` are listed.

## `start_windows.bat` closes immediately

Open a terminal in the project folder and run:

```powershell
.\start_windows.bat
```

That keeps the error visible so it can be copied for debugging.

## The map loads but all statistics are blank

Check:

```text
http://127.0.0.1:8000/api/health
```

If the real-data counts are zero, run:

```text
sync_real_data_windows.bat
```

and restart the website afterward.

## Attendance is empty

Try a small known date range first:

```powershell
python -m app attendance --from 2026-08-01 --to 2026-09-04
```

If it still discovers or parses zero documents, the Parliament website/document format may have changed and the scraper will need adjustment.

## Voting is empty

Try:

```powershell
python -m app votes --from 2026-08-01 --to 2026-09-04
```

Then inspect:

```text
http://127.0.0.1:8000/api/health
```

and confirm that `divisions` and `division_votes` increased.

## ECQ automatic download fails

Use the manual CSV method:

```powershell
python -m app donations --csv "C:\path\to\ecq-gifts.csv"
```

You can also troubleshoot the browser automation visibly with:

```powershell
python -m app donations --headed
```

---

# Interpretation and responsible use

This is a political-transparency data project, so presentation matters as much as scraping.

### Attendance is not a performance score

Sitting attendance reports evidence of presence on parliamentary sitting days. It does not measure electorate work, committee work, ministerial work, preparation, illness, approved leave or other parliamentary responsibilities.

### Voting participation is not the same thing as attendance

A recorded Aye or No proves presence for that recorded division. A missing vote does **not** prove absence from the sitting day.

### Pairs require separate treatment

A pair is not presented as a cast vote and is not treated as evidence of physical presence.

### Donations should not be over-attributed

A gift to a political party should not automatically be represented as a gift to every MP in that party. Member-level totals in this project are intentionally conservative. Party-wide totals are shown as contextual information only and are explicitly labelled as **not personal to the MP**.

### Donor totals are aggregated from disclosure rows

The Funding tab groups party disclosures by the disclosed donor name and sums their gift values for the selected period. This helps answer “who is the funding coming from?” without changing the underlying ECQ records. The recent-disclosure list remains available beneath the grouped donor totals for traceability.

### Keep the source evidence

When publishing or presenting a specific attendance day, vote or donation, retain the official source URL wherever possible so users can inspect the underlying record themselves.

---

# Updating the app over time

For a simple local workflow, periodically run:

```text
update_parliament_data_windows.bat
```

for Parliament data, or:

```text
sync_real_data_windows.bat
```

for Parliament + ECQ data.

Then restart the website.

For a deployed/public version, the next engineering step would be scheduling these scraper jobs and moving from local SQLite to a hosted database such as PostgreSQL.

---

# Version

This README describes the QLD MP Watch build with:

- sitting attendance;
- vote-confirmed attendance;
- recorded Aye/No/Pair division history;
- voting participation;
- ECQ direct/candidate-linked gifts;
- party-wide ECQ funding and donor aggregation; and
- Queensland electorate mapping.

API version in this build: **0.4.0**.
