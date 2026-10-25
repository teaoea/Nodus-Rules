#!/usr/bin/env python3
"""将上游 Clash list 转为 Nodus；只写入合并结果，不保留手工原文。"""
from collections import Counter
import ipaddress
from merge import read_local, merge_conditions, RULE_PRIORITY
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

TYPES = ("domain", "domain-suffix", "domain-keyword", "ip-cidr", "geoip", "protocol", "port")
REPO = "https://github.com/blackmatrix7/ios_rule_script"
RAW = "https://raw.githubusercontent.com/teaoea/nodus-rules/main/"
TEMPLATE_VERSION = 7
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
    rules, seen, skipped = [], set(), []
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
                duplicates += rule in seen
                if rule not in seen:
                    rules.append(rule)
                    seen.add(rule)
                no_resolve += len(parts) == 3
            except ValueError as exc:
                reason = str(exc)
        if reason:
            skipped.append({"line": number, "rule": line, "reason": reason})
    if input_count == 0:
        raise ValueError("上游正文没有规则，拒绝用空下载结果更新")
    return rules, {"input": input_count, "duplicates": duplicates,
                   "no_resolve_removed": no_resolve, "skipped": skipped}



def render(name, rules, date):
    ordered = sorted(rules, key=lambda r: RULE_PRIORITY.index(r.split(",", 1)[0]))
    counts = Counter(r.split(",", 1)[0] for r in ordered)
    lines = [f"# 名称：{name}", f"# 来源核对日期：{date}", f"# 规则总数：{len(ordered)}"]
    lines += [f"# {kind}: {counts[kind]}" for kind in TYPES]
    lines += ["rules:" if ordered else "rules: []"]
    lines += ["  - " + r for r in ordered]
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


def prepare(source, root, date, additions=None):
    upstream = source / "rule/Clash"
    sources = sorted(upstream.rglob("*.list"))
    if not sources or not (source / "LICENSE").is_file():
        raise ValueError("上游规则或许可证缺失")
    # 全量准备完成才写入：读取、解析或映射失败时不会部分刷新。
    planned, report, entries = {}, {}, []
    old_report = root / "rules/sync-report.json"
    previous = json.loads(old_report.read_text()).get("collections", {}) if old_report.exists() else {}
    history = subprocess.check_output([
        "git", "-C", str(source), "log", "--format=@@%cI", "--name-only", "--no-renames", "--", "rule/Clash"
    ], text=True)
    last_dates = {}
    last_date = None
    for line in history.splitlines():
        if line.startswith("@@"):
            last_date = line[2:]
        elif line.endswith(".list") and last_date:
            last_dates.setdefault(line, last_date)
    for file in sources:
        relative = file.parent.relative_to(upstream)
        name = file.stem
        folder = root / "rules" / relative
        stem = safe_file(name)
        target = folder / (stem + ".yaml")
        if target in planned:
            raise ValueError(f"上游名称映射冲突：{target}")
        text = file.read_text(encoding="utf-8-sig")
        source_key = str(file.relative_to(source))
        upstream_date = last_dates.get(source_key)
        if not upstream_date:
            raise ValueError(f"无法取得上游 Last commit date：{source_key}；需要完整提交历史")
        old_detail = previous.get(source_key, {})
        new_conditions = (additions or {}).get(str(file.relative_to(upstream)), set())
        if (old_detail.get("upstream_last_commit_date") == upstream_date
                and target.is_file()
                and old_detail.get("template_version") == TEMPLATE_VERSION
                and (folder / "README.md").is_file()
                and not new_conditions.difference(read_local(target))):
            report[source_key] = {key: value for key, value in old_detail.items() if key != "merged_alias"}
            entries.append((relative.as_posix(), RAW + quote(str(target.relative_to(root)), safe="/")))
            continue
        rules, detail = convert(text)
        merge_stats = {}
        rules = merge_conditions(read_local(target), rules, (additions or {}).get(str(file.relative_to(upstream)), set()), stats=merge_stats)
        detail["merge"] = merge_stats
        # 只迁移旧转换记录明确登记的自动 -direct 文件；手工 -direct 文件不参与重命名。
        old_output = previous.get(str(file.relative_to(source)), {}).get("output")
        alias = folder / (stem + "-direct.yaml")
        if old_output == str(alias.relative_to(root)) and alias.exists():
            rules = merge_conditions(rules, read_local(alias))
            detail["merged_alias"] = str(alias.relative_to(root))
        body = render(name, rules, date).encode()
        if (target.is_file() and old_detail.get("upstream_last_commit_date") == upstream_date
                and old_detail.get("template_version") == TEMPLATE_VERSION
                and set(rules) == set(read_local(target))):
            body = target.read_bytes()
        planned[target] = body
        url = RAW + quote(str(target.relative_to(root)), safe="/")
        source_path = quote(str(file.relative_to(source)), safe="/")
        source_readme = REPO + "/blob/master/" + quote(str(file.with_name("README.md").relative_to(source)), safe="/")
        doc_link = quote(os.path.relpath(root / "scripts/README.md", folder), safe="/")
        marker = f"upstream-sync:{target.name}"
        block = (f"<!-- {marker}:start -->\n"
                 f"同步时间：{date}\n\n"
                 + f"```text\n{url}\n```\n\n"
                 + f"```yaml\nrule-providers:\n  - name: {stem}\n    url: {url}\n```\n\n"
                 + f"来源：[blackmatrix7/ios_rule_script]({REPO}/blob/master/{source_path})；"
                 + f"[上游说明]({source_readme})。转换及合并由本项目执行，上游内容按 GPL-2.0 分发，"
                 + f"许可与来源记录见 [同步说明]({doc_link})。\n\n"
                 + f"<!-- {marker}:end -->")
        destination_readme = folder / "README.md"
        existing = planned.get(destination_readme, b"").decode()
        planned[destination_readme] = (existing.rstrip() + "\n\n" + block + "\n").lstrip("\n").encode()
        detail.update({"output": str(target.relative_to(root)), "rules": len(rules),
                       "bytes": len(body), "exceeds_current_core": len(body) > 8*1024*1024 or len(rules) > 100000,
                       "upstream_last_commit_date": upstream_date,
                       "template_version": TEMPLATE_VERSION})
        report[str(file.relative_to(source))] = detail
        entries.append((relative.as_posix(), url))
    planned[root / "LICENSE"] = (source / "LICENSE").read_bytes()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    planned[root / "rules/sync-report.json"] = (json.dumps({"upstream": REPO, "revision": revision,
        "date": date, "collections": report}, ensure_ascii=False, indent=2) + "\n").encode()
    index = "# 自动同步规则集合\n\n目录及集合划分以上游为准；每份规则集单独合并去重，同一文件夹可包含多份规则集，上游说明以链接引用，不保存副本。\n\n"
    index += "\n".join(f"- [{name}]({quote(name, safe='/')}/README.md)：[远程规则]({url})" for name, url in entries) + "\n"
    planned[root / "rules/README.md"] = index.encode()
    return planned, report



