# How the ghost-job detection works, and how much to trust it

These signals come from a research pass (Sep 2026) that covered published studies, the fields each
applicant-tracking system (ATS) exposes, and tests on about 30,000 live postings. **Every signal was then
reviewed by a second agent trying to refute it.** Signals that didn't survive were dropped or down-weighted.
Ghost-risk points below sit on a 0–100 scale; **40 or more puts a posting in "Likely ghost"**.

## The honest limit

Nobody outside the company can *prove* a posting is fake. No free data source records hires. The best available
approach is to catch (1) postings that say or record that no specific opening exists, (2) old requisitions dressed
up as new, and (3) patterns that build up over daily runs. The weights rank postings; they are not calibrated
probabilities.

## Strong signals (the posting or the ATS itself says there is no single open seat)

| Signal | Points | Evidence |
|---|---|---|
| Pipeline title ("Future Opportunity", "Talent Community", "General Interest", "(Pipeline)") | +45 | ~90% precision on 6,352 live titles. Technical uses ("data pipeline", "Pipeline Engineer") are excluded |
| Greenhouse **prospect post** (`internal_job_id` is null) | +40 | Documented by Greenhouse; 14/14 were talent pools |
| Job-specific evergreen text ("not currently linked to an open position", "build a pipeline of candidates"…) | +35 (+10 for cohort programs) | 5/5 true hits once company boilerplate is removed. Bare "talent pipeline" was **dropped** because it flagged Regeneron's real entry-level cohort |
| NY ghost-job-law wording "THIS POSTING IS NOT FOR A CURRENT VACANCY" | +60 | Exact statutory text (S8877, passed and awaiting signature). A fill-by date gives −15; a fill-by date that has passed gives +15 |
| Ontario "not an existing vacancy" (without "new position") | +25 | Required text since Jan 2026 |
| SmartRecruiters `Req Type` = Sourcing/Pipeline | +30 (+10 for intern/new-grad) | Intuitive: 86 pipeline reqs, 0 with funded headcount IDs |
| Phenom `isEverGreenReq` / evergreen requisition type; all openings filled | +30 | ATS field |
| PERM labor-certification ad (earmarked for a sponsored worker) | +40 | 20 CFR 656.17 |
| SmartRecruiters "Internal Only" | hidden | Not open to outside applicants |

## Requisition age: catching reposts that look brand new

Workday and SmartRecruiters **reset the posted date when an old requisition is re-posted**. The tool estimates the
requisition's true age three ways and uses the oldest:

1. **Its own history.** The first day it saw this requisition ID (improves every day it runs).
2. **ATS creation timestamps.** Phenom `dateCreated` and Eightfold `creationTs`, ignoring bulk-migration stamps.
3. **Requisition-number sequence.** Req numbers are issued roughly in order. From the postings with exact dates,
   the tool fits how many reqs a company opens per day (Medtronic about 80, Thermo Fisher about 170), then dates any req number.
   - Checked against Boston Scientific's real creation dates: **23 correct flags, 0 false alarms, 3 misses**, median error about 4 days.
   - On a big employer's "fresh" postings it flags 6–20%, in line with independent measurements (7–18%).
   - If a company's data is too sparse to fit reliably, it makes no estimate.

| Requisition age | Points |
|---|---|
| 61–90 days | +6 |
| 91–120 days | +10 |
| 121–180 days | +15 |
| over 180 days | +22 |

If the requisition is 60+ days old but the posting looks new, the freshness bonus is **capped at +5**, the job
can't be in "Apply today", and it shows the flag *reposted old req (~N d)*.

Why the thresholds start at 60 days: engineering roles at large employers are commonly open 40–60 days (JOLTS
microdata: about 38 days mean vacancy duration at establishments with 1,000+ employees). A requisition at 60–90 days is normal, and past about 120 days it's
more likely stale than live. Reposting an old requisition also often means a real but **hard-to-fill** job
(Chéron & Decreuse 2017), which is why these weights are moderate.

## History-based signals (improve with daily runs)

- **Re-listed after disappearing:** same requisition or role+city back under a new ID after 7+ days gone. +10, or +15 if it happened twice or more.
- **Hiring freeze:** the employer's total open postings sit at ≤60% of its 4-week median for 3 straight runs. Activates after 4 weeks of history. +5.

## Weak signals (small weights)

- Workday re-posting suffix **above that employer's norm**: +6 per step, max +12. `-1` is the default at Medtronic and BD (70%+), so it is never penalized by itself. The old rule was a false-positive generator.
- Application deadline in the text: passed and still posted +15; closing within 45 days −4. Workday's `endDate` is ignored: it's an automatic expiry, and Workday removes expired postings itself.
- No pay range in a pay-transparency state: +5.
- Description under 700 characters: +5.
- Same posting in 10 or more locations (not field or sales roles): +3.
- SEC 8-K Item 2.05 restructuring filing: +5 within 180 days, +2 within a year. Off unless `[sec] contact_email` is set in `config/profile.toml`, because SEC requires a contact email in requests.

## Tested and rejected

| Idea | Why it was rejected |
|---|---|
| State WARN layoff notices | Name matching was too noisy: "Abbott" matched a social-services agency, and 22% of postings got flagged. Georgia isn't in the free dataset. A 50-person plant layoff says little about an R&D req elsewhere. |
| Near-duplicate descriptions | They are more common among *real* jobs (territory and shift clones) than pipeline posts. |
| Company posting volume | No measured link to ghost jobs. |
| Workday `canApply` / `endDate` in the past, Oracle openings and hiring-manager fields | Always constant or empty in live data. |
| "Hires per posting" industry priors (JOLTS) | Nearly every employer here is in the same industry, so it doesn't change the ranking. |

## What to watch

After about 8 weeks of daily runs, check whether flagged postings disappear without being filled or keep getting
re-posted more often than unflagged ones, and re-tune the weights in `jobfinder/scoring.py`.
