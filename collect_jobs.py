"""Bulk MES job collection. No API keys or third-party packages needed."""
import json, re, urllib.request, urllib.error, time, hashlib, xml.etree.ElementTree as ET, html
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parent
KEYWORDS = ('strategy','strategic','finance','financial','business operations','bizops',
 'business development','marketing','growth','monetization','pricing','corporate development',
 'partnership','product manager','product management','program manager','chief of staff',
 'commercial','revenue','market research','business analyst','business intelligence')
EXCLUDE = ('software engineer','data engineer','security engineer','graphic designer',
 'account executive','sales representative','vice president','vp ','head of ',
 'principal','staff engineer')
PLATFORMS = ('greenhouse','lever','ashby')

def relevant(title):
 t=title.lower()
 if any(x in t for x in EXCLUDE): return False
 if re.search(r'\b(2025|2026|2028|2029)\b',t) and '2027' not in t: return False
 return any(x in t for x in KEYWORDS) or bool(re.search(r'\bmba\b',t))

def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; MESJobBoard/1.0)', 'Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=8) as response:
  return json.load(response)

def date_ms(value):
 return datetime.fromtimestamp(value/1000,tz=timezone.utc).isoformat() if value else None

def collect(company,platform):
 board=quote(company['board'],safe='')
 if platform=='greenhouse':
  raw=get(f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true')['jobs']
  rows=[(str(j['id']),j.get('title',''),(j.get('location') or {}).get('name',''),
   ((j.get('departments') or [{}])[0].get('name') or 'Business'),j.get('first_published'),
   j.get('updated_at'),j.get('absolute_url')) for j in raw]
 elif platform=='lever':
  raw=get(f'https://api.lever.co/v0/postings/{board}?mode=json')
  rows=[(str(j['id']),j.get('text',''),(j.get('categories') or {}).get('location',''),
   (j.get('categories') or {}).get('team') or 'Business',date_ms(j.get('createdAt')),
   None,j.get('hostedUrl') or j.get('applyUrl')) for j in raw]
 elif platform=='ashby':
  raw=get(f'https://api.ashbyhq.com/posting-api/job-board/{board}')['jobs']
  rows=[(str(j.get('id') or j.get('jobUrl')),j.get('title',''),j.get('location') or '',
   j.get('department') or 'Business',j.get('publishedAt'),None,
   j.get('jobUrl') or j.get('applyUrl')) for j in raw if j.get('isListed',True)]
 else: raise ValueError('Unknown platform')
 jobs=[]
 for jid,title,location,category,posted,updated,url in rows:
  if not url or not relevant(title): continue
  internship=bool(re.search(r'\b(intern|internship)\b',title,re.I))
  jobs.append(dict(id=f'{platform}-{board}-{jid}',company=company['name'],
   industry=company['industry'],title=title,location=location,category=category,
   job_type='Internship' if internship else 'Full-time / Other',posted_date=posted,
   updated_date=updated,deadline=None,visa_sponsorship='Not specified',
   company_website=url,apply_url=url,source=platform.title()))
 return len(rows),jobs

# Optional public sitemap + JobPosting structured-data adapter.
# Only emits jobs when a real job detail page contains schema.org JobPosting.
def fetch_text(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; MESJobBoard/1.1)','Accept':'text/html,application/xml,*/*'})
 with urllib.request.urlopen(req,timeout=12) as response:
  return response.read(2500000).decode('utf-8','replace')

def sitemap_links(url, depth=0):
 if depth>1: return []
 try:
  root=ET.fromstring(fetch_text(url))
 except Exception: return []
 ns='{http://www.sitemaps.org/schemas/sitemap/0.9}'
 if root.tag.endswith('sitemapindex'):
  nested=[x.text for x in root.findall('.//'+ns+'loc') if x.text]
  priority=[x for x in nested if any(w in x.lower() for w in ('job','career','position','vacanc'))]
  return [v for sub in (priority or nested[:5])[:8] for v in sitemap_links(sub,depth+1)]
 return [x.text for x in root.findall('.//'+ns+'loc') if x.text]

def job_objects(obj):
 if isinstance(obj,list):
  for v in obj: yield from job_objects(v)
 elif isinstance(obj,dict):
  typ=obj.get('@type',[])
  if typ=='JobPosting' or isinstance(typ,list) and 'JobPosting' in typ: yield obj
  for key in ('@graph','mainEntity'):
   if key in obj: yield from job_objects(obj[key])

def collect_sitemap(company):
 root=company.get('careers_url','').rstrip('/')
 if not root: raise ValueError('Missing careers_url')
 domain=urlparse(root).netloc
 candidates=company.get('sitemaps') or [f'https://{domain}/sitemap.xml',f'https://{domain}/sitemap_index.xml']
 links=[]
 for sm in candidates:
  links.extend(sitemap_links(sm))
  if links: break
 # Avoid crawling non-job pages; only process relevant job-looking URLs.
 links=list(dict.fromkeys(u for u in links if re.search(r'(/job[s]?/|/careers/.*/|/position[s]?/|/vacanc|/requisition)',u,re.I)))[:350]
 jobs=[]
 for url in links:
  try:
   page=fetch_text(url)
   for match in re.findall(r'<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>',page,re.I|re.S):
    try: objs=list(job_objects(json.loads(html.unescape(match))))
    except (ValueError,TypeError): continue
    for obj in objs:
     title=html.unescape(re.sub('<[^>]+>','',str(obj.get('title','')))).strip()
     if not relevant(title): continue
     loc=obj.get('jobLocation',{})
     if isinstance(loc,list): loc=loc[0] if loc else {}
     address=loc.get('address',{}) if isinstance(loc,dict) else {}
     location=', '.join(str(address.get(k,'')) for k in ('addressLocality','addressRegion','addressCountry') if address.get(k)) if isinstance(address,dict) else ''
     apply=obj.get('url') or url
     if not isinstance(apply,str) or not apply.startswith('http'): apply=url
     jid=hashlib.sha256(apply.encode()).hexdigest()[:20]
     jobs.append(dict(id=f'sitemap-{company["name"].lower().replace(" ","-")}-{jid}',company=company['name'],industry=company['industry'],title=title,location=location,category='Business',job_type='Internship' if re.search(r'\b(intern|internship)\b',title,re.I) else 'Full-time / Other',posted_date=obj.get('datePosted'),updated_date=None,deadline=obj.get('validThrough'),visa_sponsorship='Not specified',company_website=root,apply_url=apply,source='Official careers page'))
  except Exception: continue
 return len(links),jobs

def main():
 companies=json.loads((BASE/'sources.json').read_text(encoding='utf-8'))['companies']
 old_path=BASE/'jobs.json'
 old=json.loads(old_path.read_text(encoding='utf-8')) if old_path.exists() else {'jobs':[]}
 old_by_company={}
 for job in old.get('jobs',[]): old_by_company.setdefault(job['company'],[]).append(job)
 jobs={}; failed=[]; successes=0; found_companies=[]
 for company in companies:
  platforms=PLATFORMS + (('sitemap',) if company.get('careers_url') else ()) if company.get('platform')=='auto' else (company['platform'],)
  errors=[]; connected=False
  for platform in platforms:
   try:
    total,selected=collect_sitemap(company) if platform=='sitemap' else collect(company,platform)
    if platform=='sitemap' and total==0: raise ValueError('No job URLs in public sitemap')
    successes+=1; connected=True;found_companies.append(company['name'])
    for job in selected: jobs[job['id']]=job
    print(f'OK {company["name"]} [{platform}]: {len(selected)} relevant / {total} total',flush=True)
    break
   except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,KeyError,ValueError) as exc:
    errors.append(f'{platform}:{type(exc).__name__}')
   except Exception as exc:
    errors.append(f'{platform}:{type(exc).__name__}')
  if not connected:
   failed.append(company['name'])
   preserved=old_by_company.get(company['name'],[])
   for job in preserved: jobs[job['id']]=job
   print(f'UNAVAILABLE {company["name"]} ({", ".join(errors)}); retained {len(preserved)} prior jobs',flush=True)
 if successes==0: raise RuntimeError('No sources connected. Previous jobs.json preserved.')
 result=dict(last_updated=datetime.now(timezone.utc).isoformat(),sources_checked=successes,
  sources_failed=failed,total_jobs=len(jobs),jobs=sorted(jobs.values(),
  key=lambda j:j.get('posted_date') or '',reverse=True))
 old_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(f'FINISHED: {successes}/{len(companies)} connected, {len(jobs)} jobs, {len(failed)} unavailable',flush=True)

if __name__=='__main__': main()
