"""已核实补充不依赖搜索结果，并保持精确主机与集合边界。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from convert import prepare, write_changed
from discover import OWNERSHIP, approved_candidate, discover
from merge import read_local


EXPECTED = {
    "OpenAI": {"domain-suffix,oaistatsig.com"},
    "Notion": {"domain-suffix,notionusercontent.com"},
    "Docker": {"domain,dhi.io"},
    "Teams": {"domain-suffix,teams.cloud.microsoft"},
    "GitHub": {"domain-suffix,ghe.com"},
    "Figma": {"domain-suffix,figma.site"},
    "Copilot": {"domain,copilot.com", "domain,copilot.cloud.microsoft"},
    "Gemini": {"domain,cloudaicompanion.googleapis.com"},
}


class VerifiedDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / "upstream"
        self.root = Path(temporary.name) / "output"
        self.upstream = self.source / "rule/Clash"
        self.upstream.mkdir(parents=True)
        (self.source / "LICENSE").write_text("fixture license\n")
        for name in EXPECTED:
            folder = self.upstream / name
            folder.mkdir()
            (folder / f"{name}.list").write_text("DOMAIN,legacy.example\n")
            (folder / f"{name}.yaml").write_text("payload:\n  - DOMAIN,existing.example\n")
        self.timestamp = "2026-11-04 16:09 UTC"

    def test_verified_rules_are_available_without_search(self):
        search = Mock(side_effect=AssertionError("unexpected network"))
        additions, report = discover(self.source, self.root, self.timestamp, limit=0, search=search)
        search.assert_not_called()
        self.assertEqual(report["attempted"], 0)
        self.assertEqual(len(additions), len(EXPECTED))
        for name, rules in EXPECTED.items():
            key = f"{name}/{name}.yaml"
            self.assertEqual(additions[key], rules)
            self.assertEqual(set(report["verified_additions"][key]["rules"]), rules)
            self.assertTrue(report["verified_additions"][key]["evidence"])
            self.assertNotIn(f"{name}/{name}.list", additions)

    def test_failed_search_keeps_verified_rules(self):
        def failed_search(_):
            raise OSError("offline")

        with patch("discover.time.sleep"):
            additions, report = discover(self.source, self.root, self.timestamp,
                                         search=failed_search)
        self.assertEqual(report["attempted"], len(EXPECTED))
        self.assertTrue(all(item["status"] == "search_failed"
                            for item in report["collections"].values()))
        for name, rules in EXPECTED.items():
            self.assertEqual(additions[f"{name}/{name}.yaml"], rules)

    def test_exact_hosts_never_expand_to_suffixes(self):
        for name, hostname in (("Docker", "dhi.io"), ("Copilot", "copilot.com"),
                               ("Copilot", "copilot.cloud.microsoft"),
                               ("Gemini", "cloudaicompanion.googleapis.com")):
            with self.subTest(name=name, hostname=hostname):
                self.assertTrue(approved_candidate(name, hostname.upper() + "."))
                self.assertFalse(approved_candidate(name, "unverified." + hostname))
                self.assertFalse(approved_candidate(name, hostname, "domain-suffix"))
        self.assertTrue(approved_candidate("Claude", "cdn.usefathom.com"))
        self.assertFalse(approved_candidate("Claude", "cdn.usefathom.com", "domain-suffix"))

    def test_roots_keep_dns_label_boundaries(self):
        for name, hostname in (("OpenAI", "oaistatsig.com"), ("Notion", "notionusercontent.com"),
                               ("Teams", "teams.cloud.microsoft"), ("GitHub", "ghe.com"),
                               ("Figma", "figma.site")):
            with self.subTest(name=name):
                self.assertTrue(approved_candidate(name, "service." + hostname))
                self.assertTrue(approved_candidate(name, hostname, "domain-suffix"))
                self.assertFalse(approved_candidate(name, "not-" + hostname))
                self.assertFalse(approved_candidate(name, hostname + ".example"))
        self.assertFalse(approved_candidate("Gemini", "oauth2.googleapis.com"))
        self.assertFalse(approved_candidate("Teams", "outlook.cloud.microsoft"))
        self.assertFalse(approved_candidate("Figma", "cdn.jsdelivr.net"))

    def test_invalid_verified_suffix_fails_closed(self):
        invalid = {"roots": [], "hosts": ["dhi.io"], "telemetry": [],
                   "verified_rules": ["domain-suffix,dhi.io"], "evidence": ["https://docs.docker.com/"]}
        with patch.dict(OWNERSHIP, {"Docker": invalid}):
            with self.assertRaises(ValueError):
                discover(self.source, self.root, self.timestamp, limit=0)

    def test_repeated_merge_is_deduplicated_and_keeps_collection_scope(self):
        additions, _ = discover(self.source, self.root, self.timestamp, limit=0)
        history = "@@2026-11-01T00:00:00Z\n" + "\n".join(
            path.relative_to(self.source).as_posix() for path in sorted(self.upstream.rglob("*"))
            if path.is_file())
        with patch("convert.subprocess.check_output", side_effect=[history, "revision\n"]):
            planned, _ = prepare(self.source, self.root, self.timestamp, additions)
        for path, body in planned.items():
            write_changed(path, body)
        for name, rules in EXPECTED.items():
            path = self.root / f"rules/{name}/{name}.yaml"
            actual = read_local(path)
            self.assertEqual(set(actual), rules | {"domain,existing.example"})
            self.assertEqual(len(actual), len(rules) + 1)
        with patch("convert.subprocess.check_output", side_effect=[history, "revision\n"]):
            again, report = prepare(self.source, self.root, self.timestamp, additions)
        self.assertFalse(any(path.suffix == ".yaml" for path in again))
        for name, rules in EXPECTED.items():
            self.assertEqual(report[f"rule/Clash/{name}/{name}.yaml"]["rules"], len(rules) + 1)


if __name__ == "__main__":
    unittest.main()
