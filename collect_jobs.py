
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Business functions relevant to MBA students
BUSINESS_KEYWORDS = [
    "strategy", "strategic", "finance", "financial",
    "business operations", "bizops", "business development",
    "marketing", "growth", "monetization", "pricing",
    "corporate development", "partnerships",
    "product management", "program management",
    "chief of staff", "commercial", "analytics",
    "revenue management", "market research"
]

# Exclude unrelated functions
EXCLUDE_KEYWORDS = [
    "software engineer", "data engineer",
    "security engineer", "graphic designer",
    "account executive", "sales representative"
]

def is_relevant(title, description=""):
    title_lower = title.lower()
    text = (title + " " + description).lower()

    if any(word in title_lower for word in EXCLUDE_KEYWORDS):
        return False

    business_match = any(
        word in title_lower for word in BUSINESS_KEYWORDS
    )

    mba_match = bool(re.search(
        r"\b(mba|business school)\b", text
    ))

    internship = bool(re.search(
        r"\b(intern|internship)\b", title_lower
    ))

    # Include 2027 internships, but avoid known other years.
    other_year = bool(re.search(
        r"\b(2025|2026|2028|2029)\b", title_lower
    ))

    if internship and other_year and "2027" not in title_lower:
        return False

    # Business internships or MBA-specific positions
    return business_match or mba_match

def get_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MES-MBA-JobBoard/1.0",
            "Accept": "application/json"
        }
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)

def collect_greenhouse(company):
    board = company["board"]
    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        + board + "/jobs?content=true"
    )

    data = get_json(url)
    results = []

    for item in data.get("jobs", []):
        title = item.get("title", "")
        description = item.get("content") or ""

        if not is_relevant(title, description):
            continue

        locations = item.get("location") or {}
        location = locations.get("name", "Not specified")

        departments = item.get("departments") or []
        category = (
            departments[0].get("name", "Business")
            if departments else "Business"
        )

        is_intern = bool(re.search(
            r"\b(intern|internship)\b", title.lower()
        ))

        results.append({
            "id": f"greenhouse-{board}-{item['id']}",
            "company": company["name"],
            "industry": company["industry"],
            "title": title,
            "location": location,
            "category": category,
            "job_type": "Internship" if is_intern else "Full-time / Other",
            "posted_date": item.get("first_published"),
            "updated_date": item.get("updated_at"),
            "deadline": None,
            "visa_sponsorship": "Not specified",
            "company_website": url,
            "apply_url": item.get("absolute_url"),
            "source": "Greenhouse"
        })

    return results

def main():
    with open(BASE / "sources.json", encoding="utf-8") as f:
        companies = json.load(f)["companies"]

    jobs = {}
    successes = 0
    failures = []

    for company in companies:
        print(f"Checking {company['name']}...")

        try:
            if company["platform"] == "greenhouse":
                found = collect_greenhouse(company)
            else:
                raise ValueError("Unsupported platform")

            successes += 1

            for job in found:
                jobs[job["id"]] = job

            print(f"  Found {len(found)} relevant jobs")

        except Exception as e:
            failures.append(company["name"])
            print(f"  ERROR: {e}")

    # Never replace existing results with an empty file
    # when all sources fail.
    if successes == 0:
        raise RuntimeError(
            "No sources succeeded. Existing data preserved."
        )

    output = {
        "last_updated": datetime.now(
            timezone.utc
        ).isoformat(),
        "sources_checked": successes,
        "sources_failed": failures,
        "total_jobs": len(jobs),
        "jobs": sorted(
            jobs.values(),
            key=lambda x: x.get("posted_date") or "",
            reverse=True
        )
    }

    with open(BASE / "jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(jobs)} jobs to jobs.json")

if __name__ == "__main__":
    main()
