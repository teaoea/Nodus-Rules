import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("sync_rules", Path(__file__).parents[1] / "scripts/sync_rules.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class ConversionTests(unittest.TestCase):
    def test_types_and_duplicates(self):
        rules, detail = sync.convert("DOMAIN,Example.COM.\nDOMAIN,example.com\nIP-CIDR6,2001:db8::/32,no-resolve")
        self.assertEqual(rules, {"domain,example.com", "ip-cidr,2001:db8::/32"})
        self.assertEqual(detail["duplicates"], 1)
        self.assertEqual(detail["no_resolve_removed"], 1)

    def test_unsupported_is_reported_without_widening(self):
        rules, detail = sync.convert("PROCESS-NAME,Claude\nIP-ASN,20473\nDOMAIN-KEYWORD,apple.com")
        self.assertFalse(rules)
        self.assertEqual(len(detail["skipped"]), 3)

    def test_unknown_type_aborts(self):
        with self.assertRaises(ValueError):
            sync.convert("FUTURE-CONDITION,example.com")

    def test_policy_and_bad_cidr_are_not_imported(self):
        rules, detail = sync.convert("DOMAIN,example.com,direct\nIP-CIDR,192.0.2.1/24\nIP-CIDR6,192.0.2.0/24")
        self.assertFalse(rules)
        self.assertEqual(len(detail["skipped"]), 3)

    def test_exact_and_suffix_are_distinct_conditions(self):
        rules, _ = sync.convert("DOMAIN,example.com\nDOMAIN-SUFFIX,example.com")
        self.assertEqual(len(rules), 2)

    def test_local_yaml_preserves_manual_conditions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rules.yaml"
            path.write_text("rules:\n  - domain,manual.example\n  - 'domain-suffix,example.com'\n")
            self.assertEqual(sync.read_local(path), {"domain,manual.example", "domain-suffix,example.com"})
            path.write_text("rules: []\n")
            self.assertEqual(sync.read_local(path), set())

    def test_header_and_single_file(self):
        rules = {f"domain,host{i}.example" for i in range(100001)}
        text = sync.render("Large", rules, "2026-10-25")
        self.assertIn("# domain: 100001\n", text)
        self.assertIn("# 规则总数：100001\n", text)
        self.assertEqual(text.count("\n  - "), 100001)

    def test_bad_upstream_leaves_destination_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            collection = source / "rule/Clash/Example"
            collection.mkdir(parents=True)
            (source / "LICENSE").write_text("license")
            (collection / "Example.list").write_text("UNKNOWN,value")
            (collection / "README.md").write_text("upstream")
            target = root / "rules/Example/Example.yaml"
            target.parent.mkdir(parents=True)
            target.write_text("rules:\n  - domain,manual.example\n")
            with self.assertRaises(ValueError):
                sync.prepare(source, root, "2026-10-25")
            self.assertEqual(target.read_text(), "rules:\n  - domain,manual.example\n")

    def test_multiple_rules_and_manual_direct_are_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            folder = source / "rule/Clash/Group"
            folder.mkdir(parents=True)
            (source / "LICENSE").write_text("license")
            (folder / "README.md").write_text("upstream original")
            (folder / "A.list").write_text("DOMAIN,upstream.example\n")
            (folder / "B.list").write_text("DOMAIN-SUFFIX,second.example\n")
            local = root / "rules/Group"
            local.mkdir(parents=True)
            (local / "A.yaml").write_text("rules:\n  - domain,manual.example\n  - domain,upstream.example\n")
            direct = local / "A-direct.yaml"
            direct.write_text("rules:\n  - domain,direct.example\n")
            with patch.object(sync.subprocess, "check_output", return_value="a" * 40):
                planned, report = sync.prepare(source, root, "2026-10-25")
            output = planned[local / "A.yaml"].decode()
            self.assertIn("domain,manual.example", output)
            self.assertEqual(output.count("domain,upstream.example"), 1)
            self.assertNotIn("domain,direct.example", output)
            self.assertNotIn(direct, planned)
            readme = planned[local / "README.md"].decode()
            self.assertIn("Group/A.yaml", readme)
            self.assertIn("Group/B.yaml", readme)
            self.assertEqual(len(report), 2)

    def test_only_previously_generated_direct_alias_is_migrated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            folder = source / "rule/Clash/A"
            folder.mkdir(parents=True)
            (source / "LICENSE").write_text("license")
            (folder / "README.md").write_text("upstream")
            (folder / "A.list").write_text("DOMAIN,upstream.example\n")
            local = root / "rules/A"
            local.mkdir(parents=True)
            (local / "A-direct.yaml").write_text("rules:\n  - domain,merged.example\n")
            (root / "rules/sync-report.json").write_text('{"collections":{"rule/Clash/A/A.list":{"output":"rules/A/A-direct.yaml"}}}')
            with patch.object(sync.subprocess, "check_output", return_value="a" * 40):
                planned, report = sync.prepare(source, root, "2026-10-25")
            self.assertIn("domain,merged.example", planned[local / "A.yaml"].decode())
            self.assertEqual(report["rule/Clash/A/A.list"]["merged_alias"], "rules/A/A-direct.yaml")


if __name__ == "__main__":
    unittest.main()
