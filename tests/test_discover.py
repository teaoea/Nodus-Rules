"""已核实补充不依赖搜索结果，并保持精确主机与集合边界。"""
from pathlib import Path
from collections import Counter
import json
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
    "Figma": {"domain-suffix,figma.site", "domain-suffix,weavy.ai", "domain-suffix,figmaweave.com"},
    "Copilot": {"domain,copilot.com", "domain,copilot.cloud.microsoft"},
    "Gemini": {"domain,cloudaicompanion.googleapis.com", "domain,cloudcode-pa.googleapis.com"},
    "Atlassian": {"domain-suffix,atlassian.net", "domain-suffix,jira.com",
                  "domain-suffix,atl-paas.net", "domain-suffix,ss-inf.net",
                  "domain-suffix,atlassian-dev.net", "domain-suffix,atlassian-3p.com"},
    "Jetbrains": {"domain-suffix,youtrack.cloud", "domain-suffix,myjetbrains.com"},
    "iCloud": {"domain-suffix,apple-dns.net"},
    "AppleID": {"domain,account.apple.com"},
    "GoogleVoice": {"domain,voice.google.com"},
    "Vercel": {"domain,v0.app", "domain,api.v0.dev",
               "domain-suffix,public.blob.vercel-storage.com", "domain-suffix,vercel.run"},
    "Dropbox": {"domain-suffix,dash.ai", "domain-suffix,docsend.com"},
    "GitLab": {"domain-suffix,gitlab.io"},
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
        exact_hosts = [(name, rule.split(",", 1)[1]) for name, rules in EXPECTED.items()
                       for rule in rules if rule.startswith("domain,")]
        for name, hostname in exact_hosts:
            with self.subTest(name=name, hostname=hostname):
                self.assertTrue(approved_candidate(name, hostname.upper() + "."))
                self.assertFalse(approved_candidate(name, "unverified." + hostname))
                self.assertFalse(approved_candidate(name, hostname, "domain-suffix"))
        self.assertTrue(approved_candidate("Claude", "cdn.usefathom.com"))
        self.assertFalse(approved_candidate("Claude", "cdn.usefathom.com", "domain-suffix"))

    def test_roots_keep_dns_label_boundaries(self):
        roots = [(name, rule.split(",", 1)[1]) for name, rules in EXPECTED.items()
                 for rule in rules if rule.startswith("domain-suffix,")]
        for name, hostname in roots:
            with self.subTest(name=name):
                self.assertTrue(approved_candidate(name, "service." + hostname))
                self.assertTrue(approved_candidate(name, hostname, "domain-suffix"))
                self.assertFalse(approved_candidate(name, "not-" + hostname))
                self.assertFalse(approved_candidate(name, hostname + ".example"))
        self.assertFalse(approved_candidate("Gemini", "oauth2.googleapis.com"))
        self.assertFalse(approved_candidate("Teams", "outlook.cloud.microsoft"))
        self.assertFalse(approved_candidate("Figma", "cdn.jsdelivr.net"))
        self.assertFalse(approved_candidate("Vercel", "vercel-storage.com", "domain-suffix"))
        self.assertFalse(approved_candidate("Vercel", "private.blob.vercel-storage.com"))
        self.assertFalse(approved_candidate("Vercel", "v0.dev", "domain-suffix"))
        self.assertFalse(approved_candidate("AppleID", "apple.com", "domain-suffix"))
        self.assertFalse(approved_candidate("GoogleVoice", "google.com", "domain-suffix"))
        self.assertFalse(approved_candidate("Gemini", "googleapis.com", "domain-suffix"))
        self.assertFalse(approved_candidate("GitLab", "github.io"))
        self.assertFalse(approved_candidate("Figma", "weavy.com"))

    def test_verified_rules_do_not_leak_into_other_collections(self):
        for name, rules in EXPECTED.items():
            for rule in rules:
                kind, hostname = rule.split(",", 1)
                for other in EXPECTED:
                    if other != name:
                        with self.subTest(name=name, other=other, rule=rule):
                            self.assertFalse(approved_candidate(other, hostname, kind))

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


class PublishedVerifiedRulesTests(unittest.TestCase):
    def test_verified_batch_is_published_with_consistent_metadata(self):
        root = Path(__file__).resolve().parents[1]
        report = json.loads((root / "rules/sync-report.json").read_text())
        for name in ("Atlassian", "Jetbrains", "iCloud", "AppleID", "Gemini",
                     "GoogleVoice", "Vercel", "Figma", "Dropbox", "GitLab"):
            with self.subTest(name=name):
                path = root / f"rules/{name}/{name}.yaml"
                body = path.read_bytes()
                rules = read_local(path)
                self.assertTrue(EXPECTED[name].issubset(rules))
                self.assertEqual(len(rules), len(set(rules)))
                counts = Counter(rule.split(",", 1)[0] for rule in rules)
                text = body.decode()
                self.assertIn(f"# 规则总数：{len(rules)}\n", text)
                for kind, count in counts.items():
                    self.assertIn(f"# {kind}: {count}\n", text)
                detail = report["collections"][f"rule/Clash/{name}/{name}.yaml"]
                self.assertEqual(detail["rules"], len(rules))
                self.assertEqual(detail["bytes"], len(body))
                verified = report["discovery"]["verified_additions"][f"{name}/{name}.yaml"]
                self.assertEqual(set(verified["rules"]), EXPECTED[name])
                self.assertEqual(verified["evidence"], OWNERSHIP[name]["evidence"])


if __name__ == "__main__":
    unittest.main()
