from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

from .models import Job
from .scoring import days_old
from .store import short_id

BUCKETS = [
    ("apply now", "Apply today", "Fresh, real-looking, and a strong fit. The first 72 hours matter most."),
    ("worth a shot", "Worth a shot", "Decent fit or a little older. Apply if you have time, ideally with a referral."),
    ("long shot", "Long shots", "Stretch on experience, older, or a weaker match."),
    ("likely ghost", "Likely ghost jobs", "Reposted, evergreen, or open for months. Skip unless you have an inside contact."),
]


def _age(j: Job, now: datetime) -> str:
    d = days_old(j, now)
    if d is None:
        return "date unknown"
    if d < 1:
        return "today"
    return f"{d:.0f}d ago"


def _pay(j: Job) -> str:
    lo, hi = j.extra.get("salary_lo"), j.extra.get("salary_hi")
    if not lo:
        return ""
    return f"${lo/1000:.0f}k" + (f"-${hi/1000:.0f}k" if hi else "")


def write_csv(jobs: list[Job], path: Path, now: datetime) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "bucket", "score", "fit", "ghost_risk", "new", "company", "title", "location",
                    "posted", "pay", "years_required", "flags", "url"])
        for j in jobs:
            w.writerow([short_id(j.uid), j.bucket, j.score, j.fit, j.ghost_risk, "yes" if j.is_new else "",
                        j.company, j.title, j.location, _age(j, now), _pay(j),
                        "" if j.years_required is None else j.years_required, "; ".join(j.flags), j.url])


def print_summary(jobs: list[Job], now: datetime, limit: int = 25) -> None:
    top = [j for j in jobs if j.bucket == "apply now"][:limit]
    counts = {b: sum(1 for j in jobs if j.bucket == b) for b, _, _ in BUCKETS}
    print()
    print("  " + " | ".join(f"{label}: {counts[b]}" for b, label, _ in BUCKETS))
    print()
    if not top:
        print("  Nothing hit 'apply now' today. Open the HTML report for 'worth a shot' roles.")
        return
    print(f"  {'id':6}  {'score':>5}  {'age':>8}  {'company':22}  title / location")
    print("  " + "-" * 100)
    for j in top:
        new = "*" if j.is_new else " "
        print(f" {new}{short_id(j.uid):6}  {j.score:5.0f}  {_age(j, now):>8}  {j.company[:22]:22}  {j.title[:55]}")
        print(f"  {'':6}  {'':5}  {'':8}  {'':22}  {j.location[:60]}  {_pay(j)}")
    print()
    print("  * = new since last run.  Mark one: python -m jobfinder applied <id>")


def write_html(jobs: list[Job], path: Path, now: datetime, stats: dict) -> None:
    e = html.escape
    sections = []
    for bucket, label, blurb in BUCKETS:
        items = [j for j in jobs if j.bucket == bucket]
        if not items:
            continue
        cards = []
        for j in items:
            sid = short_id(j.uid)
            flags = "".join(f'<span class="flag">{e(f)}</span>' for f in j.flags)
            chips = []
            if j.is_new:
                chips.append('<span class="chip new">NEW</span>')
            chips.append(f'<span class="chip">{e(_age(j, now))}</span>')
            if _pay(j):
                chips.append(f'<span class="chip pay">{e(_pay(j))}</span>')
            if j.years_required is not None:
                chips.append(f'<span class="chip">~{j.years_required} yrs exp</span>')
            if j.remote:
                chips.append(f'<span class="chip">{e(j.remote)}</span>')
            reasons = "".join(f"<li>{e(r)}</li>" for r in j.reasons)
            search = e(f"{j.company} {j.title} {j.location} {' '.join(j.flags)}".lower())
            cards.append(f"""
<article class="card" data-id="{sid}" data-search="{search}" data-title="{e(j.title)}" data-company="{e(j.company)}" data-url="{e(j.url)}">
  <div class="top">
    <div class="score" title="fit {j.fit} / ghost risk {j.ghost_risk}">{j.score:.0f}</div>
    <div class="main">
      <a class="title" href="{e(j.url)}" target="_blank" rel="noopener">{e(j.title)}</a>
      <div class="co">{e(j.company)} <span class="muted">· {e(j.location[:120] or 'location n/a')}</span></div>
      <div class="chips">{''.join(chips)}{flags}</div>
    </div>
    <div class="acts">
      <label><input type="checkbox" class="applied"> applied</label>
      <label><input type="checkbox" class="hide"> hide</label>
    </div>
  </div>
  <details><summary>Why this score</summary><ul>{reasons}</ul></details>
</article>""")
        is_open = " open" if bucket in ("apply now", "worth a shot") else ""
        sections.append(f"""
<details class="bucket" data-bucket="{e(bucket)}"{is_open}>
  <summary><h2>{e(label)} <span class="count">{len(items)}</span></h2></summary>
  <p class="blurb">{e(blurb)}</p>
  {''.join(cards)}
</details>""")

    err = stats.get("errors") or {}
    err_html = ""
    if err:
        err_html = "<details class='errs'><summary>{} company feeds failed</summary><ul>{}</ul></details>".format(
            len(err), "".join(f"<li>{e(k)}: {e(v)}</li>" for k, v in sorted(err.items())))
    local = now.astimezone().strftime("%a %b %d, %Y %I:%M %p")
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Finder</title>
<style>
:root {{ --bg:#f7f7f5; --card:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e4e0; --accent:#0b6e4f;
        --chip:#eef0ec; --new:#d9480f; --flag:#fff1e6; --flagink:#a4410b; --pay:#e6f4ea; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141416; --card:#1d1d20; --ink:#ececef; --muted:#9a9aa2;
        --line:#2e2e33; --accent:#4cc38a; --chip:#2a2a2f; --flag:#3a2515; --flagink:#ffb27a; --pay:#1d3326; }} }}
* {{ box-sizing:border-box }}
html, body {{ max-width:100% }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif }}
header {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line); padding:14px 16px; z-index:2 }}
header h1 {{ margin:0 0 4px; font-size:20px }}
.muted {{ color:var(--muted) }}
.bar {{ display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-top:8px }}
input[type=search] {{ flex:1; min-width:200px; padding:8px 10px; border:1px solid var(--line); border-radius:8px;
        background:var(--card); color:var(--ink); font-size:15px }}
main {{ max-width:980px; margin:0 auto; padding:8px 16px 60px }}
h2 {{ margin:28px 0 2px; font-size:18px; display:inline }}
details.bucket {{ margin:0; font-size:15px; color:var(--ink) }} details.bucket > summary {{ cursor:pointer; margin-top:24px }} .count {{ color:var(--muted); font-weight:400 }}
.blurb {{ margin:0 0 10px; color:var(--muted) }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:8px 0 }}
.card.is-applied {{ opacity:.55 }} .card.is-hidden {{ display:none }} body.showhidden .card.is-hidden {{ display:block; opacity:.4 }}
.top {{ display:flex; gap:12px; align-items:flex-start }}
.score {{ min-width:44px; height:44px; border-radius:8px; background:var(--accent); color:#fff; font-weight:700;
        display:flex; align-items:center; justify-content:center; font-size:17px }}
.main {{ flex:1 1 0; min-width:0 }}
.title {{ overflow-wrap:anywhere; font-weight:600; color:var(--ink); text-decoration:none; font-size:16px }} .title:hover {{ text-decoration:underline }}
.co {{ margin-top:2px; overflow-wrap:anywhere }}
.chips {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:6px }}
.chip, .flag {{ font-size:12px; padding:2px 8px; border-radius:99px; background:var(--chip) }}
.chip.new {{ background:var(--new); color:#fff; font-weight:700 }} .chip.pay {{ background:var(--pay) }}
.flag {{ background:var(--flag); color:var(--flagink) }}
.acts {{ display:flex; flex-direction:column; gap:2px; font-size:13px; color:var(--muted); white-space:nowrap }}
#applied-list {{ margin:6px 0 0 18px; padding:0 }} #applied-list li {{ margin:3px 0 }} #applied-list a {{ color:var(--ink) }}
details {{ margin-top:6px; font-size:13px; color:var(--muted) }} details ul {{ margin:4px 0 0 18px; padding:0 }}
.errs {{ margin-top:8px }}
@media (max-width:600px) {{ .top {{ flex-wrap:wrap }} .main {{ flex-basis:calc(100% - 60px) }} .bar label {{ font-size:13px }} .acts {{ flex-direction:row; gap:12px; width:100% }} }}
</style></head><body>
<header>
  <h1>Job Finder <span class="muted" style="font-weight:400;font-size:14px">for {e(stats.get('name',''))}</span></h1>
  <div class="muted">{e(local)} · {stats.get('companies',0)} employers checked · {stats.get('fetched',0)} postings scanned ·
    {stats.get('matched',0)} matched · {stats.get('new',0)} new since last run</div>
  <div class="bar">
    <input type="search" id="q" placeholder="Filter: company, title, state, 'remote', 'contract'...">
    <label class="muted"><input type="checkbox" id="onlynew"> new only</label>
    <label class="muted"><input type="checkbox" id="showhidden"> show hidden</label>
  </div>
  {err_html}
</header>
<main>
<details class="bucket" id="applied-box" hidden><summary><h2>My applications <span class="count" id="applied-count"></span></h2></summary>
  <p class="blurb">Everything you've ticked "applied" (saved in this browser). Follow up after about a week if you hear nothing.</p>
  <ul id="applied-list"></ul>
</details>
{''.join(sections) or '<p>No matching jobs right now. Check back tomorrow, or lower your salary floor in the app.</p>'}</main>
<script>
const KEY = "jobfinder-marks";
let marks = {{}};
try {{ marks = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
const save = () => {{ try {{ localStorage.setItem(KEY, JSON.stringify(marks)); }} catch (e) {{}} }};
document.querySelectorAll(".card").forEach(c => {{
  const id = c.dataset.id, m = marks[id] || {{}};
  const a = c.querySelector(".applied"), h = c.querySelector(".hide");
  a.checked = !!m.applied; h.checked = !!m.hide;
  const paint = () => {{ c.classList.toggle("is-applied", a.checked); c.classList.toggle("is-hidden", h.checked); }};
  paint();
  [a, h].forEach(el => el.addEventListener("change", () => {{
    marks[id] = {{ applied: a.checked, hide: h.checked, at: new Date().toISOString(),
                  title: c.dataset.title, company: c.dataset.company, url: c.dataset.url }};
    save(); paint(); renderApplied(); }}));
}});
function renderApplied() {{
  const items = Object.values(marks).filter(m => m.applied && m.title).sort((x, y) => (y.at || "").localeCompare(x.at || ""));
  const box = document.getElementById("applied-box");
  box.hidden = !items.length;
  document.getElementById("applied-count").textContent = items.length;
  const ul = document.getElementById("applied-list");
  ul.textContent = "";
  items.forEach(m => {{
    const li = document.createElement("li"), a = document.createElement("a");
    a.href = m.url; a.target = "_blank"; a.rel = "noopener"; a.textContent = m.title;
    li.append((m.at || "").slice(0, 10) + "  ", a, "  — " + m.company);
    ul.append(li);
  }});
}}
renderApplied();
const q = document.getElementById("q"), onlynew = document.getElementById("onlynew");
function filter() {{
  const terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  document.querySelectorAll(".card").forEach(c => {{
    const ok = terms.every(t => c.dataset.search.includes(t)) && (!onlynew.checked || c.querySelector(".chip.new"));
    c.style.display = ok ? "" : "none";
  }});
}}
q.addEventListener("input", filter); onlynew.addEventListener("change", filter);
document.getElementById("showhidden").addEventListener("change", e => document.body.classList.toggle("showhidden", e.target.checked));
</script></body></html>""", encoding="utf-8")
