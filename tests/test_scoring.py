import unittest
from datetime import datetime, timedelta, timezone

from jobfinder.config import load_profile
from jobfinder.models import Job
from jobfinder.scoring import is_us, parse_salary, score_job, title_matches, years_required

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
P = load_profile()


def job(title, desc="", loc="Atlanta, GA", days=1, source="greenhouse", **kw):
    return Job(company="Acme Medical", source=source, ext_id="1", title=title, location=loc, url="u",
               description=desc, posted_at=NOW - timedelta(days=days), **kw)


GOOD_DESC = ("We design Class II medical devices. Requirements: Bachelor's degree with 2+ years of experience "
             "or Master's degree with 0 years of experience. SolidWorks, GD&T, ISO 13485, design controls, "
             "CAPA, DOE, Minitab, test method development. " * 3 + "Pay: $78,000 - $95,000 per year.")


class Titles(unittest.TestCase):
    def test_targets(self):
        for t in ["R&D Engineer I", "Quality Engineer", "Associate Process Development Engineer",
                  "Design Quality Engineer", "Manufacturing Engineer II", "Associate Scientist, Upstream"]:
            self.assertTrue(title_matches(P, t), t)

    def test_excluded(self):
        for t in ["Senior Quality Engineer", "Staff R&D Engineer", "Software Engineer", "Engineering Manager",
                  "R&D Engineering Intern", "Field Service Engineer", "Electrical Engineer I",
                  "Quality Engineer III", "Principal Process Engineer"]:
            self.assertFalse(title_matches(P, t), t)


class Years(unittest.TestCase):
    def test_ms_alternative_wins(self):
        self.assertEqual(years_required("Bachelor's degree with 4+ years of experience or Master's degree "
                                        "with 2+ years of experience")[0], 2)

    def test_bs_only_gets_ms_credit(self):
        self.assertEqual(years_required("Bachelor's degree and 3 years of relevant experience")[0], 1)

    def test_plain(self):
        self.assertEqual(years_required("Requires 5-7 years of experience in medical devices")[0], 5)

    def test_none(self):
        self.assertIsNone(years_required("Founded 25 years ago, we are a great company.")[0])


class Salary(unittest.TestCase):
    def test_hourly(self):
        self.assertEqual(parse_salary("Pay rate: $20/hr")[0], 41600)

    def test_range(self):
        lo, hi, _ = parse_salary("The base pay range is $83,200.00 - $124,800.00")
        self.assertEqual((lo, hi), (83200, 124800))

    def test_k(self):
        self.assertEqual(parse_salary("$110K – $185K")[:2], (110000, 185000))


class Location(unittest.TestCase):
    def test_us(self):
        for loc in ["Atlanta, GA", "Minneapolis, Minnesota, United States of America", "Remote - US", "Irvine, CA"]:
            self.assertTrue(is_us(job("x", loc=loc)), loc)

    def test_foreign(self):
        for loc in ["Galway, County Galway, Ireland", "Kulim, Kedah, Malaysia", "Toronto, Ontario, Canada"]:
            self.assertFalse(is_us(job("x", loc=loc)), loc)


class Scoring(unittest.TestCase):
    def test_fresh_entry_role_is_apply_now(self):
        j = score_job(job("R&D Engineer I", GOOD_DESC, days=1), P, NOW)
        self.assertEqual(j.bucket, "apply now", j.reasons)

    def test_evergreen_is_ghost(self):
        j = score_job(job("Quality Engineer", GOOD_DESC + " This requisition is not currently linked to an open "
                          "position; we will consider you for future openings.", days=70), P, NOW)
        self.assertEqual(j.bucket, "likely ghost", j.reasons)

    def test_bare_talent_pipeline_is_not_ghost(self):
        # Regeneron-style cohort text: real entry-level job, must not be binned as a ghost
        j = score_job(job("Process Development Engineer I", GOOD_DESC + " We are building a strong entry-level "
                          "talent pipeline through our graduate cohort."), P, NOW)
        self.assertLess(j.ghost_risk, 20, j.reasons)

    def test_pipeline_title(self):
        self.assertEqual(score_job(job("Mechanical Engineer, Instruments - Future Opportunity", GOOD_DESC), P, NOW).bucket,
                         "likely ghost")
        self.assertLess(score_job(job("Process Development Engineer I", GOOD_DESC), P, NOW).ghost_risk, 20)

    def test_greenhouse_prospect_post(self):
        j = job("Quality Engineer", GOOD_DESC)
        j.extra["gh_prospect"] = True
        self.assertGreaterEqual(score_job(j, P, NOW).ghost_risk, 40)

    def test_smartrecruiters_posting_type(self):
        pub = job("Quality Engineer", GOOD_DESC, source="smartrecruiters")
        pub.extra["custom"] = {"Posting Type": "Public - Internal & External", "Req Type": "Professional"}
        self.assertEqual(score_job(pub, P, NOW).ghost_risk, 0)
        internal = job("Quality Engineer", GOOD_DESC, source="smartrecruiters")
        internal.extra["custom"] = {"Posting Type": "Internal Only"}
        self.assertEqual(score_job(internal, P, NOW).bucket, "filtered")
        pipe = job("Human Factors Design Engineer", GOOD_DESC, source="smartrecruiters")
        pipe.extra["custom"] = {"Posting Type": "Public - Internal & External", "Req Type": "Sourcing/ Pipeline"}
        self.assertGreaterEqual(score_job(pipe, P, NOW).ghost_risk, 30)

    def test_ny_law_statement(self):
        j = score_job(job("Quality Engineer", GOOD_DESC + " THIS POSTING IS NOT FOR A CURRENT VACANCY BUT THE "
                          "EMPLOYER IS SEEKING RESUMES."), P, NOW)
        self.assertEqual(j.bucket, "likely ghost")

    def test_refreshed_old_requisition_loses_apply_now(self):
        j = job("R&D Engineer I", GOOD_DESC, days=1)
        j.extra["req_age_estimate"] = 150
        j = score_job(j, P, NOW)
        self.assertNotEqual(j.bucket, "apply now", j.reasons)
        self.assertTrue(any("reposted old req" in f for f in j.flags))

    def test_passed_deadline(self):
        j = score_job(job("Quality Engineer", GOOD_DESC + " Apply by September 1, 2026."), P, NOW)
        self.assertTrue(any("has passed" in r for r in j.reasons), j.reasons)

    def test_senior_requirement_sinks(self):
        j = score_job(job("Process Engineer", GOOD_DESC.replace("Master's degree with 0 years", "")
                          .replace("2+ years", "8+ years"), days=1), P, NOW)
        self.assertNotEqual(j.bucket, "apply now", j.reasons)

    def test_lowball_flagged(self):
        j = score_job(job("Quality Engineer", "Medical device QE, ISO 13485. 12 month contract. $20/hr " * 20,
                          loc="New York, NY"), P, NOW)
        self.assertTrue(any("low pay" in f for f in j.flags), j.flags)
        self.assertIn("contract/temp", j.flags)

    def test_relist_raises_ghost_risk(self):
        j = job("Quality Engineer", GOOD_DESC)
        j.extra["relists"] = 2
        self.assertGreaterEqual(score_job(j, P, NOW).ghost_risk, 15)

    def test_workday_suffix_relative_to_tenant(self):
        from jobfinder.staleness import CompanyContext
        ctx = CompanyContext(wd_suffix_baseline=1)
        normal = job("Quality Engineer", GOOD_DESC, source="workday")
        normal.extra["wd_suffix"] = 1
        self.assertEqual(score_job(normal, P, NOW, ctx).ghost_risk, 0, normal.reasons)
        odd = job("Quality Engineer", GOOD_DESC, source="workday")
        odd.extra["wd_suffix"] = 3
        self.assertGreater(score_job(odd, P, NOW, ctx).ghost_risk, 0)


if __name__ == "__main__":
    unittest.main()


class Staleness(unittest.TestCase):
    def test_req_number_estimator(self):
        from jobfinder.staleness import build_contexts
        # 100 reqs/day, typical req posted ~5 days after it is opened
        jobs = []
        for i in range(120):
            age = i % 25
            n = 500000 - int(age * 100) - 500 + (i % 7) * 10
            jobs.append(Job(company="Big", source="workday", ext_id=str(i), title="Engineer", location="MN",
                            url="u", posted_at=NOW - timedelta(days=age), req_id=f"R{n}",
                            extra={"age_exact": True}))
        old = Job(company="Big", source="workday", ext_id="x", title="Engineer", location="MN", url="u",
                  posted_at=NOW - timedelta(days=1), req_id="R485000", extra={"age_exact": True})
        ctx = build_contexts(jobs + [old], NOW)["Big"]
        est = ctx.req_age_estimate(old)
        self.assertIsNotNone(est)
        self.assertTrue(140 <= est <= 160, est)

    def test_boilerplate_removed(self):
        from jobfinder.staleness import build_contexts
        boiler = "We are building a talent pipeline for future needs across our drug pipeline. "
        jobs = [Job(company="C", source="greenhouse", ext_id=str(i), title="Engineer", location="GA", url="u",
                    description=boiler + f"Role {i} designs catheters with solidworks and runs test method work." * 5)
                for i in range(6)]
        ctx = build_contexts(jobs, NOW)["C"]
        self.assertNotIn("talent pipeline", ctx.strip_boilerplate(jobs[0].description))
