"""Turns the "url ~ title ~ company ~ location ~ posted ~ skillset ~ type ~ salary" lines from browser_scrapers.js
into a --merge file for collect.py.

    python collector/lines_to_json.py <Source name> lines.txt [more.txt ...] -o browser-results.json --append
"""
import argparse
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("files", nargs="+", type=Path)
ap.add_argument("-o", "--out", type=Path, default=Path("browser-results.json"))
ap.add_argument("--append", action="store_true", help="add to an existing output file")
a = ap.parse_args()

rows = json.loads(a.out.read_text(encoding="utf-8")) if a.append and a.out.exists() else []
for f in a.files:
    for line in f.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split(" ~ ")]
        if len(parts) < 6 or not parts[0].startswith("http"):
            continue
        url, title, company, location, posted, skillset = parts[:6]
        rows.append({"title": title, "company": company, "location": location, "posted": posted or "today",
                     "source": a.source, "apply_url": url, "skillset": skillset, "description": "",
                     "job_type": parts[6] if len(parts) > 6 else "", "salary": parts[7] if len(parts) > 7 else "",
                     "remote": "remote" in location.lower()})
a.out.write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"{len(rows)} rows in {a.out}")
