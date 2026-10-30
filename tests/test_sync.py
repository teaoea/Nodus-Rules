"""验证上游文件隔离、旧输出迁移及仅替换说明中的下载 URL。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from convert import prepare, write_changed, source_text, convert, render_readme


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "upstream"
        self.root = Path(self.temporary.name) / "output"
        self.folder = self.source / "rule/Clash/Group/Nested"
        self.folder.mkdir(parents=True)
        (self.source / "LICENSE").write_text("上游许可证\n")
        self.files = {
            "Example.list": "DOMAIN,all.example\n",
            "Example.yaml": "payload:\n  - IP-CIDR,192.0.2.0/24\n",
            "Example_Classical.yaml": "payload:\n  - DOMAIN,full.example\n  - IP-CIDR,192.0.2.0/24\n",
            "Example_No_Resolve.yaml": "payload:\n  - IP-CIDR,192.0.2.0/24,no-resolve\n",
            "Example_Domain.yaml": "payload:\n  - '+.example.com'\n  - 'exact.example'\n",
            "Example_Domain.txt": "exact.example\n",
            "Example_Domain_For_Clash.txt": "+.example.com\n",
            "Example_IP.txt": "2001:db8::/32\n",
        }
        for name, text in self.files.items():
            (self.folder / name).write_text(text)
        self.readme = "# 标题\n\n使用说明与统计保持上游原文。\n"
        self.readme += "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Group/Nested/Example.yaml\n"
        self.readme += "https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@release/rule/Clash/Group/Nested/Example_Domain.txt\n"
        self.readme += "https://ghproxy.com/https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/release/rule/Clash/Group/Nested/Example.list\n"
        self.readme += "来源：https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/source/rule/Example.list\n"
        (self.folder / "README.md").write_text(self.readme)

    def run_prepare(self):
        history = "@@2026-10-30T00:00:00Z\n" + "\n".join(
            "rule/Clash/Group/Nested/" + name for name in self.files)
        with patch("convert.subprocess.check_output", side_effect=[history, "revision\n"]):
            return prepare(self.source, self.root, "2026-10-30 00:00 UTC")

    def save(self, planned):
        for path, body in planned.items():
            write_changed(path, body)

    def test_every_source_has_independent_output(self):
        planned, report = self.run_prepare()
        self.assertEqual(len(report), len(self.files) - 1)
        self.assertEqual(len({x["output"] for x in report.values()}), len(self.files) - 1)
        folder = self.root / "rules/Group/Nested"
        self.assertIn(b"domain,all.example", planned[folder / "Example.list.yaml"])
        self.assertNotIn(b"domain,all.example", planned[folder / "Example.yaml"])
        self.assertIn(b"domain-suffix,example.com", planned[folder / "Example_Domain.yaml"])
        self.assertIn(b"ip-cidr,2001:db8::/32", planned[folder / "Example_IP.txt.yaml"])
        self.assertNotIn("rule/Clash/Group/Nested/Example_No_Resolve.yaml", report)
        self.assertNotIn(folder / "Example_No_Resolve.yaml", planned)

    def test_readme_changes_only_download_urls(self):
        planned, _ = self.run_prepare()
        expected = self.readme.replace(
            "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Group/Nested/Example.yaml",
            "https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Group/Nested/Example.yaml").replace(
            "https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@release/rule/Clash/Group/Nested/Example_Domain.txt",
            "https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Group/Nested/Example_Domain.txt.yaml").replace(
            "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/release/rule/Clash/Group/Nested/Example.list",
            "https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Group/Nested/Example.list.yaml")
        self.assertEqual(planned[self.root / "rules/Group/Nested/README.md"], expected.encode())

    def test_incremental_readme_and_single_file_changes(self):
        planned, _ = self.run_prepare()
        self.save(planned)
        again, _ = self.run_prepare()
        self.assertFalse(any(p.suffix == ".yaml" for p in again))
        readme = self.folder / "README.md"
        readme.write_text(self.readme + "\n上游新说明\n")
        changed, _ = self.run_prepare()
        destination = self.root / "rules/Group/Nested/README.md"
        self.assertTrue(changed[destination].endswith("上游新说明\n".encode()))
        (self.root / "rules/Group/Nested/Example.yaml").unlink()
        repaired, _ = self.run_prepare()
        self.assertIn(self.root / "rules/Group/Nested/Example.yaml", repaired)
        self.assertEqual(repaired[destination], changed[destination])

    def test_legacy_list_migration_does_not_contaminate_yaml(self):
        legacy = self.root / "rules/Group/Nested/Example.yaml"
        write_changed(legacy, b"rules:\n  - domain,all.example\n  - domain,manual.example\n")
        write_changed(self.root / "rules/sync-report.json", json.dumps({"collections": {
            "rule/Clash/Group/Nested/Example.list": {"output": "rules/Group/Nested/Example.yaml", "template_version": 8}
        }}).encode())
        planned, _ = self.run_prepare()
        self.assertIn(b"domain,manual.example", planned[legacy.with_name("Example.list.yaml")])
        self.assertNotIn(b"domain,manual.example", planned[legacy])

    def test_missing_upstream_link_and_line_endings_are_preserved(self):
        text = "# 上游\r\nhttps://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Absent.yaml\r\n"
        readme = self.folder / "README.md"
        readme.write_bytes(text.encode())
        warnings = []
        result = render_readme(readme, self.source / "rule/Clash", self.root, warnings)
        self.assertEqual(result, text.encode())
        self.assertEqual(len(warnings), 1)

    def test_resolve_variants_are_excluded_from_rules_and_readme(self):
        for name in ("Example_Resolve.yaml", "Example_Classical_No_Resolve.yaml", "Resolve.list"):
            self.files[name] = "未知类型,不应读取\n"
            (self.folder / name).write_text(self.files[name])
        planned, report = self.run_prepare()
        self.assertFalse(any("Resolve" in key for key in report))
        self.assertFalse(any("Resolve" in path.name for path in planned))
        from convert import format_readme
        readme = ("# 示例\n\n## Clash\n\n#### 配置建议\n"
                  "- Example.yaml 单独使用。\n- Example_Resolve.yaml、Example_Domain.yaml 共同使用。\n"
                  "#### 规则链接\n"
                  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Example_Resolve.yaml\n"
                  "https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Clash/Example_No_%52esolve.yaml\n"
                  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Example.yaml\n")
        rendered = format_readme(readme, "Example")
        self.assertNotIn("Resolve", rendered)
        self.assertNotIn("%52esolve", rendered)
        self.assertIn("Example.yaml 单独使用。", rendered)
        self.assertIn("/Example.yaml```", rendered)

    def test_unknown_yaml_structure_fails_closed(self):
        path = self.folder / "Example.yaml"
        path.write_text("payload: [invalid]\n")
        with self.assertRaises(ValueError):
            source_text(path)

    def test_wildcard_is_reported_without_becoming_suffix(self):
        path = self.folder / "Example_Domain.yaml"
        path.write_text("payload:\n  - '*.example.com'\n")
        rules, detail = convert(source_text(path))
        self.assertEqual(rules, [])
        self.assertEqual(len(detail["skipped"]), 1)


if __name__ == "__main__":
    unittest.main()
