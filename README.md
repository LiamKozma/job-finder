# Job Finder

**➡️ [Download for Windows](https://github.com/LiamKozma/job-finder/releases/latest/download/JobFinder.exe)** · [How to use it](#get-started-on-windows-no-technical-skills-needed) · [How to turn applications into interviews](STRATEGY.md)

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

## Get started on Windows (no technical skills needed)

1. **[Download JobFinder.exe](https://github.com/LiamKozma/job-finder/releases/latest/download/JobFinder.exe)**. Save it
   somewhere easy, like your Desktop.
2. **Double-click it.** Windows may show a blue box saying *"Windows protected your PC"*. That appears because the
   app isn't from the Microsoft Store. Click **More info**, then **Run anyway**. You only need to do this once.
3. In the window that opens, fill in **Your preferences** (lowest salary, preferred states, visa or clearance
   situation) and click **Save preferences**.
4. Click **Find jobs now**. It takes about 3 minutes. Your results open in your web browser when it's done.
5. Tick **"Search for me automatically every day at 8:00"** and it runs every morning by itself.
   If the laptop is asleep at 8, it runs as soon as it wakes up.

That's it. Nothing else to install. To update, download the .exe again. Your settings and history are kept.

<details><summary>Using it with Python instead (Mac/Linux, or developers)</summary>

Install Python 3.11+, download this repo, then double-click `JobFinder.pyw`, or run `python3 -m jobfinder gui` for the
window or `python3 -m jobfinder` for the command line. `./run.sh` / `run.bat` also work.
</details>

## Why this exists

Applying through big job boards means competing with hundreds of applicants, often for listings that
were never going to be filled. This tool does the opposite:

| Problem | What the tool does |
|---|---|
| **Ghost jobs** (pipeline postings, reposted old roles, "talent community" listings) | Catches postings that say, or whose ATS records, that there's no single open seat: pipeline titles, Greenhouse prospect posts, evergreen/pipeline requisition fields, NY/Ontario vacancy-disclosure wording. It spots **old requisitions re-posted with a fresh date**, estimated from each company's requisition-number sequence (0 false alarms against Boston Scientific's real creation dates), and tracks re-listings and hiring freezes across daily runs. Details and evidence: [docs/GHOST_JOBS.md](docs/GHOST_JOBS.md). |
| **Instant auto-rejections** | These are usually knockout filters: years of experience, degree, clearance, location. The tool reads each description and pulls out **how many years they actually require for someone with an MS** (e.g. "BS + 2 yrs **or MS + 0 yrs**"). "5+ years" roles and clearance/PE/PhD requirements get pushed down. |
| **Being applicant #800** | Jobs are pulled straight from the employer's own ATS, usually **hours** after posting. Postings from the last 24–72h get a big boost, because early applicants are far likelier to get a human review. |
| **Lowball offers** (e.g. $20/hr on a 2-year contract ≈ $41.6k/yr) | Parses posted pay ranges and flags anything under your floor (`min_salary`, default $65k). Contract, temp and staffing-agency roles are flagged too. Most US states with big medtech hubs (CA, CO, WA, NY, IL, MN, MA, NJ, MD) legally require a pay range in the posting, so you'll see the pay *before* applying. |

## Daily routine (about 15 minutes)

1. Open your results. They open by themselves if you turned on the daily search, or click **Open last results** in the app.
   Start with **Apply today**. Tick **new only** to see just what appeared since last time.
2. For each good one, click **"Why this score"** to see which of your skills matched. Then open the posting and
   apply the same day, using the posting's own words in your resume.
3. Tick **applied** on the job. It moves to **My applications** at the top of the page, so you can track it and
   follow up after about a week. Tick **hide** for jobs you're not interested in.
4. For your top 2–3 jobs, find the hiring manager or a Georgia Tech / UGA alum on that team on LinkedIn and send a short
   note. See [STRATEGY.md](STRATEGY.md) for a template. A referral or a direct message beats a cold application by a wide margin.

## Command line (optional)

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
- **ghost_risk** (0–100): pipeline title +45, Greenhouse prospect post +40, evergreen text +35, ATS pipeline/evergreen
  requisition +30, requisition 61–180+ days old +6 to +22, re-listed +10/+15, passed deadline +15, and smaller signals.
  An old requisition with a fresh date also caps the freshness bonus. Full table: [docs/GHOST_JOBS.md](docs/GHOST_JOBS.md).

Buckets: **apply now** (score ≥ 70 and ≤ 7 days old), **worth a shot** (≥ 45), **long shot**, and
**likely ghost** (ghost_risk ≥ 40).

**Optional:** set `contact_email` under `[sec]` in `config/profile.toml` to also flag employers that filed an
SEC restructuring notice in the past year. SEC requires a contact email on API requests, so this is off by default.

## Privacy

The app keeps your settings, history and results in `%LOCALAPPDATA%\JobFinder` on your own computer. In a repo
checkout, `data/` (your applied/hidden history) and `reports/` stay on your laptop and are git-ignored, and so are
PDFs, so a resume dropped in the folder won't be committed. The tool only makes read-only
requests to public job-board endpoints.

## Development

```
python -m unittest -v
```
Pure standard library (Python 3.11+). Fetchers live in `jobfinder/sources.py`, scoring in `jobfinder/scoring.py`.
