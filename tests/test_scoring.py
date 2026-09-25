import unittest
from datetime import datetime, timedelta, timezone

from jobfinder.config import load_profile
from jobfinder.models import Job
from jobfinder.scoring import is_us, parse_salary, score_job, title_matches, years_required

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)
P = load_profile()


def job(title, desc="", loc="Atlanta, GA", days=1, **kw):
    return Job(company="Acme Medical", source="greenhouse", ext_id="1", title=title, location=loc, url="u",
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
        j = score_job(job("Quality Engineer", GOOD_DESC + " Join our talent pipeline for future opportunities.",
                          days=70), P, NOW)
        self.assertEqual(j.bucket, "likely ghost", j.reasons)

    def test_senior_requirement_sinks(self):
        j = score_job(job("Process Engineer", GOOD_DESC.replace("Master's degree with 0 years", "")
                          .replace("2+ years", "8+ years"), days=1), P, NOW)
        self.assertNotEqual(j.bucket, "apply now", j.reasons)

    def test_lowball_flagged(self):
        j = score_job(job("Quality Engineer", "Medical device QE, ISO 13485. 12 month contract. $20/hr " * 20,
                          loc="New York, NY"), P, NOW)
        self.assertTrue(any("low pay" in f for f in j.flags), j.flags)
        self.assertIn("contract/temp", j.flags)

    def test_repost_raises_ghost_risk(self):
        j = job("Quality Engineer", GOOD_DESC)
        j.repost_count = 2
        self.assertGreaterEqual(score_job(j, P, NOW).ghost_risk, 30)


if __name__ == "__main__":
    unittest.main()
