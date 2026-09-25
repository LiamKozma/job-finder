# Job Finder

Find engineering jobs that are **fresh, real, and a genuine fit**. Skip the reposted ghost listings
and the postings that auto-reject you at 1:01 AM.

It checks the official public job-board feeds of **231 medical device, biotech, diagnostics and
contract-manufacturing employers**, about 30,000 postings per run. Examples include Medtronic, Boston Scientific,
Stryker, J&J MedTech, Abbott, BD, Edwards, Zimmer Biomet, Dexcom, Insulet, Hologic, Amgen, Regeneron, Lilly,
Moderna, Thermo Fisher, Lonza and Catalent, plus about 50 venture-backed medtech startups and Georgia employers.
It scores every posting against your resume and opens a ranked report in your browser, in about 2–3 minutes.
It uses no LinkedIn/Indeed scraping, no API keys, no accounts, and no third-party Python packages.

![buckets](https://img.shields.io/badge/buckets-apply%20now%20·%20worth%20a%20shot%20·%20long%20shot%20·%20likely%20ghost-0b6e4f)

**New to this? Read [STRATEGY.md](STRATEGY.md).** It covers what's behind ghost jobs and 1 AM rejections, real pay
data for entry-level roles, and a daily routine that turns postings into interviews.

## Why this exists

Applying through big job boards means competing with hundreds of applicants, often for listings that
were never going to be filled. This tool does the opposite:

| Problem | What the tool does |
|---|---|
| **Ghost jobs** (reposted roles, "talent pipeline" listings, reqs open for months) | Remembers every posting across daily runs. It catches **reposts** (same role and city, new ID; Workday's `-1/-2` re-opened reqs), **evergreen language**, **age > 35/60 days**, thin descriptions, and postings blasted to dozens of locations. It raises a `ghost_risk` score and sends these to the "Likely ghost" bin. |
| **Instant auto-rejections** | These are usually knockout filters: years of experience, degree, clearance, location. The tool reads each description and pulls out **how many years they actually require for someone with an MS** (e.g. "BS + 2 yrs **or MS + 0 yrs**"). "5+ years" roles and clearance/PE/PhD requirements get pushed down. |
| **Being applicant #800** | Jobs are pulled straight from the employer's own ATS, usually **hours** after posting. Postings from the last 24–72h get a big boost, because early applicants are far likelier to get a human review. |
| **Lowball offers** (e.g. $20/hr on a 2-year contract ≈ $41.6k/yr) | Parses posted pay ranges and flags anything under your floor (`min_salary`, default $65k). Contract, temp and staffing-agency roles are flagged too. Most US states with big medtech hubs (CA, CO, WA, NY, IL, MN, MA, NJ, MD) legally require a pay range in the posting, so you'll see the pay *before* applying. |

## Quick start (Windows)

1. Install Python 3.11+ (one time). Open **PowerShell** and run:
   ```powershell
   winget install Python.Python.3.12
   ```
2. Download this repo: **Code → Download ZIP** on GitHub and unzip it (or `git clone` it).
3. Double-click **`run.bat`**. The first run takes a few minutes, and then the report opens in your browser.
4. *(Optional)* To run it automatically every morning at 8 AM, open PowerShell in the repo folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
   # or twice a day:  ... -Times 08:00,13:00      remove:  ... -Remove
   ```
   If the laptop is asleep at 8, the task runs as soon as it wakes up.

**macOS / Linux:** `./run.sh`, and `sh scripts/schedule_mac.sh` for a daily 8 AM run.

## Daily routine (about 15 minutes)

1. Open the report (it opens by itself if scheduled). Start with **Apply today**. Tick **new only** to
   see just what appeared since yesterday.
2. For each good one, check **"Why this score"**, open the posting and apply the same day.
   Mirror the posting's keywords in your resume (the matched skills are listed for you).
3. Tick **applied** in the report, and/or record it so it never shows again:
   ```
   py -m jobfinder applied 3fa9c1 "referral from Sam"
   py -m jobfinder tracker            # everything you've applied to
   py -m jobfinder hide 8b21de        # not interested
   ```
4. For the top 2–3 roles, find the hiring manager or a team engineer on LinkedIn and send a short note.
   A referral or a direct message beats a cold application by a wide margin.

## Commands

```
py -m jobfinder                      # same as "run": fetch, score, open report
py -m jobfinder run --new-first      # new-since-last-run at the top
py -m jobfinder run --segment georgia-local large-medtech
py -m jobfinder run --company stryker
py -m jobfinder add https://careers.somecompany.com/jobs/123 --name "SomeCo"   # auto-detects the ATS
py -m jobfinder add "Company Name"                                               # guesses Greenhouse/Lever/Ashby
py -m jobfinder check [--prune]      # health-check every employer feed
```
(On macOS/Linux use `python3` instead of `py`.)

## Tuning it

Everything lives in two plain-text files:

- **`config/profile.toml`**: target titles, excluded titles (Senior/Staff/Manager/Intern/Software…),
  resume skills, domain words, entry-level phrases, ghost-job phrases, knockouts, pay floor, preferred states,
  and score thresholds. Every pattern is a regex with a comment explaining it.
- **`config/companies.csv`**: the employers to check. Add any company whose careers site runs on a
  supported ATS with `jobfinder add <url>`.

Supported systems: Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Oracle Recruiting
Cloud, Phenom and Eightfold. Companies on iCIMS, Taleo, SuccessFactors or UKG have no public feed, so check those by hand
(for example Teleflex, B. Braun, Novo Nordisk, Takeda, Intuitive).

### How the score works

`score = fit + freshness − ghost_risk`, and each job's report card shows the full breakdown.

- **fit**: title match (+35 core / +20 adjacent), entry-level title (+12), resume skills found in the
  description (+3 each, max 30), domain words (max 10), years required ≤ 2 for an MS (+10) vs. 5+ (−25 or more),
  explicit new-grad language (+12), posted pay (+5) or pay under your floor (−20), contract (−10),
  knockouts (−40), and a small bump for preferred locations/segments.
- **freshness**: ≤1 day +25, ≤3 days +18, ≤7 days +10, >30 days −15.
- **ghost_risk**: evergreen/pipeline language +35, reposted +15 each, open >60 days +20,
  thin description +10, many locations +10, no pay range in a pay-transparency state +5.

Buckets: **apply now** (score ≥ 70 and ≤ 7 days old), **worth a shot** (≥ 45), **long shot**, and
**likely ghost** (ghost_risk ≥ 40).

## Privacy

`data/` (your applied/hidden history) and `reports/` stay on your laptop and are git-ignored, and so are
PDFs, so a resume dropped in the folder won't be committed. The tool only makes read-only
requests to public job-board endpoints.

## Development

```
python -m unittest -v
```
Pure standard library (Python 3.11+). Fetchers live in `jobfinder/sources.py`, scoring in `jobfinder/scoring.py`.
