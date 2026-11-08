"""The published numbers are exactly what the offline reproduction computes."""

import contextlib
import io
import json
import os
import tempfile
import unittest

from vaultcheck import readme
from vaultcheck.reproduce import reproduce

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Published(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        with contextlib.redirect_stdout(io.StringIO()):
            cls.code = reproduce(os.path.join(ROOT, "data"), cls.out)
        with open(os.path.join(cls.out, "report.json")) as f:
            cls.report = json.load(f)
        with open(os.path.join(ROOT, "data", "registry.json")) as f:
            cls.registry = json.load(f)
        with open(os.path.join(ROOT, "README.md")) as f:
            cls.readme = f.read()

    def test_data_integrity(self):
        self.assertTrue(self.report["manifest_ok"], self.report["manifest_problems"])
        self.assertEqual(self.code, 0)

    def test_readme_results_match_reproduction(self):
        self.assertEqual(readme.section(self.readme, readme.RESULTS), readme.render_results(self.report),
                         "README results are stale: run `make reproduce && python3 -m vaultcheck readme`")

    def test_readme_registry_matches_data(self):
        self.assertEqual(readme.section(self.readme, readme.REGISTRY), readme.render_registry(self.report, self.registry))

    def test_korean_readme_matches_reproduction(self):
        with open(os.path.join(ROOT, "README.ko.md")) as f:
            ko = f.read()
        self.assertEqual(readme.section(ko, readme.SUMMARY_KO), readme.render_summary_ko(self.report))
        self.assertEqual(readme.section(ko, readme.RESULTS), readme.render_results(self.report))
        self.assertEqual(readme.section(ko, readme.REGISTRY), readme.render_registry(self.report, self.registry))

    def test_incident_matches_post_mortem(self):
        inc = self.report["incident"]
        first = inc["crossings"][0]
        # post-mortem: attacker withdrawals 29 Sep 16:14 UTC
        self.assertTrue(first["time_utc"].startswith("2026-09-29 16:14"), first)
        # post-mortem: $3.8M
        self.assertGreater(inc["peak"]["gap_usd"], 3_700_000)
        self.assertLess(inc["peak"]["gap_usd"], 3_900_000)
        # post-mortem: paused 08:33, unpaused 11:20 (on-chain flag within 2 minutes)
        for f in self.report["pause_flips"]:
            self.assertLessEqual(abs(f["minutes_from_postmortem"]), 2.0, f)

    def test_alarm_fires_before_identification(self):
        c1k = next(c for c in self.report["incident"]["crossings"] if c["threshold_usd"] == 1000)
        self.assertGreater(c1k["hours_before_identified"], 24)

    def test_demo_replays_the_reproduced_numbers(self):
        with open(os.path.join(self.out, "demo.html")) as f:
            page = f.read()
        c1k = next(c for c in self.report["incident"]["crossings"] if c["threshold_usd"] == 1000)
        self.assertIn(f'"head_start_h":{c1k["hours_before_identified"]}', page)
        self.assertIn(f'"alarm":"{c1k["time_utc"]}"', page)
        self.assertNotIn("<script src", page)

    def test_pages_copies_are_current(self):
        for src, dst in (("demo.html", "index.html"), ("report.html", "report.html")):
            with open(os.path.join(self.out, src)) as f, open(os.path.join(ROOT, "docs", dst)) as g:
                self.assertEqual(f.read(), g.read(), f"docs/{dst} is stale: run `make pages`")

    def test_only_the_incident_token_alarms_in_the_window(self):
        token = self.report["incident"]["token"]
        for s in self.report["scans"]:
            for a in s["alarms"]:
                self.assertEqual(a["token"], token, (s["block"], a))


if __name__ == "__main__":
    unittest.main()
