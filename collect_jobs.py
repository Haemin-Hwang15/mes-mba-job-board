import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from html import unescape
from urllib.parse import quote

BASE = Path(__file__).resolve().parent
KEYWORDS = ('strategy', 'strategic', 'finance', 'financial', 'business operations',
            'bizops', 'business development', 'marketing', 'growth', 'monetization',
            'pricing', 'corporate development', 'partnership', 'product manager',
            'product management', 'program manager', 'chief of staff', 'commercial',
            'revenue', 'market research', 'business analyst', 'business intelligence')
EXCLUDE = ('software engineer', 'data engineer', 'security engineer',
           'graphic designer', 'account executive', 'sales representative',
           'director', 'vice president', 'vp ', 'head of ', 'principal', 'staff engineer')

def relevant(title, description=''):
    t = title.lower()
    if any(x in t for x in EXCLUDE):
        return False
    if re.search(r'\b(2025|2026|2028|2029)\b', t) and '2027' not in t:
        return False
    return any(x in t for x in KEYWORDS) or ('mba' in t)

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent':'MES-MBA-JobBoard/1.0', 'Accept':'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def iso_ms(value):
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()

def collect(c):
    p, board = c['platform'], quote(c['board'], safe='')
    if p == 'greenhouse':
        raw = fetch(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true')['jobs']
        rows = [dict(id=str(j['id']), title=j.get('title',''), location=(j.get('location') or {}).get('name',''),
                     category=((j.get('departments') or [{}])[0].get('name') or 'Business'),
                     posted=j.get('first_published'), updated=j.get('updated_at'),
                     url=j.get('absolute_url'), description=j.get('content') or '') for j in raw]
    elif p == 'lever':
        raw = fetch(f'https://api.lever.co/v0/postings/{board}?mode=json')
        rows = [dict(id=str(j['id']), title=j.get('text',''), location=(j.get('categories') or {}).get('location',''),
                     category=(j.get('categories') or {}).get('team') or 'Business',
                     posted=iso_ms(j.get('createdAt')), updated=None,
                     url=j.get('hostedUrl') or j.get('applyUrl'), description=j.get('descriptionPlain') or '') for j in raw]
    elif p == 'ashby':
        raw = fetch(f'https://api.ashbyhq.com/posting-api/job-board/{board}')['jobs']
        rows = [dict(id=str(j.get('id') or j.get('jobUrl')), title=j.get('title',''),
                     location=j.get('location') or '', category=j.get('department') or 'Business',
                     posted=j.get('publishedAt'), updated=None,
                     url=j.get('jobUrl') or j.get('applyUrl'), description=j.get('descriptionPlain') or '')
                for j in raw if j.get('isListed', True)]
    else:
        raise ValueError('Unsupported platform: ' + p)
    out = []
    for j in rows:
        if not relevant(j['title'], j['description']) or not j['url']:
            continue
        intern = bool(re.search(r'\b(intern|internship)\b', j['title'], re.I))
        out.append(dict(id=f'{p}-{board}-{j["id"]}', company=c['name'], industry=c['industry'],
                        title=j['title'], location=j['location'], category=j['category'],
                        job_type='Internship' if intern else 'Full-time / Other',
                        posted_date=j['posted'], updated_date=j['updated'],
                        deadline=None, visa_sponsorship='Not specified',
                        company_website=j['url'], apply_url=j['url'], source=p.title()))
    return len(rows), out

def main():
    companies = json.loads((BASE/'sources.json').read_text(encoding='utf-8'))['companies']
    jobs, failures, successes = {}, [], 0
    for c in companies:
        try:
            total, selected = collect(c)
            successes += 1
            for j in selected:
                jobs[j['id']] = j
            print(f'OK {c["name"]}: {len(selected)} relevant / {total} total', flush=True)
        except Exception as e:
            failures.append(c['name'])
            print(f'FAILED {c["name"]}: {type(e).__name__}: {e}', flush=True)
    if successes == 0:
        raise RuntimeError('All sources failed; keeping previous jobs.json')
    data = dict(last_updated=datetime.now(timezone.utc).isoformat(), sources_checked=successes,
                sources_failed=failures, total_jobs=len(jobs),
                jobs=sorted(jobs.values(), key=lambda j:j['posted_date'] or '', reverse=True))
    (BASE/'jobs.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved {len(jobs)} jobs from {successes} sources; failed: {len(failures)}')

if __name__ == '__main__':
    main()
