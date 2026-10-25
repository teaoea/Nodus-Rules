#!/usr/bin/env python3
"""将上游 Clash list 转为 Nodus；只写入合并结果，不保留手工原文。"""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

TYPES = ("domain", "domain-suffix", "domain-keyword", "ip-cidr", "geoip", "protocol", "port")
REPO = "https://github.com/blackmatrix7/ios_rule_script"
RAW = "https://raw.githubusercontent.com/teaoea/nodus-rules/main/"
UNSUPPORTED = {"PROCESS-NAME", "PROCESS-PATH", "IP-ASN", "DOMAIN-REGEX", "DOMAIN-WILDCARD",
               "URL-REGEX", "USER-AGENT", "AND", "OR", "NOT", "SRC-IP-CIDR", "SRC-PORT",
               "DST-PORT", "NETWORK", "RULE-SET", "GEOIP", "GEOSITE", "MATCH"}


def host(value):
    value = value.lower().removesuffix(".")
    if not value or len(value) > 253:
        raise ValueError("域名长度不合法")
    for label in value.split("."):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label):
            raise ValueError("域名不符合 Nodus ASCII 标签约束")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("域名条件不能是 IP 地址")


def convert(text):
    rules, skipped = set(), []
    input_count = duplicates = no_resolve = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "//")):
            continue
        input_count += 1
        parts = line.split(",")
        kind = parts[0]
        reason = None
        if kind in UNSUPPORTED:
            reason = "Nodus 远程规则不支持此条件或语义"
        elif kind not in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6"}:
            raise ValueError(f"第 {number} 行出现未知类型：{kind}")
        else:
            try:
                is_ip = kind in {"IP-CIDR", "IP-CIDR6"}
                if len(parts) != 2 and not (is_ip and len(parts) == 3 and parts[2] == "no-resolve"):
                    raise ValueError("不接受自带策略、未知选项或多余字段")
                value = parts[1]
                if value != value.strip():
                    raise ValueError("条件包含首尾空白")
                if kind in {"DOMAIN", "DOMAIN-SUFFIX"}:
                    value = host(value)
                elif kind == "DOMAIN-KEYWORD":
                    if not re.fullmatch(r"[A-Za-z0-9-]{1,63}", value):
                        raise ValueError("Nodus 关键词仅支持 1–63 位字母数字或短横线")
                    value = value.lower()
                else:
                    network = ipaddress.ip_network(value, strict=True)
                    if network.version != (6 if kind == "IP-CIDR6" else 4):
                        raise ValueError("IP 地址族与类型不符")
                    value = str(network)
                target = "ip-cidr" if is_ip else kind.lower()
                rule = f"{target},{value}"
                duplicates += rule in rules
                rules.add(rule)
                no_resolve += len(parts) == 3
            except ValueError as exc:
                reason = str(exc)
        if reason:
            skipped.append({"line": number, "rule": line, "reason": reason})
    if input_count == 0:
        raise ValueError("上游正文没有规则，拒绝用空下载结果更新")
    return rules, {"input": input_count, "duplicates": duplicates,
                   "no_resolve_removed": no_resolve, "skipped": skipped}


def read_local(path):
    if not path.exists():
        return set()
    # 本仓库正文是单个 rules 字符串列表；不猜测其他 YAML 结构。
    rules, found = set(), False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "rules: []" and not found:
            found = True
            continue
        if line == "rules:" and not found:
            found = True
        elif found and line.startswith("- "):
            value = line[2:]
            if value.startswith('"'):
                value = json.loads(value)
            elif value.startswith("'"):
                if not value.endswith("'"):
                    raise ValueError(f"本地 YAML 引号不完整：{path}")
                value = value[1:-1].replace("''", "'")
            if not isinstance(value, str) or value.split(",", 1)[0] not in TYPES:
                raise ValueError(f"本地条件不符合 Nodus 格式：{path}")
            rules.add(value)
        else:
            raise ValueError(f"本地文件结构无法安全合并：{path}")
    if not found:
        raise ValueError(f"本地文件缺少 rules：{path}")
    return rules


def render(name, rules, date):
    ordered = sorted(rules, key=lambda r: (TYPES.index(r.split(",", 1)[0]), r))
    counts = Counter(r.split(",", 1)[0] for r in ordered)
    lines = [f"# 名称：{name}", f"# 来源核对日期：{date}", f"# 规则总数：{len(ordered)}"]
    lines += [f"# {kind}: {counts[kind]}" for kind in TYPES]
    lines += ["rules:" if ordered else "rules: []"]
    lines += ["  - " + json.dumps(r, ensure_ascii=False) for r in ordered]
    return "\n".join(lines) + "\n"


def safe_file(name):
    name = re.sub(r"[^A-Za-z0-9._-]", "-", name)
    if not name or name in {".", ".."} or len(name) > 110:
        raise ValueError("无法生成安全的 Nodus 文件名")
    return name


def write_changed(path, content):
    if path.exists() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".sync-tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def prepare(source, root, date):
    upstream = source / "rule/Clash"
    sources = sorted(upstream.rglob("*.list"))
    if not sources or not (source / "LICENSE").is_file():
        raise ValueError("上游规则或许可证缺失")
    # 全量准备完成才写入：读取、解析或映射失败时不会部分刷新。
    planned, report, entries = {}, {}, []
    old_report = root / "rules/sync-report.json"
    previous = json.loads(old_report.read_text()).get("collections", {}) if old_report.exists() else {}
    for file in sources:
        relative = file.parent.relative_to(upstream)
        name = file.stem
        folder = root / "rules" / relative
        stem = safe_file(name)
        target = folder / (stem + ".yaml")
        if target in planned:
            raise ValueError(f"上游名称映射冲突：{target}")
        rules, detail = convert(file.read_text(encoding="utf-8-sig"))
        rules |= read_local(target)
        # 只迁移旧转换记录明确登记的自动 -direct 文件；手工 -direct 文件不参与重命名。
        old_output = previous.get(str(file.relative_to(source)), {}).get("output")
        alias = folder / (stem + "-direct.yaml")
        if old_output == str(alias.relative_to(root)) and alias.exists():
            rules |= read_local(alias)
            detail["merged_alias"] = str(alias.relative_to(root))
        body = render(name, rules, date).encode()
        planned[target] = body
        readme = file.with_name("README.md")
        if not readme.is_file():
            raise ValueError(f"上游集合缺少 README：{relative}")
        planned[folder / "README.upstream.md"] = readme.read_bytes()
        url = RAW + quote(str(target.relative_to(root)), safe="/")
        source_path = quote(str(file.relative_to(source)), safe="/")
        doc_link = quote(os.path.relpath(root / "scripts/README.md", folder), safe="/")
        report_link = quote(os.path.relpath(root / "rules/sync-report.json", folder), safe="/")
        marker = f"upstream-sync:{target.name}"
        block = (f"<!-- {marker}:start -->\n"
                 "采用 Nodus `rules:` 格式，"
                 + "导入后按需要选择策略；正文不附带策略。\n\n"
                 + f"```text\n{url}\n```\n\n"
                 + f"来源：[blackmatrix7/ios_rule_script]({REPO}/blob/master/{source_path})；"
                 + "[上游说明原文](README.upstream.md)。转换及合并由本项目执行，上游原文按 GPL-2.0 分发，"
                 + f"许可与来源记录见 [同步说明]({doc_link})。\n\n"
                 + f"转换后共 {len(rules)} 条；未转换 {len(detail['skipped'])} 条，"
                 + f"详见 [转换记录]({report_link})。不支持的条件不作等价替换；"
                 + "`no-resolve` 无对应选项，IP 条件保留但此选项不保留。\n\n"
                 + f"<!-- {marker}:end -->")
        destination_readme = folder / "README.md"
        old = (planned[destination_readme].decode() if destination_readme in planned
               else destination_readme.read_text() if destination_readme.exists() else f"# {relative.name}\n")
        if "<!-- upstream-sync:start -->" in old:
            old = re.sub(r"<!-- upstream-sync:start -->.*?<!-- upstream-sync:end -->", lambda _: block, old, flags=re.S)
        elif f"<!-- {marker}:start -->" in old:
            old = re.sub(re.escape(f"<!-- {marker}:start -->") + r".*?" + re.escape(f"<!-- {marker}:end -->"),
                         lambda _: block, old, flags=re.S)
        else:
            old = old.rstrip() + "\n\n" + block + "\n"
        planned[destination_readme] = old.encode()
        detail.update({"output": str(target.relative_to(root)), "rules": len(rules),
                       "bytes": len(body), "exceeds_current_core": len(body) > 8*1024*1024 or len(rules) > 100000})
        report[str(file.relative_to(source))] = detail
        entries.append((relative.as_posix(), url))
    planned[root / "ThirdParty/ios_rule_script/LICENSE"] = (source / "LICENSE").read_bytes()
    planned[root / "LICENSE"] = (source / "LICENSE").read_bytes()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    planned[root / "rules/sync-report.json"] = (json.dumps({"upstream": REPO, "revision": revision,
        "date": date, "collections": report}, ensure_ascii=False, indent=2) + "\n").encode()
    index = "# 自动同步规则集合\n\n目录及集合划分以上游为准；每份规则集单独合并去重，同一文件夹可包含多份规则集，并同步上游 README。\n\n"
    index += "\n".join(f"- [{name}]({quote(name, safe='/')}/README.md)：[远程规则]({url})" for name, url in entries) + "\n"
    planned[root / "rules/README.md"] = index.encode()
    return planned, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--date", default=datetime.now(timezone(timedelta(hours=8))).date().isoformat())
    args = parser.parse_args()
    planned, report = prepare(args.source, args.root, args.date)
    for path, data in planned.items():
        write_changed(path, data)
    for detail in report.values():
        if "merged_alias" in detail:
            (args.root / detail["merged_alias"]).unlink()
    print(json.dumps({"collections": len(report), "rules": sum(r["rules"] for r in report.values()),
        "skipped": sum(len(r["skipped"]) for r in report.values()),
        "exceeds_current_core": sum(r["exceeds_current_core"] for r in report.values())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
