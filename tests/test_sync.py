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
            "OnlyList.list": "DOMAIN,only-list.example\n",
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
        self.assertEqual(len(report), len(self.files) - 4)
        self.assertEqual(len({x["output"] for x in report.values()}), len(self.files) - 4)
        folder = self.root / "rules/Group/Nested"
        self.assertIn(b"domain,only-list.example", planned[folder / "OnlyList.list.yaml"])
        self.assertNotIn(folder / "Example.list.yaml", planned)
        self.assertNotIn(folder / "Example_Domain.txt.yaml", planned)
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
            "https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Group/Nested/Example_Domain.yaml").replace(
            "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/release/rule/Clash/Group/Nested/Example.list",
            "https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Group/Nested/Example.yaml")
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

    def test_yaml_priority_does_not_reuse_legacy_list_union(self):
        legacy = self.root / "rules/Group/Nested/Example.yaml"
        write_changed(legacy, b"rules:\n  - domain,all.example\n  - domain,manual.example\n")
        write_changed(self.root / "rules/sync-report.json", json.dumps({"collections": {
            "rule/Clash/Group/Nested/Example.list": {"output": "rules/Group/Nested/Example.yaml", "template_version": 8}
        }}).encode())
        planned, _ = self.run_prepare()
        self.assertNotIn(legacy.with_name("Example.list.yaml"), planned)
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
        for name in ("Example_Resolve.yaml", "Example_Classical_No_Resolve.yaml", "Resolve.list", "Example_For_Clash.txt"):
            self.files[name] = "未知类型,不应读取\n"
            (self.folder / name).write_text(self.files[name])
        planned, report = self.run_prepare()
        self.assertFalse(any("Resolve" in key or "For_Clash" in key for key in report))
        self.assertFalse(any("Resolve" in path.name or "For_Clash" in path.name for path in planned))
        from convert import format_readme
        readme = ("# 示例\n\n## Clash\n\n#### 配置建议\n"
                  "- Example.yaml 单独使用。\n- Example_Resolve.yaml、Example_Domain.yaml 共同使用。\n"
                  "- Example_Domain_For_Clash.txt 单独使用。\n"
                  "#### 规则链接\n"
                  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Example_Domain_For_Clash.txt\n"
                  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Example_Resolve.yaml\n"
                  "https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Clash/Example_No_%52esolve.yaml\n"
                  "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Example.yaml\n")
        rendered = format_readme(readme, "Example")
        self.assertNotIn("Resolve", rendered)
        self.assertNotIn("%52esolve", rendered)
        self.assertNotIn("For_Clash", rendered)
        self.assertIn("Example.yaml 单独使用。", rendered)
        self.assertIn("/Example.yaml\n```", rendered)
        self.assertIn("```text\nhttps://", rendered)

    def test_yaml_preference_is_scoped_to_directory_and_stem(self):
        from convert import select_sources, preferred_source
        sibling = self.folder / "Other"
        sibling.mkdir()
        other = sibling / "OnlyList.yaml"
        other.write_text("payload:\n  - DOMAIN,other.example\n")
        sources = select_sources(self.source / "rule/Clash")
        self.assertIn(self.folder / "OnlyList.list", sources)
        self.assertIn(other, sources)
        self.assertIn(self.folder / "Example_Classical.yaml", sources)
        self.assertNotIn(self.folder / "Example.list", sources)
        self.assertEqual(preferred_source(self.folder / "Example_Domain.txt"),
                         self.folder / "Example_Domain.yaml")

    def test_download_urls_use_separate_copyable_code_blocks(self):
        from convert import render_readme
        text = ("## Clash\n\n#### 规则链接\n"
                "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Group/Nested/Example.yaml\n"
                "https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Clash/Group/Nested/Example.yaml\n"
                "https://ghproxy.com/https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Group/Nested/Example.yaml\n")
        path = self.folder / "README.md"
        path.write_text(text)
        rendered = render_readme(path, self.source / "rule/Clash", self.root).decode()
        import re
        blocks = re.findall(r"^```text\n(https://[^\n]+)\n```$", rendered, re.M)
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(url.endswith("/rules/Group/Nested/Example.yaml") for url in blocks))
        self.assertNotIn("```https://", rendered)

    def test_readme_uses_repository_sync_time(self):
        text = ("## 规则统计\n\n最后更新时间：2000-01-01 00:00:00\n\n"
                "## Clash\n\n#### 规则链接\n"
                "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/Group/Nested/Example.yaml\n")
        (self.folder / "README.md").write_text(text)
        planned, _ = self.run_prepare()
        result = planned[self.root / "rules/Group/Nested/README.md"].decode()
        self.assertIn("最后更新时间：2026-10-30 00:00 UTC", result)
        self.assertNotIn("2000-01-01", result)

    def test_readme_combines_ipv4_and_ipv6_statistics(self):
        from convert import format_readme
        for rows, expected in (("| IP-CIDR | 17 |\n| IP-CIDR6 | 4 |", 21),
                               ("| IP-CIDR6 | 4 |", 4),
                               ("| IP-CIDR | 17 |", 17)):
            text = "## 规则统计\n\n| 类型 | 数量(条) |\n| ---- | ---- |\n" + rows + "\n| TOTAL | 99 |\n\n## Clash\n"
            rendered = format_readme(text, "Example")
            self.assertNotIn("IP-CIDR6", rendered)
            self.assertIn(f"| ip-cidr | {expected} |", rendered)
            self.assertIn("| total | 99 |", rendered)

    def test_statistics_labels_are_lowercase(self):
        from convert import format_readme
        text = ("## 规则统计\n\n| 类型 | 数量(条) |\n| ---- | ---- |\n"
                "| DOMAIN | 17 |\n| DOMAIN-KEYWORD | 9 |\n| DOMAIN-SUFFIX | 3674 |\n"
                "| IP-CIDR | 17 |\n| IP-CIDR6 | 4 |\n| TOTAL | 3721 |\n\n## Clash\n")
        rendered = format_readme(text, "Example")
        for name in ("domain", "domain-keyword", "domain-suffix", "ip-cidr", "total"):
            self.assertIn("| " + name + " |", rendered)
        self.assertNotIn("IP-CIDR6", rendered)
        self.assertNotIn("ip-cidr6", rendered)
        self.assertIn("| ip-cidr | 21 |", rendered)

    def test_country_name_is_bold_without_custom_color_styles(self):
        from convert import format_readme
        text = ("## 前言\n\n请通过【中华人民共和国 People's Republic of China】合法的互联网出入口信道访问规则中的地址。\n\n## Clash\n")
        rendered = format_readme(text, "Example")
        self.assertIn("【**中华人民共和国 People's Republic of China**】", rendered)
        self.assertNotIn("style=", rendered)

    def test_country_image_uses_valid_relative_path_for_nested_collections(self):
        text = "## 前言\n\n请通过【中华人民共和国 People's Republic of China】合法的互联网出入口信道访问规则中的地址。\n\n## Clash\n"
        path = self.folder / "README.md"
        path.write_text(text)
        rendered = render_readme(path, self.source / "rule/Clash", self.root).decode()
        self.assertIn("![请通过中华人民共和国 People's Republic of China合法的互联网出入口信道访问规则中的地址。](../../../assets/china-network-notice.svg)", rendered)
        asset = self.root / "rules/Group/Nested/../../../assets/china-network-notice.svg"
        self.assertEqual(asset.resolve(), (self.root / "assets/china-network-notice.svg").resolve())

    def test_country_notice_is_one_complete_sentence_image(self):
        path = self.folder / "README.md"
        path.write_text("## 前言\n\n请通过【中华人民共和国 People's Republic of China】合法的互联网出入口信道访问规则中的地址。\n\n## Clash\n")
        rendered = render_readme(path, self.source / "rule/Clash", self.root).decode()
        self.assertIn("![请通过中华人民共和国 People's Republic of China合法的互联网出入口信道访问规则中的地址。](../../../assets/china-network-notice.svg)", rendered)
        self.assertNotIn("> ", rendered)
        self.assertNotIn("【", rendered)

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
