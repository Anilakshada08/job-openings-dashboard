# Job Openings Dashboard (USA Job search application)

A public, read-only dashboard of job openings posted in the last 24 hours, for everyone:
https://anilakshada08.github.io/job-openings-dashboard/ (GitHub Pages from `main`, repo Anilakshada08/job-openings-dashboard).

Filters: Skillset (Angular, APM/PO), Experience (Junior 0–3, Mid 3–8, Senior 8+), Location (Chicago / Remote / other US), and posted date.

This project is separate from the Angular job-apply project in `C:\Users\anilv\job-search-engine`. Never edit, commit to or
schedule anything there from here.

## How data gets in
- `collector/collect.py` (standard library only) polls the public feeds, merges per-site results, levels experience,
  tags location and dedupes. All postings are stored in `data/postings.json`, which keeps 60 days of history.
- `.github/workflows/daily.yml`: polls the public feeds at 07:00 UTC.
- The local scheduled task `job-openings-dashboard-daily` (2:20 AM CT) is the orchestrator. It runs one `openings-site`
  agent (`.claude/agents/openings-site.md`) per site in `collector/sites.json`, in parallel waves of 5, each in its own
  Chrome tab. Each agent writes `.runs/<site>.json`. The orchestrator then runs `python collector/collect.py --merge .runs/*.json` and pushes
  `data/postings.json` only.
- Page scrapers: `collector/browser_scrapers.js` has dedicated scrapers for LinkedIn, Indeed, Dice and Monster,
  and a generic one for every other site.

## Rules
- Read-only on every job site: never apply, sign in, message, save jobs or solve CAPTCHAs.
- Commit only code or `data/postings.json`. Never commit `.runs/`.
- To add a job site, add an entry to `collector/sites.json`. To add a skillset, add it to `SKILLSETS` in
  `collect.py` and to `terms` in `sites.json`.
