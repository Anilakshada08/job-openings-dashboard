# USA Job Search

A public, filterable list of job openings **posted in the last 24 hours**, refreshed every night around **2 AM Central**.

**Live dashboard:** https://anilakshada08.github.io/job-openings-dashboard/

## Filters

| Filter | Options |
|---|---|
| Skillset | Angular · APM / PO (Agile Project Manager, Product Owner, Technical Project/Program Manager) |
| Experience | Junior (0–3 yrs) · Mid (3–8 yrs) · Senior (8+ yrs) |
| Location | All · Chicago or Remote · Chicago area · Remote · Other US locations |
| Posted | Last 24 hours, any single past day, or all dates |
| Source / Search | Narrow by job site, or by title or company |

Filters are kept in the page address, so you can share a link to a filtered view, for example
`?skill=apmpo&exp=senior&loc=chicago,remote`.

## How it updates

1. **GitHub Actions** (`.github/workflows/daily.yml`) runs `collector/collect.py` at 07:00 UTC each day. It reads the public
   job feeds (Himalayas, Jobicy, Remote OK, Remotive, The Muse, Workable), keeps postings from the last 24 hours that
   match a skillset, and appends them to `data/postings.json`.
2. **Site agents, one per job site, run in parallel** every night around 2 AM Central. The sites are listed in
   `collector/sites.json`: LinkedIn, Indeed, Dice, Monster, ZipRecruiter, Glassdoor, CareerBuilder, SimplyHired,
   Built In, USAJOBS, Talent.com, Jooble, We Work Remotely, Wellfound, and company career sites (Workday, Greenhouse,
   Lever, Ashby and others, found through a Google search of the past 24 hours).
   Each agent (`.claude/agents/openings-site.md`) opens its own browser tab and searches only public result pages
   (no sign-in) for every skillset. It reads the cards with `collector/browser_scrapers.js` and writes
   `.runs/<site>.json`. An orchestrator then runs `python collector/collect.py --merge .runs/*.json`.
   To add a job site, add one entry to `sites.json`.
3. The page re-reads `data/postings.json` every 10 minutes, so open tabs pick up the update without a refresh.

Postings are kept for 60 days so the date filter can show earlier days. A job that appears on several sites is shown once,
with a link to each site.

### Experience level

The level comes from the smallest "N+ years of experience" in the posting: under 3 years is Junior, 3–7 is Mid, and 8
or more is Senior. Senior-titled roles asking for 5 or more years also count as Senior. When a posting gives no years,
the level is estimated from the job title and shown with "≈".

## Adding a skillset

Add an entry to `SKILLSETS` in `collector/collect.py`, giving it a label, feed search terms and a title pattern. The
dropdown picks it up on the next run.

## Credits

Listings belong to the sites they come from. Every row links back to the original posting; apply there.
