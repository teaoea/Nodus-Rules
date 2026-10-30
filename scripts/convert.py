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


def excluded_rule(file):
    """按规则文件名排除 Resolve（含 No_Resolve）及 For_Clash 变体。"""
    name = Path(unquote(str(file))).name
    return any(marker in name for marker in ("Resolve", "For_Clash"))


def preferred_source(file):
    """同目录同主文件名优先 YAML；不同目录或不同主文件名互不替代。"""
    yaml = file.with_suffix(".yaml")
    return yaml if file.suffix != ".yaml" and yaml.is_file() and not excluded_rule(yaml) else file


def select_sources(upstream):
    return sorted({preferred_source(file) for file in upstream.rglob("*")
                   if file.is_file() and file.suffix in {".list", ".yaml", ".txt"}
                   and not excluded_rule(file)})


def output_path(file, upstream, root):
    file = preferred_source(file)
    # 无同名 YAML 的 LIST/TXT 保留源扩展名，避免输出名称碰撞。
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


def format_readme(text, name):
    """按集合说明格式整理上游数据，不复制示例集合的名称、统计或链接。"""
    # 非集合说明保持原文；集合模板以 Clash 规则章节作为识别入口。
    if not re.search(r"^## Clash\s*$", text, re.M):
        return text

    def section(title):
        match = re.search(r"^## " + re.escape(title) + r"[^\S\n]*\n(.*?)(?=^## |\Z)",
                          text, re.M | re.S)
        return match[1].strip() if match else ""

    def tidy(body):
        lines = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                line = "| " + " | ".join(cells) + " |"
                if lines and lines[-1] and not lines[-1].startswith("|"):
                    lines.append("")
            lines.append(line)
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    introduction = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", section("前言"))
                    if paragraph.strip().startswith(("分流规则是", "请通过"))]
    parts = ["# " + name]
    if introduction:
        parts += ["## 前言", "\n\n".join(introduction)]
    statistics = section("规则统计")
    if statistics:
        parts += ["## 规则统计", tidy(statistics)]
    parts.append("## Nodus Core")
    clash = section("Clash")
    advice = re.search(r"^#{3,4} 配置建议[^\S\n]*\n(.*?)(?=^#{1,4} |\Z)",
                       clash, re.M | re.S)
    if advice:
        advice_lines = [line for line in advice[1].splitlines()
                        if not any(excluded_rule(name) for name in
                                   re.findall(r"[^\s、，,`]+\.(?:yaml|list|txt)", line))]
        if any(line.strip() for line in advice_lines):
            parts += ["### 配置建议", tidy("\n".join(advice_lines))]
    parts.append("### 规则链接")
    links = {"MASTER分支 (每日更新)": [], "MASTER分支 CDN (每日更新)": [],
             "MASTER分支 GHProxy (每日更新)": []}
    for url in re.findall(r"https?://[^\s`<>]+", clash):
        if excluded_rule(url):
            continue
        # 本仓库只发布 main；模板仅展示上游 MASTER 对应的三组链接。
        if "/master/rule/Clash/" not in url and "@master/rule/Clash/" not in url:
            continue
        if url.startswith("https://ghproxy.com/"):
            group = "MASTER分支 GHProxy (每日更新)"
        elif url.startswith("https://cdn.jsdelivr.net/"):
            group = "MASTER分支 CDN (每日更新)"
        elif url.startswith("https://raw.githubusercontent.com/"):
            group = "MASTER分支 (每日更新)"
        else:
            continue
        if url not in links[group]:
            links[group].append(url)
    for title, urls in links.items():
        if urls:
            parts += ["#### " + title, "\n\n".join("```text\n" + url + "\n```" for url in urls)]
    children = section("子规则/排除规则")
    if "当前分流规则，已排除以下规则" in children:
        children = children.replace("当前分流规则，未包含其他子规则。", "").strip()
    if children:
        parts += ["## 子规则/排除规则", tidy(children)]
    return "\n\n".join(parts) + "\n"


def render_readme(file, upstream, root, warnings=None):
    """按约定格式整理集合 README，下载 URL 对应本仓库实际输出。"""
    text = format_readme(file.read_bytes().decode("utf-8-sig"), file.parent.name)
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
    sources = select_sources(upstream)
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
        # YAML 优先后，不把旧版 LIST 输出的并集混入上游同名 YAML。
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
        if readme.parent == upstream:
            continue
        planned[root / "rules" / readme.relative_to(upstream)] = render_readme(readme, upstream, root, readme_warnings)
    planned[root / "LICENSE"] = (source / "LICENSE").read_bytes()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    planned[root / "rules/sync-report.json"] = (json.dumps({"upstream": REPO, "revision": revision,
        "date": date, "collections": report, "readme_warnings": readme_warnings}, ensure_ascii=False, indent=2) + "\n").encode()
    index = "# 自动同步规则集合\n\n同目录同名文件优先 YAML，排除 Resolve 与 For_Clash 变体；集合说明按约定格式生成。\n\n"
    index += "\n".join(f"- [{name}]({quote(name, safe='/')})：[远程规则]({url})" for name, url in entries) + "\n"
    planned[root / "rules/README.md"] = index.encode()
    return planned, report
