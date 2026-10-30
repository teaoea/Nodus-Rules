#!/usr/bin/env python3
"""将上游 Clash list 转为 Nodus；只写入合并结果，不保留手工原文。"""
from collections import Counter
import ipaddress
from merge import read_local, merge_conditions, RULE_PRIORITY
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote, unquote

TYPES = ("domain", "domain-suffix", "domain-keyword", "ip-cidr", "geoip", "protocol", "port")
REPO = "https://github.com/blackmatrix7/ios_rule_script"
RAW = "https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/"
TEMPLATE_VERSION = 9
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


def output_path(file, upstream, root):
    # 保留源扩展名，避免 Foo.list、Foo.yaml 和 Foo.txt 共用同一输出。
    name = file.name if file.suffix == ".yaml" else file.name + ".yaml"
    return root / "rules" / file.parent.relative_to(upstream) / safe_file(name)


def source_text(file):
    """只接受上游生成器的 payload 字符串列表，不解释任意 YAML。"""
    text = file.read_text(encoding="utf-8-sig")
    if file.suffix == ".list":
        return text
    values, found = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if file.suffix == ".yaml":
            if line == "payload:" and not found:
                found = True
                continue
            if not found or not line.startswith("- "):
                raise ValueError(f"未知上游 YAML 结构：{file}")
            line = line[2:].strip()
            if line.startswith("'"):
                if not line.endswith("'"):
                    raise ValueError(f"上游 YAML 引号不完整：{file}")
                line = line[1:-1].replace("''", "'")
            elif line.startswith('"'):
                line = json.loads(line)
            if not isinstance(line, str):
                raise ValueError(f"上游 YAML 条件不是字符串：{file}")
        if "_Domain" in file.stem:
            if line.startswith("+."):
                line = "DOMAIN-SUFFIX," + line[2:]
            elif "*" in line:
                line = "DOMAIN-WILDCARD," + line
            else:
                line = "DOMAIN," + line
        elif re.search(r"_IP(?:_No_IPv6)?$", file.stem):
            line = ("IP-CIDR6," if ":" in line else "IP-CIDR,") + line
        values.append(line)
    if file.suffix == ".yaml" and not found:
        raise ValueError(f"上游 YAML 缺少 payload：{file}")
    return "\n".join(values)


def render_readme(file, upstream, root, warnings=None):
    """保留上游正文，只改写已同步规则的下载 URL；来源链接保持原样。"""
    text = file.read_bytes().decode("utf-8-sig")
    prefixes = (
        ("https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/", RAW),
        ("https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@", "https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/"),
    )
    for prefix, replacement in prefixes:
        pattern = re.escape(prefix) + r"(?:master|release)/rule/Clash/([^\s`<>\)]+)"
        def replace(match):
            relative = Path(unquote(match[1]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("上游 README 含不安全规则路径")
            source = upstream / relative
            if not source.is_file() or source.suffix not in {".list", ".yaml", ".txt"}:
                if warnings is not None:
                    warning = {"readme": file.relative_to(upstream).as_posix(),
                               "url": match[0], "reason": "上游链接无对应源文件，保留原 URL"}
                    if warning not in warnings:
                        warnings.append(warning)
                return match[0]
            return replacement + quote(output_path(source, upstream, root).relative_to(root).as_posix(), safe="/")
        text = re.sub(pattern, replace, text)
    return text.encode()


def prepare(source, root, date, additions=None):
    upstream = source / "rule/Clash"
    sources = sorted(file for file in upstream.rglob("*")
                     if file.is_file() and file.suffix in {".list", ".yaml", ".txt"})
    if not sources or not (source / "LICENSE").is_file():
        raise ValueError("上游规则或许可证缺失")
    planned, report, entries = {}, {}, []
    old_report = root / "rules/sync-report.json"
    previous = json.loads(old_report.read_text()).get("collections", {}) if old_report.exists() else {}
    owners = {detail["output"]: key for key, detail in previous.items() if "output" in detail}
    history = subprocess.check_output([
        "git", "-C", str(source), "log", "--format=@@%cI", "--name-only", "--no-renames", "--", "rule/Clash"
    ], text=True)
    last_dates, last_date = {}, None
    for line in history.splitlines():
        if line.startswith("@@"):
            last_date = line[2:]
        elif line.startswith("rule/Clash/") and last_date:
            last_dates.setdefault(line, last_date)
    targets = set()
    for file in sources:
        target = output_path(file, upstream, root)
        if target in targets:
            raise ValueError(f"上游名称映射冲突：{target}")
        targets.add(target)
        source_key = file.relative_to(source).as_posix()
        upstream_date = last_dates.get(source_key)
        if not upstream_date:
            raise ValueError(f"无法取得上游 Last commit date：{source_key}；需要完整提交历史")
        old_detail = previous.get(source_key, {})
        target_key = target.relative_to(root).as_posix()
        # 旧版 Foo.list -> Foo.yaml 的条件只迁到 Foo.list.yaml，不污染新 Foo.yaml。
        old_output = old_detail.get("output", target_key)
        local_path = root / old_output
        if owners.get(old_output, source_key) != source_key:
            local = []
        else:
            local = read_local(local_path)
        new_conditions = (additions or {}).get(file.relative_to(upstream).as_posix(), set())
        if (old_detail.get("upstream_last_commit_date") == upstream_date
                and target.is_file() and old_output == target_key
                and old_detail.get("template_version") == TEMPLATE_VERSION
                and not new_conditions.difference(local)):
            report[source_key] = {key: value for key, value in old_detail.items() if key != "merged_alias"}
        else:
            rules, detail = convert(source_text(file))
            merge_stats = {}
            rules = merge_conditions(local, rules, new_conditions, stats=merge_stats)
            detail["merge"] = merge_stats
            body = render(file.stem, rules, date).encode()
            if (target.is_file() and old_output == target_key
                    and old_detail.get("upstream_last_commit_date") == upstream_date
                    and old_detail.get("template_version", 0) >= 6
                    and set(rules) == set(read_local(target))):
                body = target.read_bytes()
            planned[target] = body
            detail.update({"output": target_key, "rules": len(rules), "bytes": len(body),
                           "exceeds_current_core": len(body) > 8*1024*1024 or len(rules) > 100000,
                           "upstream_last_commit_date": upstream_date, "template_version": TEMPLATE_VERSION})
            report[source_key] = detail
        entries.append((target.relative_to(root / "rules").as_posix(), RAW + quote(target_key, safe="/")))
    # README 独立核对：单份规则跳过不会覆盖或遗漏同目录的其他链接。
    readme_warnings = []
    for readme in sorted(upstream.rglob("README.md")):
        planned[root / "rules" / readme.relative_to(upstream)] = render_readme(readme, upstream, root, readme_warnings)
    planned[root / "LICENSE"] = (source / "LICENSE").read_bytes()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    planned[root / "rules/sync-report.json"] = (json.dumps({"upstream": REPO, "revision": revision,
        "date": date, "collections": report, "readme_warnings": readme_warnings}, ensure_ascii=False, indent=2) + "\n").encode()
    index = "# 自动同步规则集合\n\n每个上游 LIST、YAML、TXT 文件分别转换；集合 README 沿用上游正文，仅替换规则下载 URL。\n\n"
    index += "\n".join(f"- [{name}]({quote(name, safe='/')})：[远程规则]({url})" for name, url in entries) + "\n"
    planned[root / "rules/README.md"] = index.encode()
    return planned, report
