# MVP — LinkedIn Job Auto-Search

Run-on-demand job collector. Define LinkedIn searches and a per-field filter,
run the script, and get a curated list of matching jobs as **per-job JSON
files** plus a slim **summary CSV** for at-a-glance browsing.

## One-time setup (uv)

```bash
uv sync --extra web                          # web UI + scraper
uv run playwright install chromium
cp mvp/config.example.yaml mvp/config.yaml   # then edit your searches + filters
```

(If you only need the CLI, `--extra mvp` skips the FastAPI deps.)

## Usage

### Web UI (recommended)

```bash
uv run python -m mvp.web                     # http://127.0.0.1:8765/
```

Pages:
- **/jobs** — kept jobs table, click any row to open the detail/application page
- **/jobs/&lt;id&gt;** — full description + application editor (status, motivation
  letter, applied/rejected dates, history, notes)
- **/discarded** — filter rejects; "Restore" button moves a job back to kept
- **/config** — form-based editor for `mvp/config.yaml` (atomic save with
  `.bak` backup)
- **/run** — Start / Rescrape / Log-in / Stop buttons + live log stream (SSE)
  + per-run summary

The web UI calls the same `run_pipeline()` as the CLI, so all configs and
data are interchangeable.

### CLI

```bash
uv run python -m mvp.run               # normal run
uv run python -m mvp.run --rescrape    # wipe data/ and re-scrape from scratch
uv run python -m mvp.reclean           # re-trim saved descriptions in place (no rescrape)
```

Use `mvp.reclean` after the LinkedIn-cruft marker list grows — it walks the
existing per-job files and applies the new trim rules to saved descriptions.
Application state is untouched.

First run opens a visible browser for LinkedIn login (handles 2FA). Subsequent
runs are headless. Stop anytime with `Ctrl+C` — already-saved jobs persist.

## Two-stage funnel

The pipeline pairs a **broad LinkedIn-side search** with a **strict
client-side filter**:

1. **`searches`** — what we send to LinkedIn. Keep these broad (LinkedIn's own
   keyword filter is loose and noisy). Use multiple searches to maximize
   recall.
2. **`filters`** — per-field check applied to the scraped record. This is
   where we actually narrow down.

```yaml
searches:
  - keywords: "engineer"
    location: "Germany"
    limit: 100
  - keywords: "developer"
    location: "Germany"
    limit: 100

filters:
  job_title:
    include: ["engineer", "developer", "scientist"]
    exclude: ["senior", "lead"]
  location:
    include: ["germany"]
  job_description:
    include: ["python"]
  workplace_type:
    in: ["Remote", "Hybrid"]
  employment_type:
    in: ["Full-time"]
  posted_date:
    within_days: 14
  case_sensitive: false
```

### Filter semantics

| Field type | Keys                       | Meaning                                                  |
|------------|----------------------------|----------------------------------------------------------|
| Text       | `include`, `exclude`       | Substring match. `include` is OR (any matches). `exclude` disqualifies. |
| Categorical| `in`                       | Field value must be one of the listed strings.           |
| Date       | `within_days`              | Parsed `posted_date` must be ≤ N days ago.               |

- **Across fields**: AND. A job passes only if every constrained field passes.
- **Field-level skipping**: drop a field's block (or empty its lists) to
  ignore that field.
- **Filter-wide skipping**: drop the entire `filters:` block to keep every
  scraped job.

## Output

```
data/
  jobs/
    4395308615.json         # one full record per kept job
    4400528523.json
    ...
  discarded/
    7890123456.json         # filter rejects, kept for audit + dedup
    ...
  summary.csv               # one row per kept job, no description
  discarded.csv             # one row per rejected job — quick sanity check
```

### Single job file shape

```jsonc
{
  "linkedin_url": "https://www.linkedin.com/jobs/view/4395308615/",
  "job_id": "4395308615",
  "job_title": "Senior Python Engineer",
  "company": "Acme",
  "company_linkedin_url": "https://www.linkedin.com/company/acme/",
  "location": "Berlin, Germany",
  "posted_date": "2 days ago",
  "posted_days_ago": 2.0,
  "applicant_count": "47 applicants",
  "workplace_type": "Hybrid",
  "employment_type": "Full-time",
  "job_description": "We are looking for...",
  "search_keywords": "engineer",
  "search_location": "Germany",
  "scraped_at": "2026-04-27T20:30:00+00:00",
  "matched": true,
  "application": {
    "status": "not_applied",
    "motivation_letter": null,
    "cv_version": null,
    "applied_at": null,
    "rejected_at": null,
    "accepted_at": null,
    "notes": null,
    "history": []
  }
}
```

Every job's complete state — scraped data + filter outcome + application
progress — lives in **one file**. That makes it LLM-friendly: you can hand
a single file to a tool that drafts a motivation letter, fills in
`application.motivation_letter`, sets `application.status = "drafted"`, and
appends an event to `history`. Re-scraping preserves the `application`
block, so progress is never lost.

### summary.csv columns

`job_id, job_title, company, location, workplace_type, employment_type,
posted_date, posted_days_ago, applicant_count, status, applied_at,
search_keywords, linkedin_url`

### discarded.csv columns

Same as summary.csv minus `status` and `applied_at` (always not-applied for
rejects). Useful to sanity-check what your filters threw out:

```bash
column -t -s, data/discarded.csv | less -S
```

Open it in Excel or:

```bash
column -t -s, data/summary.csv | less -S
```

### Quick queries

```bash
# Count kept vs discarded
ls data/jobs | wc -l
ls data/discarded | wc -l

# Find a specific job
cat data/jobs/4395308615.json

# Pipe matching jobs into a tool
jq -s '.' data/jobs/*.json
```

In Python:

```python
import json, glob
jobs = [json.load(open(f, encoding="utf-8")) for f in glob.glob("data/jobs/*.json")]
remote = [j for j in jobs if j["workplace_type"] == "Remote"]
```

## Application tracking (planned)

The `application` block is wired into the schema today and ready for a
future workflow:

```
status:        not_applied → drafted → applied → interviewing → accepted/rejected
                                              ↘ withdrawn
```

To update by hand right now, just edit the JSON file:

```bash
# After applying
$EDITOR data/jobs/4395308615.json
# Set application.status = "applied", applied_at, and append to history
```

A future `python -m mvp.apply <job_id>` command can use the
`job_description` + `company` to draft a motivation letter via an LLM and
update the file in place. The data shape doesn't need to change.

## Notes

- `config.yaml`, `data/`, and `linkedin_session.json` are gitignored.
- The extractor relies on English LinkedIn UI strings (`"About the job"`,
  `"On-site"`, `"Full-time"`). If you switch LinkedIn UI to another
  language, edit the constants in [extractor.py](extractor.py).
- `summary.csv` is regenerated at the end of every run by walking
  `data/jobs/`. If you edit per-job files manually and want a fresh summary
  without re-scraping, the simplest path today is to re-run with no new
  searches (an empty incremental run still rebuilds the CSV).
