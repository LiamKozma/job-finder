from __future__ import annotations

import argparse
import re
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from . import __version__
from .config import DATA_DIR, REPORTS_DIR, add_company, load_companies, load_profile, save_companies
from .http import get_text
from .models import Company, Job
from .report import print_summary, write_csv, write_html
from .scoring import days_old, score_job, title_matches
from .sec import restructuring_days
from .sources import DetailCache, FetchContext, detect_from_text, fetch_company, probe_slug
from .staleness import build_contexts
from .store import Store


def _console_utf8() -> None:
    # Windows consoles default to cp1252; don't crash on an accented company name.
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def cmd_run(args, progress=None) -> int:
    """progress(done, total, postings, message) is called as employers finish (used by the app window)."""
    progress = progress or (lambda *a: None)
    profile = load_profile()
    companies = load_companies()
    if args.segment:
        companies = [c for c in companies if c.segment in args.segment]
    if args.company:
        needle = args.company.lower()
        companies = [c for c in companies if needle in c.name.lower()]
    if not companies:
        print("No companies selected.")
        return 1
    now = datetime.now(timezone.utc)
    store = Store(DATA_DIR / "jobfinder.sqlite")
    cache = DetailCache(store.load_details())
    ctx = FetchContext(lambda t: title_matches(profile, t), profile.workday_queries,
                       max_age_days=profile.max_age_days + 15, cache=cache)

    print(f"Checking {len(companies)} employers...", flush=True)
    progress(0, len(companies), 0, "Checking employers...")
    jobs: list[Job] = []
    errors: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(fetch_company, c, ctx): c for c in companies}
        for fut in as_completed(futs):
            c = futs[fut]
            done += 1
            try:
                got = fut.result()
                jobs.extend(got)
            except Exception as e:  # one broken board must never kill the run
                errors[c.name] = str(e)[:160]
            progress(done, len(companies), len(jobs), f"Checked {c.name}")
            if done % 10 == 0 or done == len(companies):
                print(f"  {done}/{len(companies)} employers, {len(jobs)} postings", flush=True)
    fetched = len(jobs)
    store.save_details(cache.fresh)

    # de-dupe (same posting can surface under two Workday queries or sites)
    uniq: dict[str, Job] = {}
    for j in jobs:
        uniq.setdefault(j.uid, j)
    jobs = list(uniq.values())

    progress(len(companies), len(companies), len(jobs), "Scoring jobs...")
    last = store.last_run()
    candidates = [j for j in jobs if title_matches(profile, j.title)]
    # company-level context (req-number sequences, boilerplate, suffix norms) from ALL postings
    contexts = build_contexts(jobs, now)
    for j in candidates:
        cc = contexts.get(j.company)
        if cc is None:
            continue
        est = cc.req_age_estimate(j)
        if est is not None:
            j.extra["req_age_estimate"] = est
        created = cc.created_at(j)
        if created:
            j.extra["req_age_created"] = (now - created).total_seconds() / 86400
    store.annotate(candidates, now)
    if last is None:  # first run: everything is "new", which is noise
        for j in candidates:
            j.is_new = False
    ticker_of = {c.name: c.ticker for c in companies if c.ticker}
    restructuring = restructuring_days(set(ticker_of.values()), profile.sec_contact, store.db)
    frozen = store.freezes()
    for j in candidates:
        if ticker_of.get(j.company) in restructuring:
            j.extra["restructuring_days"] = restructuring[ticker_of[j.company]]
        if j.company in frozen:
            j.extra["freeze"] = True
        score_job(j, profile, now, contexts.get(j.company))
    marks = store.marks()
    shown = [j for j in candidates if j.bucket != "filtered"
             and marks.get(j.uid) not in ("applied", "hidden")
             and not ((days_old(j, now) or 0) > profile.max_age_days and j.bucket != "likely ghost")]
    shown.sort(key=lambda j: (-j.is_new, -j.score) if args.new_first else (-j.score,))
    kept = [j for j in candidates if j.bucket != "filtered"]
    store.record_reqs(kept, now)
    store.record_counts(ctx.totals, errors, now)
    store.save(kept, now, len(companies), errors)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stats = {"name": profile.name, "companies": len(companies), "fetched": fetched,
             "matched": len(shown), "new": sum(j.is_new for j in shown), "errors": errors}
    html_path = REPORTS_DIR / "latest.html"
    write_html(shown, html_path, now, stats)
    write_csv(shown, REPORTS_DIR / "latest.csv", now)
    stamp = now.astimezone().strftime("%Y-%m-%d")
    write_csv(shown, REPORTS_DIR / f"jobs-{stamp}.csv", now)

    print_summary(shown, now)
    if errors:
        print(f"  {len(errors)} feeds failed (see report header). `python -m jobfinder check` to diagnose.")
    print(f"  Report: {html_path}")
    if not args.no_open:
        webbrowser.open(html_path.resolve().as_uri())
    return 0


def _mark(args, status: str) -> int:
    store = Store(DATA_DIR / "jobfinder.sqlite")
    rows = store.mark(args.id, status, " ".join(args.note or []))
    if not rows:
        print(f"No job found with id {args.id!r}. Use the 6-character id shown in the report.")
        return 1
    for uid, company, title in rows:
        print(f"Marked {status}: {company} - {title}")
    return 0


def cmd_tracker(args) -> int:
    rows = Store(DATA_DIR / "jobfinder.sqlite").applied()
    if not rows:
        print("Nothing marked applied yet.")
        return 0
    for at, company, title, loc, url, note in rows:
        print(f"{at[:10]}  {company[:24]:24}  {title[:50]:50}  {note or ''}")
        print(f"{'':12}{url}")
    print(f"\n{len(rows)} applications tracked. Follow up on anything older than 7 days without a reply.")
    return 0


def _slug_guesses(name: str) -> list[str]:
    base = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    joined = "".join(base)
    return list(dict.fromkeys([joined, "-".join(base), base[0] if base else joined, joined + "inc"]))


def cmd_add(args) -> int:
    target = args.target
    companies = load_companies()
    hits: list[tuple[str, tuple]] = []
    if target.startswith("http"):
        hits = detect_from_text(target)
        if not hits:
            try:
                hits = detect_from_text(get_text(target))
            except Exception as e:
                print(f"Couldn't load {target}: {e}")
    name = args.name or (target if not target.startswith("http") else "")
    if not hits and name:
        for ats in ("greenhouse", "lever", "ashby", "smartrecruiters"):
            for slug in _slug_guesses(name):
                n = probe_slug(ats, slug)
                if n > 0:
                    hits.append((ats, (slug,)))
                    print(f"  found {ats}/{slug} with {n} postings")
                    break
    if not hits:
        print("Couldn't detect a supported job board. Open the company's careers page, click into a job, and\n"
              "pass that URL:  python -m jobfinder add <job-url> --name \"Company\"")
        return 1
    ats, g = hits[0]
    if ats == "workday":
        tenant, wd, site = g
        c = Company(name=name or tenant, ats="workday", slug=tenant, host=f"{tenant}.{wd}.myworkdayjobs.com",
                    site=site, segment=args.segment)
    else:
        c = Company(name=name or g[0], ats=ats, slug=g[0], segment=args.segment)
    if any(x.key == c.key for x in companies):
        print(f"Already tracking {c.name} ({c.key}).")
        return 0
    try:
        profile = load_profile()
        n = len(fetch_company(c, FetchContext(lambda t: title_matches(profile, t), ["engineer"], 40)))
    except Exception as e:
        print(f"Detected {c.key} but fetching failed: {e}")
        return 1
    add_company(c)
    print(f"Added {c.name} via {c.ats} ({n} postings visible).")
    return 0


def cmd_check(args) -> int:
    profile = load_profile()
    companies = load_companies()
    ctx = FetchContext(lambda t: False, profile.workday_queries[:1], 20)
    bad = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(fetch_company, c, ctx): c for c in companies}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                n = len(fut.result())
                status = "ok" if n else "EMPTY"
            except Exception as e:
                n, status = 0, f"FAIL {str(e)[:80]}"
            if status.startswith("FAIL"):
                bad.append(c)
            print(f"{status:6.6}  {n:5}  {c.name}  ({c.key})")
    print(f"\n{len(companies) - len(bad)}/{len(companies)} feeds healthy.")
    if bad and args.prune:
        keep = [c for c in companies if c not in bad]
        save_companies(keep)
        print(f"Removed {len(bad)} broken feeds from config/companies.csv")
    return 0


def main(argv: list[str] | None = None) -> int:
    _console_utf8()
    p = argparse.ArgumentParser(prog="jobfinder", description="Find fresh, real, well-matched job postings.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="fetch, score and open today's report (default)")
    r.add_argument("--segment", nargs="*", help="only these segments (see companies.csv)")
    r.add_argument("--company", help="only companies whose name contains this")
    r.add_argument("--workers", type=int, default=12)
    r.add_argument("--no-open", action="store_true", help="don't open the report in a browser")
    r.add_argument("--new-first", action="store_true", help="sort jobs new since last run to the top")

    for name, help_ in (("applied", "mark a job as applied (hides it from future reports)"),
                        ("hide", "hide a job you're not interested in")):
        m = sub.add_parser(name, help=help_)
        m.add_argument("id", help="6-char id from the report, or the job URL")
        m.add_argument("note", nargs="*", help="optional note, e.g. 'referral from Sam'")

    sub.add_parser("tracker", help="list jobs you've marked applied")
    sub.add_parser("gui", help="open the Job Finder app window")

    a = sub.add_parser("add", help="add an employer from a careers/job URL or company name")
    a.add_argument("target", help="careers page / job URL, or company name to guess")
    a.add_argument("--name", help="display name")
    a.add_argument("--segment", default="custom")

    c = sub.add_parser("check", help="health-check every employer feed")
    c.add_argument("--workers", type=int, default=12)
    c.add_argument("--prune", action="store_true", help="remove feeds that fail")

    args = p.parse_args(argv)
    if args.cmd is None:
        args = p.parse_args(["run", *(argv or sys.argv[1:])])
    if args.cmd == "gui":
        from .gui import main as gui_main
        return gui_main([])
    return {"run": cmd_run, "applied": lambda a: _mark(a, "applied"), "hide": lambda a: _mark(a, "hidden"),
            "tracker": cmd_tracker, "add": cmd_add, "check": cmd_check}[args.cmd](args)
