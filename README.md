# QLD MP Watch — frontend prototype

A single-file, responsive frontend for exploring Queensland state MPs by electorate, with views for parliamentary attendance and political donations.

## Run

Open `index.html` in a browser with internet access, or serve the folder locally:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000`.

## What is live vs demo

- **Live/configured:** Queensland state-electorate polygons from the Queensland Government ArcGIS administrative-boundaries service (layer 5), rendered with Leaflet/OpenStreetMap.
- **Demo:** attendance percentages and donation totals. The interface intentionally labels these as sample values.

## Suggested backend endpoints

The frontend becomes production-ready once these endpoints replace the sample object in `index.html`:

```text
GET /api/members
GET /api/electorates/:electorate/member
GET /api/members/:id/attendance?from=YYYY-MM-DD&to=YYYY-MM-DD
GET /api/members/:id/donations?from=YYYY-MM-DD&to=YYYY-MM-DD
```

Recommended attendance response:

```json
{
  "member_id": "...",
  "present_sitting_days": 64,
  "total_sitting_days": 68,
  "attendance_rate": 94.1,
  "days": [{"date":"2026-08-25","status":"present","evidence_url":"..."}]
}
```

Recommended donations response:

```json
{
  "member_id": "...",
  "total": 86400,
  "reconciled_total": 81200,
  "unreconciled_total": 5200,
  "gifts": [{"donor":"...","value":5000,"date":"2026-08-01","recipient":"...","political_donation":true,"source_url":"..."}]
}
```

## Production notes

1. Keep raw source records and evidence URLs rather than only storing aggregates.
2. Distinguish absence, approved leave, pairing and attendance at other parliamentary duties where the official record allows it.
3. For donations, preserve ECQ's reconciled/unreconciled distinction and display the publication caveat that EDS information is uploaded by users and may not be validated before publication.
4. Cache/parquet/DB-normalise scrape results server-side; do not scrape parliamentary/ECQ pages directly from the browser.
