"""Fetchers for public ATS job-board APIs.

Every fetcher takes a Company and returns a list[Job]. Only official, public,
unauthenticated JSON endpoints that the ATS vendors expose for career sites are
used - no LinkedIn/Indeed scraping.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import quote

from .http import HttpError, request_json
from .models import Company, Job

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)  # greenhouse double-escapes
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>|</h\d>", "\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def parse_dt(v) -> datetime | None:
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):  # epoch ms (lever)
            return datetime.fromtimestamp(v / 1000, tz=timezone.utc)
        s = str(v).replace("Z", "+00:00")
        if len(s) == 10:
            s += "T00:00:00+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- Greenhouse
def fetch_greenhouse(c: Company, ctx: "FetchContext") -> list[Job]:
    data = request_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(c.slug)}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        desc = html_to_text(j.get("content"))
        out.append(Job(
            company=c.name, source="greenhouse", ext_id=str(j["id"]), title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""), description=desc,
            posted_at=parse_dt(j.get("first_published")), updated_at=parse_dt(j.get("updated_at")),
            req_id=str(j.get("requisition_id") or ""),
            department=", ".join(d.get("name", "") for d in j.get("departments") or []),
            segment=c.segment,
        ))
    return out


# --------------------------------------------------------------------------- Lever
def fetch_lever(c: Company, ctx: "FetchContext") -> list[Job]:
    data = request_json(f"https://api.lever.co/v0/postings/{quote(c.slug)}?mode=json")
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        sal = j.get("salaryRange") or {}
        salary = ""
        if sal.get("min"):
            salary = f"{sal.get('currency', '')} {sal.get('min')}-{sal.get('max')} {sal.get('interval', '')}".strip()
        desc = "\n".join(filter(None, [
            j.get("descriptionPlain") or j.get("openingPlain"), j.get("descriptionBodyPlain"),
            "\n".join(f"{l.get('text')}\n{html_to_text(l.get('content'))}" for l in j.get("lists") or []),
            j.get("additionalPlain"), j.get("salaryDescriptionPlain"),
        ]))
        out.append(Job(
            company=c.name, source="lever", ext_id=j["id"], title=j.get("text", ""),
            location=", ".join(cats.get("allLocations") or [cats.get("location") or ""]),
            url=j.get("hostedUrl", ""), description=desc, posted_at=parse_dt(j.get("createdAt")),
            remote=(j.get("workplaceType") or "").lower(), salary=salary,
            department=cats.get("team") or "", employment_type=cats.get("commitment") or "",
            segment=c.segment, extra={"country": j.get("country", "")},
        ))
    return out


# --------------------------------------------------------------------------- Ashby
def fetch_ashby(c: Company, ctx: "FetchContext") -> list[Job]:
    data = request_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(c.slug)}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        comp = (j.get("compensation") or {}).get("scrapeableCompensationSalarySummary") or \
               (j.get("compensation") or {}).get("compensationTierSummary") or ""
        out.append(Job(
            company=c.name, source="ashby", ext_id=j["id"], title=j.get("title", ""),
            location=" / ".join(l for l in locs if l), url=j.get("jobUrl", ""),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            posted_at=parse_dt(j.get("publishedAt")), remote=(j.get("workplaceType") or "").lower(),
            salary=comp, department=j.get("department") or "", employment_type=j.get("employmentType") or "",
            segment=c.segment,
        ))
    return out


# --------------------------------------------------------------------------- SmartRecruiters
def fetch_smartrecruiters(c: Company, ctx: "FetchContext") -> list[Job]:
    out, offset = [], 0
    while True:
        data = request_json(f"https://api.smartrecruiters.com/v1/companies/{quote(c.slug)}/postings"
                            f"?limit=100&offset={offset}&country=us")
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            job = Job(
                company=c.name, source="smartrecruiters", ext_id=str(j["id"]), title=j.get("name", ""),
                location=loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")])),
                url=f"https://jobs.smartrecruiters.com/{c.slug}/{j['id']}",
                posted_at=parse_dt(j.get("releasedDate")), req_id=j.get("refNumber") or "",
                remote="remote" if loc.get("remote") else ("hybrid" if loc.get("hybrid") else ""),
                employment_type=(j.get("typeOfEmployment") or {}).get("label", ""),
                department=(j.get("function") or {}).get("label", ""), segment=c.segment,
                extra={"experience_level": (j.get("experienceLevel") or {}).get("id", "")},
            )
            out.append(job)
        offset += len(items)
        if not items or offset >= data.get("totalFound", 0) or offset >= 2000:
            break
    # descriptions only for jobs whose title passes the filter (saves hundreds of calls)
    for job in out:
        if ctx.wants_title(job.title):
            cached = ctx.cache.get(job.uid)
            if cached:
                job.description, job.url = cached["description"], cached["url"]
                continue
            try:
                d = request_json(f"https://api.smartrecruiters.com/v1/companies/{quote(c.slug)}/postings/{job.ext_id}")
                secs = ((d.get("jobAd") or {}).get("sections") or {})
                job.description = "\n".join(html_to_text((secs.get(k) or {}).get("text"))
                                            for k in ("jobDescription", "qualifications", "additionalInformation"))
                job.url = d.get("postingUrl") or d.get("applyUrl") or job.url
                ctx.cache.put(job.uid, {"description": job.description, "url": job.url})
            except Exception:
                pass
    return out


# --------------------------------------------------------------------------- Workable
def fetch_workable(c: Company, ctx: "FetchContext") -> list[Job]:
    data = request_json(f"https://apply.workable.com/api/v1/widget/accounts/{quote(c.slug)}?details=true")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        out.append(Job(
            company=c.name, source="workable", ext_id=j.get("shortcode") or j.get("id", ""),
            title=j.get("title", ""), location=loc, url=j.get("url") or j.get("application_url", ""),
            description=html_to_text(j.get("description")),
            posted_at=parse_dt(j.get("published_on") or j.get("created_at")),
            remote="remote" if j.get("telecommuting") else "", employment_type=j.get("employment_type") or "",
            department=j.get("department") or "", segment=c.segment,
        ))
    return out


# --------------------------------------------------------------------------- Recruitee
def fetch_recruitee(c: Company, ctx: "FetchContext") -> list[Job]:
    data = request_json(f"https://{c.slug}.recruitee.com/api/offers/")
    out = []
    for j in data.get("offers", []):
        out.append(Job(
            company=c.name, source="recruitee", ext_id=str(j["id"]), title=j.get("title", ""),
            location=j.get("location") or ", ".join(filter(None, [j.get("city"), j.get("country")])),
            url=j.get("careers_url", ""),
            description=html_to_text((j.get("description") or "") + (j.get("requirements") or "")),
            posted_at=parse_dt(j.get("published_at") or j.get("created_at")),
            remote="remote" if j.get("remote") else "", employment_type=j.get("employment_type_code") or "",
            department=j.get("department") or "", segment=c.segment,
        ))
    return out


# --------------------------------------------------------------------------- Workday
_POSTED = re.compile(r"Posted\s+(Today|Yesterday|(\d+)\+?\s+Days?\s+Ago)", re.I)


def _workday_posted(text: str) -> datetime | None:
    m = _POSTED.search(text or "")
    if not m:
        return None
    if m.group(1).lower() == "today":
        days = 0
    elif m.group(1).lower() == "yesterday":
        days = 1
    else:
        days = int(m.group(2))
    return _now() - timedelta(days=days)


def fetch_workday(c: Company, ctx: "FetchContext") -> list[Job]:
    base = f"https://{c.host}/wday/cxs/{c.slug}/{c.site}"
    seen: dict[str, Job] = {}
    for query in ctx.workday_queries:
        offset, total = 0, None
        while True:
            data = request_json(f"{base}/jobs", method="POST", payload={
                "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": query})
            if total is None:
                total = data.get("total", 0)
            posts = data.get("jobPostings") or []
            for p in posts:
                path = p.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen[path] = Job(
                    company=c.name, source="workday", ext_id=path.rsplit("_", 1)[-1] if "_" in path else path,
                    title=p.get("title", ""), location=p.get("locationsText", ""),
                    url=f"https://{c.host}/{c.site}{path}",
                    posted_at=_workday_posted(p.get("postedOn", "")),
                    req_id=(p.get("bulletFields") or [""])[0], segment=c.segment,
                    extra={"path": path, "posted_text": p.get("postedOn", "")},
                )
            offset += 20
            # results are newest-first: stop once we're past the age cutoff
            oldest = _workday_posted(posts[-1].get("postedOn", "")) if posts else None
            too_old = oldest is not None and (_now() - oldest).days > ctx.max_age_days
            if not posts or too_old or offset >= min(total or 0, ctx.workday_max_per_query):
                break
    jobs = list(seen.values())
    # detail call only for plausible titles: gives full description, absolute start date, remote type
    for job in jobs:
        if not ctx.wants_title(job.title):
            continue
        d = ctx.cache.get(job.uid)
        if d is None:
            try:
                d = request_json(f"{base}{job.extra['path']}").get("jobPostingInfo", {})
            except Exception:
                continue
            d = {k: d.get(k) for k in ("jobDescription", "startDate", "jobReqId", "remoteType", "timeType",
                                       "externalUrl", "location", "additionalLocations", "country", "endDate",
                                       "questionnaireId")}
            ctx.cache.put(job.uid, d)
        job.description = html_to_text(d.get("jobDescription"))
        job.posted_at = parse_dt(d.get("startDate")) or job.posted_at
        job.req_id = d.get("jobReqId") or job.req_id
        job.remote = (d.get("remoteType") or "").lower()
        job.employment_type = d.get("timeType") or ""
        job.url = d.get("externalUrl") or job.url
        loc = d.get("location") or ""
        extra_locs = d.get("additionalLocations") or []
        if loc:
            job.location = " / ".join([loc] + list(extra_locs))
        job.extra["country"] = (d.get("country") or {}).get("descriptor", "")
        job.extra["end_date"] = d.get("endDate") or ""
        job.extra["has_questionnaire"] = bool(d.get("questionnaireId"))
    return jobs


# --------------------------------------------------------------------------- Oracle Recruiting Cloud
def fetch_oracle(c: Company, ctx: "FetchContext") -> list[Job]:
    base = f"https://{c.host}/hcmRestApi/resources/latest"
    jobs: dict[str, Job] = {}
    for query in ctx.workday_queries:
        offset = 0
        while True:
            kw = quote(f'"{query}"')
            data = request_json(
                f"{base}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
                f"&finder=findReqs;siteNumber={c.site},keyword={kw},limit=200,offset={offset},sortBy=POSTING_DATES_DESC")
            item = (data.get("items") or [{}])[0]
            reqs = item.get("requisitionList") or []
            for r in reqs:
                rid = str(r.get("Id"))
                if rid in jobs:
                    continue
                locs = [r.get("PrimaryLocation") or ""] + [x.get("Name", "") for x in r.get("secondaryLocations") or []]
                jobs[rid] = Job(
                    company=c.name, source="oracle", ext_id=rid, title=r.get("Title", ""),
                    location=" / ".join(l for l in locs if l),
                    url=f"https://{c.host}/hcmUI/CandidateExperience/en/sites/{c.site}/job/{rid}",
                    description=r.get("ShortDescriptionStr") or "", posted_at=parse_dt(r.get("PostedDate")),
                    remote=(r.get("WorkplaceType") or "").lower(), segment=c.segment,
                    extra={"country": r.get("PrimaryLocationCountry") or ""},
                )
            offset += len(reqs)
            if not reqs or offset >= (item.get("TotalJobsCount") or 0) or offset >= 1000:
                break
    for job in jobs.values():
        if not ctx.wants_title(job.title):
            continue
        d = ctx.cache.get(job.uid)
        if d is None:
            try:
                d = (request_json(f"{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
                                  f"&finder=ById;Id=%22{job.ext_id}%22,siteNumber={c.site}").get("items") or [{}])[0]
            except Exception:
                continue
            d = {k: d.get(k) for k in ("ExternalDescriptionStr", "ExternalQualificationsStr",
                                       "ExternalResponsibilitiesStr", "ExternalPostedEndDate", "RequisitionId")}
            ctx.cache.put(job.uid, d)
        job.description = html_to_text("\n".join(filter(None, [d.get("ExternalDescriptionStr"),
                                       d.get("ExternalResponsibilitiesStr"), d.get("ExternalQualificationsStr")])))
        job.req_id = d.get("RequisitionId") or ""
        job.extra["end_date"] = d.get("ExternalPostedEndDate") or ""
    return list(jobs.values())


# --------------------------------------------------------------------------- Phenom
def fetch_phenom(c: Company, ctx: "FetchContext") -> list[Job]:
    lang, _, country = (c.site or "en_us/us").partition("/")
    url = f"https://{c.host}/widgets"
    jobs: dict[str, Job] = {}
    for query in ctx.workday_queries:
        start = 0
        while True:
            data = request_json(url, method="POST", payload={
                "lang": lang, "deviceType": "desktop", "country": country, "pageName": "search-results",
                "ddoKey": "refineSearch", "from": start, "size": 100, "jobs": True, "counts": True,
                "keywords": query, "global": True, "selected_fields": {},
                "sort": {"order": "desc", "field": "postedDate"}})
            rs = data.get("refineSearch") or {}
            items = (rs.get("data") or {}).get("jobs") or []
            for j in items:
                jid = str(j.get("jobId") or j.get("reqId"))
                if jid in jobs:
                    continue
                loc = j.get("location") or ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
                multi = [m.get("location", "") for m in j.get("multi_location") or [] if isinstance(m, dict)]
                jobs[jid] = Job(
                    company=c.name, source="phenom", ext_id=jid, title=j.get("title", ""),
                    location=" / ".join(dict.fromkeys([loc] + multi)) if multi else loc,
                    url=f"https://{c.host}/{country}/{lang.split('_')[0]}/job/{quote(jid)}",
                    description=j.get("descriptionTeaser") or "", posted_at=parse_dt(j.get("postedDate")),
                    req_id=j.get("reqId") or "", department=j.get("category") or "", segment=c.segment,
                    extra={"country": j.get("country") or "", "created": j.get("dateCreated") or ""},
                )
            start += len(items)
            if not items or start >= (rs.get("totalHits") or 0) or start >= 1000:
                break
    for job in jobs.values():
        if not ctx.wants_title(job.title):
            continue
        d = ctx.cache.get(job.uid)
        if d is None:
            try:
                r = request_json(url, method="POST", payload={
                    "lang": lang, "deviceType": "desktop", "country": country, "pageName": "job",
                    "ddoKey": "jobDetail", "jobId": job.ext_id})
                d = {"description": (((r.get("jobDetail") or {}).get("data") or {}).get("job") or {}).get("description")}
            except Exception:
                continue
            ctx.cache.put(job.uid, d)
        job.description = html_to_text(d.get("description")) or job.description
    return list(jobs.values())


# --------------------------------------------------------------------------- Eightfold
def fetch_eightfold(c: Company, ctx: "FetchContext") -> list[Job]:
    base = f"https://{c.host}"
    jobs: dict[str, Job] = {}
    for query in ctx.workday_queries:
        start = 0
        while True:
            data = request_json(f"{base}/api/pcsx/search?domain={quote(c.slug)}&query={quote(query)}"
                                f"&location=&start={start}&sort_by=timestamp")
            d = data.get("data") or {}
            pos = d.get("positions") or []
            for j in pos:
                jid = str(j.get("id"))
                if jid in jobs:
                    continue
                ts = j.get("postedTs") or j.get("creationTs")
                jobs[jid] = Job(
                    company=c.name, source="eightfold", ext_id=jid, title=j.get("name", ""),
                    location=" / ".join(j.get("standardizedLocations") or j.get("locations") or []),
                    url=f"{base}/careers/job/{jid}", posted_at=parse_dt(ts * 1000) if ts else None,
                    req_id=str(j.get("displayJobId") or j.get("atsJobId") or ""),
                    remote=(j.get("workLocationOption") or "").lower(), department=j.get("department") or "",
                    segment=c.segment,
                )
            start += len(pos)
            oldest = pos[-1].get("postedTs") if pos else None
            too_old = oldest and (_now() - datetime.fromtimestamp(oldest, tz=timezone.utc)).days > ctx.max_age_days
            if not pos or too_old or start >= (d.get("count") or 0) or start >= 600:
                break
    for job in jobs.values():
        if not ctx.wants_title(job.title):
            continue
        d = ctx.cache.get(job.uid)
        if d is None:
            try:
                r = request_json(f"{base}/api/pcsx/position_details?position_id={job.ext_id}&domain={quote(c.slug)}")
                d = {"description": (r.get("data") or {}).get("jobDescription"),
                     "url": (r.get("data") or {}).get("publicUrl")}
            except Exception:
                continue
            ctx.cache.put(job.uid, d)
        job.description = html_to_text(d.get("description"))
        job.url = d.get("url") or job.url
    return list(jobs.values())


FETCHERS: dict[str, Callable[[Company, "FetchContext"], list[Job]]] = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workable": fetch_workable,
    "recruitee": fetch_recruitee,
    "workday": fetch_workday,
    "oracle": fetch_oracle,
    "phenom": fetch_phenom,
    "eightfold": fetch_eightfold,
}


class DetailCache:
    """Job-detail responses keyed by job uid, so each posting's detail page is fetched once, ever."""
    def __init__(self, data: dict | None = None):
        self.data = data or {}
        self.fresh: dict[str, dict] = {}

    def get(self, uid: str) -> dict | None:
        return self.data.get(uid)

    def put(self, uid: str, value: dict) -> None:
        self.data[uid] = self.fresh[uid] = value


class FetchContext:
    def __init__(self, wants_title: Callable[[str], bool], workday_queries: list[str],
                 workday_max_per_query: int = 400, max_age_days: int = 60, cache: DetailCache | None = None):
        self.wants_title = wants_title
        self.workday_queries = workday_queries
        self.workday_max_per_query = workday_max_per_query
        self.max_age_days = max_age_days
        self.cache = cache or DetailCache()


def fetch_company(c: Company, ctx: FetchContext) -> list[Job]:
    fn = FETCHERS.get(c.ats)
    if fn is None:
        raise ValueError(f"unsupported ats {c.ats!r}")
    return fn(c, ctx)


# --------------------------------------------------------------------------- ATS discovery
_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"([A-Za-z0-9-]+)\.recruitee\.com")),
    ("workday", re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
]


def detect_from_text(text: str) -> list[tuple[str, tuple]]:
    hits = []
    for ats, pat in _PATTERNS:
        for m in pat.finditer(text):
            g = m.groups()
            if ats == "workday" and g[2].lower() in ("wday", "job", "en-us"):
                continue
            if (ats, g) not in hits:
                hits.append((ats, g))
    return hits


def probe_slug(ats: str, slug: str) -> int:
    """Return number of postings for a guessed slug, or -1 if it doesn't exist."""
    urls = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "smartrecruiters": f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
    }
    try:
        d = request_json(urls[ats], retries=0, timeout=10)
    except (HttpError, Exception):
        return -1
    if ats == "lever":
        return len(d) if isinstance(d, list) else -1
    if ats == "smartrecruiters":
        return d.get("totalFound", 0) or -1
    return len(d.get("jobs", []))
