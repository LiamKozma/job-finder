# Playbook: from applications to interviews

This is research-backed advice for an entry-level medical device / biotech engineer (MS BME) in 2026.
The tool finds the right postings. This covers what to do with them.

## 1. What's actually going on

- **Ghost jobs are real and common.** 18–22% of postings on Greenhouse look like ghost jobs
  ([Greenhouse 2024](https://www.greenhouse.com/blog/greenhouse-2024-state-of-job-hunting-report)).
  About 1 in 3 US listings leads to no hire
  ([MyPerfectResume via HR Dive](https://www.hrdive.com/news/us-job-listings-go-nowhere-creating-a-ghost-job-economy/805448/)).
  40% of hiring managers admit posting fake jobs
  ([ResumeBuilder](https://www.resumebuilder.com/3-in-10-companies-currently-have-fake-job-posting-listed/)).
  Hires per posting fell from about 8 in 10 in 2020 to fewer than 4 in 10 in 2024
  ([CRS](https://www.congress.gov/crs-product/IF12977)).
- **The 1 AM rejection is a machine, not a person.** It comes from knockout questions (years of experience,
  sponsorship, relocation, degree) or from a batch job that sends rejections overnight. It also happens when a
  req closes or is filled internally, which rejects everyone still in the pile at once. Nobody read the resume.
- **So the fix isn't a better cover letter.** It's three things:
  1. apply to real, fresh postings,
  2. pass the knockouts, and
  3. reach a human some other way.

## 2. Pay reality check (from this tool's own data, Sep 25, 2026)

Across **341 live postings** open to 0–2 years of experience that list a pay range:

| | |
|---|---|
| Median bottom of range | **$75,000** |
| Median midpoint | **$92,000** |
| 10th percentile, bottom of range | $55,000 |
| New York median midpoint | $87,500 |

A **$20/hr, 2-year contract ≈ $41,600/yr with no benefits**. That is below the 10th percentile of
what employers are publicly posting for this exact profile. Don't anchor on it. If you take a contract
as a bridge, $32–45/hr W-2 is the normal range for validation, quality or CAPA contract work.

## 3. Daily routine (15–30 min)

1. **Run the tool in the morning.** Work through **Apply today** first, and tick **new only** after the first day.
2. **Apply to ≤72-hour-old postings the same day.** Most teams start reviewing within 24–72h, and popular
   roles get 100–250+ applications in the first 48h.
3. **Pick 2–3 top matches a day for outreach.** Find the hiring manager (search "R&D Manager" or "Quality
   Engineering Manager" + company + site city) or a Georgia Tech / UGA alum on the team. Send three lines:
   > Hi ___, I just applied to the Design Quality Engineer role (R12345) in Irvine. I did ISO 14971/CAPA
   > and DHF work at a cardiac device startup and an MS in BME at Georgia Tech. Would you be open to a
   > 10-min chat, or could you point me to the right person?

   Referred candidates pass the first screen about 52% of the time vs 35% otherwise, and are hired about 4× as often
   ([Jobvite](https://www.jobvite.com/blog/4-reasons-to-invest-in-employee-referrals/)).
4. **Mark it applied** (`py -m jobfinder applied <id> "note"`), and follow up after 7 days.

## 4. Beating the knockouts

- **Years of experience.** Many "Engineer II" roles say "BS + 2 yrs **or MS + 0 yrs**". The tool reads that
  and shows "~0 yrs exp". Answer the knockout honestly. Where the form allows it, count the CardioREST
  internship plus 1.5 years of graduate research as relevant experience.
- **Location.** For an onsite role in another state, write "Relocating to <city>; no relocation assistance
  needed" in the application, if that's true. Atlanta addresses applied to Minnesota onsite roles get filtered.
- **Mirror the exact terms.** Use the posting's own wording: "ISO 13485", "21 CFR 820 / QMSR", "design
  controls", "IQ/OQ/PQ", "CAPA", "DHF". The report's "Why this score" lists which of your skills matched.
- **Format.** Use a single-column resume with no tables, text boxes or graphics, saved as .docx or a text-based PDF.
- **Keep one tailored resume per track**: (a) R&D/design, (b) quality/regulatory, (c) process/manufacturing/bioprocess.

## 5. Channels ranked by hit rate for this profile

1. **Referral / hiring-manager outreach** on fresh postings.
2. **Direct ATS applications within 72h.** This is what the tool is for.
3. **Early-career / rotational programs.** Apply September–November: Medtronic, Boston Scientific, Stryker, J&J,
   Edwards, BD, Abbott, and similar.
4. **Contract-to-hire through medtech staffing firms.** These are real jobs that fill fast. Try Actalent, Kelly
   Scientific/SET, Planet Pharma, Aerotek, Yoh, ICONMA and QCS Staffing. Send their medtech recruiters a
   one-page skills summary. **Negotiate the rate.**
5. **Contract manufacturers / CDMOs** (Integer, Viant, Jabil, Resonetics, Lonza, Catalent, and others). They hire far
   more entry-level manufacturing, quality and validation engineers than the big brands do.
6. Big job boards (LinkedIn Easy Apply, Indeed): lowest yield. Use them only for discovery.

## 6. Track and adjust

After about 50 applications, check `py -m jobfinder tracker`. If there are no callbacks at all,
the resume isn't passing screens, so get it reviewed. If there are callbacks but no offers, practice interviewing.
You can tune `config/profile.toml` too: raise `min_salary`, add or remove title patterns, and set
`preferred_states`.
