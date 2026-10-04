"""Daily job-openings collector for the public dashboard (standard library only).

Pulls postings from public job feeds for every skillset in SKILLSETS, keeps the ones posted in the
last 24 hours, tags each with skillset / experience level / location group, and appends them to
data/postings.json (history is kept so the dashboard's date filter works).

    python collector/collect.py                  # poll the public feeds
    python collector/collect.py --merge f.json   # add postings found in a browser (LinkedIn, Dice, ...)

A --merge file is a JSON list of objects with: title, company, location, posted (ISO date/time,
or "3 hours ago"), source, apply_url, and optionally description, skillset, experience, salary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone, tzinfo
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "postings.json"


class _Central(tzinfo):
    """US Central time with US DST rules (2nd Sun Mar - 1st Sun Nov); avoids needing tzdata on Windows."""

    def utcoffset(self, dt):
        return timedelta(hours=-5) if self.dst(dt) else timedelta(hours=-6)

    def dst(self, dt):
        y = dt.year
        start = datetime(y, 3, 8 + (6 - datetime(y, 3, 8).weekday()) % 7, 2)
        end = datetime(y, 11, 1 + (6 - datetime(y, 11, 1).weekday()) % 7, 2)
        return timedelta(hours=1) if start <= dt.replace(tzinfo=None) < end else timedelta(0)

    def tzname(self, dt):
        return "CDT" if self.dst(dt) else "CST"


CT = _Central()
UA = {"User-Agent": "Mozilla/5.0 (job-openings-dashboard; daily public digest)"}
WINDOW_HOURS = 24
KEEP_DAYS = 60

# ---------------------------------------------------------------- skillsets
# Each skillset: feed search terms + a title matcher. Add a new entry here to add a dropdown option.
SKILLSETS = {
    "angular": {
        "label": "Angular",
        "queries": ["angular"],
        "title": re.compile(r"\bangular", re.I),
        # Generic front-end/web titles count when the description mentions Angular.
        "title_with_desc": re.compile(r"front[\s-]?end|\bui\b|\bweb\b|full[\s-]?stack|software (engineer|developer)|"
                                      r"javascript|typescript", re.I),
        "desc": re.compile(r"\bangular\b(?!\s*js)|\bangular\s*(\d|2\+)", re.I),
    },
    "apmpo": {
        "label": "APM / PO",
        "queries": ["product owner", "technical project manager", "agile project manager",
                    "technical program manager"],
        "title": re.compile(r"product owner|agile (project|program|delivery) manager|"
                            r"technical (project|program) manager|\bTPM\b|scrum master|agile coach|"
                            r"(it|software|digital|technology|technical|agile|scrum) (project|program|delivery) (manager|lead)",
                            re.I),
        # Plain "Project/Program Manager" titles count only for agile / software work.
        "title_with_desc": re.compile(r"\b(project|program|delivery) manager\b", re.I),
        "desc": re.compile(r"\bagile\b|\bscrum\b|\bsdlc\b|\bjira\b|software development", re.I),
        # Non-software project management is out of scope for this skillset.
        "exclude": re.compile(r"marketing|construction|event|facilit|clinical|\bops\b|operations|real estate|civil|"
                              r"mechanical|electrical|manufactur|interior|landscap|restoration|hvac|renovation|nuclear|bridge|"
                              r"transmission|substation|r&d", re.I),
    },
}

CHICAGO_AREA = re.compile(
    r"chicago|arlington heights|schaumburg|naperville|oak ?brook|evanston|rosemont|des plaines|itasca|"
    r"deerfield|northbrook|lombard|downers grove|elk grove|hoffman estates|lisle|aurora, il|skokie|glenview|"
    r"lake forest|rolling meadows|wheeling|buffalo grove|vernon hills|bolingbrook|joliet|elgin|libertyville|"
    r"mount prospect|palatine|park ridge|warrenville|westchester|riverwoods|lincolnshire|oakbrook terrace|"
    r"west chicago|wood dale|bannockburn|north chicago|waukegan|oak park|cicero|lake zurich", re.I)
US_HINT = re.compile(r"\b(us|usa|u\.s\.|united states|america|anywhere|worldwide|global|north america|"
                     r"[A-Z][a-z]+, [A-Z]{2})\b|^\s*remote\s*$", re.I)
NON_US = re.compile(r"\b(uk|united kingdom|europe|emea|germany|india|canada|liechtenstein|switzerland|philippines|brazil|latam|"
                    r"latin america|apac|australia|spain|poland|france|netherlands|mexico|argentina|"
                    r"colombia|south africa|nigeria|pakistan|portugal|romania|ukraine|singapore|japan)\b", re.I)


# ---------------------------------------------------------------- helpers
def clean(html: str | None) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_when(value, now: datetime) -> datetime | None:
    """ISO strings, epoch seconds/millis, RFC-2822 or '3 hours ago' -> aware UTC datetime."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
        n = float(value)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, timezone.utc)
    s = str(value).strip()
    m = re.match(r"(\d+|an?|one)\s*(minute|min|hour|hr|day|week)s?\s+ago", s, re.I)
    if m:
        n = 1 if m.group(1).lower() in ("a", "an", "one") else int(m.group(1))
        unit = m.group(2).lower()
        delta = {"minute": timedelta(minutes=n), "min": timedelta(minutes=n), "hour": timedelta(hours=n),
                 "hr": timedelta(hours=n), "day": timedelta(days=n), "week": timedelta(weeks=n)}[unit]
        return now - delta
    if re.match(r"(just now|today|moments? ago|new)$", s, re.I):
        return now
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:  # date-only / naive values are Chicago local time
            d = d.replace(tzinfo=CT)
        return d.astimezone(timezone.utc)
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def match_skillsets(title: str, desc: str) -> list[str]:
    out = []
    for key, sk in SKILLSETS.items():
        if sk.get("exclude") and sk["exclude"].search(title):
            continue
        if sk["title"].search(title) or (sk["title_with_desc"].search(title) and sk["desc"].search(desc)):
            out.append(key)
    return out


SENIOR_TITLE = re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|director|head of|iii|iv|executive)\b", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*\+?\s*)?(?:years|yrs)", re.I)


def experience(title: str, desc: str, hint: str = "") -> tuple[str, int | None, bool]:
    """-> (junior|mid|senior, minimum years asked or None, estimated?)."""
    years = []
    for m in YEARS.finditer(desc[:8000]):
        ctx = desc[m.start(): m.end() + 80].lower()
        if "experience" in ctx or "exp" in ctx:
            n = int(m.group(1))
            if 0 < n <= 25:
                years.append(n)
    if years:
        y = min(years)
        level = "junior" if y < 3 else "mid" if y < 8 else "senior"
        if level == "mid" and y >= 5 and SENIOR_TITLE.search(title):
            level = "senior"
        return level, y, False
    t = f"{title} {hint}".lower()
    if SENIOR_TITLE.search(t):
        return "senior", None, True
    if re.search(r"\b(junior|jr\.?|entry|associate|graduate|intern|trainee|apprentice|level i|i)\b", t):
        return "junior", None, True
    return "mid", None, True


def location_group(location: str, remote: bool) -> str:
    if CHICAGO_AREA.search(location or ""):
        return "chicago"
    if remote or re.search(r"remote|anywhere|work from home|wfh", location or "", re.I):
        return "remote"
    return "other"


def us_eligible(location: str) -> bool:
    loc = location or ""
    if not loc.strip() or CHICAGO_AREA.search(loc):
        return True
    m = re.search(r"remote\s*\(([^)]*)\)", loc, re.I)
    if m:  # "Remote (Canada, UK)"-style restriction lists must name the US or anywhere
        return bool(US_HINT.search(m.group(1)))
    return bool(US_HINT.search(loc)) or not NON_US.search(loc)


def make_posting(raw: dict, now: datetime) -> dict | None:
    title = clean(raw.get("title"))
    company = clean(raw.get("company"))
    location = clean(raw.get("location")) or "Not specified"
    desc = clean(raw.get("description"))
    url = (raw.get("apply_url") or "").strip()
    if not (title and url):
        return None
    if not us_eligible(location):
        return None
    skills = match_skillsets(title, desc)
    sk = SKILLSETS.get(raw.get("skillset") or "")
    # A site search for the skillset counts as the description match when the title fits the role family.
    if not skills and sk and sk["title_with_desc"].search(title) and not (sk.get("exclude") and sk["exclude"].search(title)):
        skills = [raw["skillset"]]
    if not skills:
        return None
    when = parse_when(raw.get("posted"), now)
    if when is None or when > now + timedelta(hours=1) or now - when > timedelta(hours=WINDOW_HOURS):
        return None
    level, years, est = experience(title, desc, raw.get("level_hint", ""))
    if raw.get("experience") in ("junior", "mid", "senior"):
        level, est = raw["experience"], False
    group = location_group(location, bool(raw.get("remote")))
    key = hashlib.sha1(f"{norm(company)}|{norm(title)}|{group}".encode()).hexdigest()[:16]
    return {
        "id": key,
        "title": title[:160],
        "company": company[:120] or "Not listed",
        "location": location[:160],
        "location_group": group,
        "skillsets": skills,
        "experience": level,
        "years_min": years,
        "experience_estimated": est,
        "salary": clean(raw.get("salary"))[:80],
        "job_type": clean(raw.get("job_type"))[:60],
        "posted": when.isoformat(timespec="minutes"),
        "posted_day": when.astimezone(CT).date().isoformat(),
        "summary": desc[:320],
        "sources": [{"name": raw.get("source") or "Web", "url": url}],
    }


# ---------------------------------------------------------------- feeds
def all_queries() -> list[str]:
    return [q for sk in SKILLSETS.values() for q in sk["queries"]]


def feed_remoteok():
    for j in get_json("https://remoteok.com/api"):
        if isinstance(j, dict) and j.get("id"):
            sal = f"${j['salary_min']:,}–${j['salary_max']:,}" if j.get("salary_min") and j.get("salary_max") else ""
            yield {"title": j.get("position"), "company": j.get("company"), "location": j.get("location") or "Remote",
                   "remote": True, "posted": j.get("date"), "source": "Remote OK", "apply_url": j.get("url"),
                   "description": j.get("description"), "salary": sal}


def feed_jobicy():
    for q in all_queries():
        url = "https://jobicy.com/api/v2/remote-jobs?count=100&tag=" + urllib.parse.quote(q)
        for j in get_json(url).get("jobs", []):
            sal = ""
            if j.get("annualSalaryMin") and j.get("annualSalaryMax"):
                sal = f"{j.get('salaryCurrency', 'USD')} {j['annualSalaryMin']:,}–{j['annualSalaryMax']:,}"
            yield {"title": j.get("jobTitle"), "company": j.get("companyName"),
                   "location": "Remote (" + str(j.get("jobGeo") or "Anywhere") + ")", "remote": True,
                   "posted": j.get("pubDate"), "source": "Jobicy", "apply_url": j.get("url"),
                   "description": j.get("jobDescription"), "level_hint": j.get("jobLevel") or "", "salary": sal,
                   "job_type": ", ".join(j.get("jobType") or [])}


def feed_himalayas():
    for q in all_queries():
        url = "https://himalayas.app/jobs/api/search?sort=recent&q=" + urllib.parse.quote(q)
        for j in get_json(url).get("jobs", []):
            restr = j.get("locationRestrictions") or ["Anywhere"]
            sal = ""
            if j.get("minSalary") and j.get("maxSalary"):
                sal = f"{j.get('currency') or 'USD'} {int(float(j['minSalary'])):,}–{int(float(j['maxSalary'])):,}"
            yield {"title": j.get("title"), "company": j.get("companyName"),
                   "location": "Remote (" + ", ".join(restr) + ")", "remote": True, "posted": j.get("pubDate"),
                   "source": "Himalayas", "apply_url": j.get("applicationLink") or j.get("guid"),
                   "description": j.get("description"), "level_hint": " ".join(j.get("seniority") or []),
                   "salary": sal, "job_type": j.get("employmentType") or ""}


def feed_remotive():
    for q in all_queries():
        url = "https://remotive.com/api/remote-jobs?limit=100&search=" + urllib.parse.quote(q)
        for j in get_json(url).get("jobs", []):
            yield {"title": j.get("title"), "company": j.get("company_name"),
                   "location": "Remote (" + (j.get("candidate_required_location") or "Anywhere") + ")",
                   "remote": True, "posted": j.get("publication_date"), "source": "Remotive",
                   "apply_url": j.get("url"), "description": j.get("description"), "salary": j.get("salary") or "",
                   "job_type": j.get("job_type") or ""}


def feed_themuse():
    levels = {"Entry Level": "junior", "Internship": "junior", "Mid Level": "mid", "Senior Level": "senior",
              "management": "senior"}
    for cat in ("Project Management", "Product Management", "Software Engineering"):
        for loc in ("Chicago, IL", "Flexible / Remote"):
            for page in range(3):
                url = ("https://www.themuse.com/api/public/jobs?descending=true&page=%d&category=%s&location=%s"
                       % (page, urllib.parse.quote(cat), urllib.parse.quote(loc)))
                for j in get_json(url).get("results", []):
                    locs = ", ".join(x.get("name", "") for x in j.get("locations") or [])
                    lv = [levels.get(x.get("name")) for x in j.get("levels") or []]
                    yield {"title": j.get("name"), "company": (j.get("company") or {}).get("name"), "location": locs,
                           "remote": "Remote" in locs or "Flexible" in locs, "posted": j.get("publication_date"),
                           "source": "The Muse", "apply_url": (j.get("refs") or {}).get("landing_page"),
                           "description": j.get("contents"), "level_hint": next((x for x in lv if x), "")}


def feed_workable():
    for q in all_queries():
        url = "https://jobs.workable.com/api/v1/jobs?query=" + urllib.parse.quote(q)
        for j in get_json(url).get("jobs", []):
            loc = j.get("location") or {}
            place = ", ".join(filter(None, [loc.get("city"), loc.get("subregion"), loc.get("countryName")]))
            remote = j.get("workplace") == "remote"
            yield {"title": j.get("title"), "company": (j.get("company") or {}).get("title"),
                   "location": (place + (" (Remote)" if remote else "")).strip() or ("Remote" if remote else ""),
                   "remote": remote, "posted": j.get("created"), "source": "Workable", "apply_url": j.get("url"),
                   "description": j.get("description"), "job_type": j.get("employmentType") or ""}


FEEDS = {"Remote OK": feed_remoteok, "Jobicy": feed_jobicy, "Himalayas": feed_himalayas,
         "Remotive": feed_remotive, "The Muse": feed_themuse, "Workable": feed_workable}


# ---------------------------------------------------------------- store
def load() -> dict:
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8"))
    return {"skillsets": {}, "runs": [], "postings": []}


def save(db: dict) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(db, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def add(db: dict, postings: list[dict]) -> int:
    """Merge postings into db; a job seen on several sites keeps one row with all its sources."""
    by_id = {p["id"]: p for p in db["postings"]}
    added = 0
    for p in postings:
        old = by_id.get(p["id"])
        if old is None:
            db["postings"].append(p)
            by_id[p["id"]] = p
            added += 1
            continue
        names = {s["name"] for s in old["sources"]}
        old["sources"] += [s for s in p["sources"] if s["name"] not in names]
        old["skillsets"] = sorted(set(old["skillsets"]) | set(p["skillsets"]))
        if old.get("experience_estimated") and not p.get("experience_estimated"):
            old.update(experience=p["experience"], years_min=p["years_min"], experience_estimated=False)
        for f in ("salary", "summary", "job_type"):
            old[f] = old.get(f) or p.get(f, "")
        old["posted"] = min(old["posted"], p["posted"])  # earliest sighting is the real post time
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--merge", type=Path, help="JSON list of postings found in a browser")
    ap.add_argument("--skip-feeds", action="store_true", help="only merge, don't poll the feeds")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    db = load()
    db["skillsets"] = {k: v["label"] for k, v in SKILLSETS.items()}
    found: list[dict] = []
    report: dict[str, str] = {}

    if not args.skip_feeds:
        for name, feed in FEEDS.items():
            n = 0
            try:
                for raw in feed():
                    p = make_posting(raw, now)
                    if p:
                        found.append(p)
                        n += 1
                report[name] = f"{n} new in last 24h"
            except Exception as e:  # one broken feed must not stop the others
                report[name] = f"unavailable ({type(e).__name__})"
    if args.merge:
        counts: dict[str, int] = {}
        for raw in json.loads(args.merge.read_text(encoding="utf-8")):
            src = raw.get("source") or "Web"
            counts.setdefault(src, 0)
            p = make_posting(raw, now)
            if p:
                found.append(p)
                counts[src] += 1
        report.update({src: f"{n} new in last 24h" for src, n in counts.items()})

    added = add(db, found)
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    db["postings"] = sorted((p for p in db["postings"] if p["posted"] >= cutoff),
                            key=lambda p: p["posted"], reverse=True)
    db["updated"] = now.isoformat(timespec="minutes")
    db["runs"] = (db.get("runs") or [])[-89:] + [{"at": db["updated"], "added": added, "sources": report}]
    save(db)
    print(json.dumps({"added": added, "total": len(db["postings"]), "sources": report}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
