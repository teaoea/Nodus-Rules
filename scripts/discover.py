"""免费公开网络候选搜索；只有具备归属依据的域名才可自动入库。"""
import html
from convert import excluded_rule
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

# 映射是归属依据，不从集合名称或搜索排名猜测所有权。其余集合仍搜索、记录候选，待补齐依据。
OWNERSHIP = {
    "115": {"roots": ["115.com"], "telemetry": [], "evidence": ["https://115.com/"]},
    "Claude": {
        "roots": ["anthropic.com", "claude.ai", "claude.app", "claude.com", "claudemcpcontent.com", "claudeusercontent.com"],
        "telemetry": ["browser-intake-us5-datadoghq.com", "http-intake.logs.us5.datadoghq.com", "cdn.usefathom.com"],
        # 已核实的规则直接参与每次合并，不依赖轮询搜索或搜索摘要命中。
        "verified_rules": [
            "domain-suffix,anthropic.com", "domain-suffix,claude.ai",
            "domain-suffix,claude.app", "domain-suffix,claude.com",
            "domain-suffix,claudemcpcontent.com", "domain-suffix,claudeusercontent.com",
            "domain,browser-intake-us5-datadoghq.com",
            "domain,http-intake.logs.us5.datadoghq.com", "domain,cdn.usefathom.com",
        ],
        "evidence": ["https://code.claude.com/docs/en/network-config", "https://code.claude.com/docs/en/desktop#network-access-requirements", "https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Clash/Claude/Claude.list"],
    },
    "OpenAI": {
        "roots": ["openai.com", "chatgpt.com", "oaistatic.com", "oaiusercontent.com", "oaistatsig.com"],
        "telemetry": [],
        "evidence": ["https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web-and-apps"],
    },
    "Apple": {"roots": ["apple.com"], "telemetry": [], "evidence": ["https://www.apple.com/"]},
    "iCloud": {"roots": ["icloud.com", "icloud.com.cn"], "telemetry": [], "evidence": ["https://support.apple.com/en-us/101555"]},
    "Google": {"roots": ["google.com"], "telemetry": [], "evidence": ["https://www.google.com/"]},
    "YouTube": {"roots": ["youtube.com", "youtu.be"], "telemetry": [], "evidence": ["https://www.youtube.com/"]},
}
OWNERSHIP["ChatGPT"] = OWNERSHIP["OpenAI"]
DOMAIN = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}\b", re.I)


def approved_candidate(name, candidate):
    candidate = candidate.lower().rstrip(".")
    policy = OWNERSHIP.get(name)
    if not policy or not policy.get("evidence"):
        return False
    return candidate in policy["telemetry"] or any(
        candidate == root or candidate.endswith("." + root) for root in policy["roots"])


def public_search(name):
    # 公开 RSS 搜索，无 API key、付费服务或付费模型；被拒绝时记录失败，不绕过验证。
    url = "https://www.bing.com/search?" + urlencode({"format": "rss", "q": f'"{name}" official domains network rules'})
    request = Request(url, headers={"User-Agent": "Nodus-Rules/1.0 (+https://github.com/teaoea/Nodus-Rules)"})
    with urlopen(request, timeout=6) as response:
        data = response.read(512 * 1024 + 1)
    if len(data) > 512 * 1024:
        raise ValueError("搜索结果超过读取上限")
    parsed = ET.fromstring(data)
    if parsed.tag != "rss":
        raise ValueError("搜索服务未返回 RSS；不处理验证页或未知格式")
    domains, sources = set(), []
    for item in parsed.findall("./channel/item")[:10]:
        link = item.findtext("link", "")
        host = urlsplit(link).hostname
        if host:
            domains.add(host.lower())
        text = html.unescape(" ".join(item.findtext(key, "") for key in ("title", "description")))
        domains.update(x.lower() for x in DOMAIN.findall(text))
        if link.startswith("https://"):
            sources.append(link)
    return domains, sources


def discover(source, root, timestamp, limit=24, budget_seconds=90, search=public_search):
    files = sorted(file for file in (source / "rule/Clash").rglob("*.list")
                   if not excluded_rule(file))
    previous = root / "rules/sync-report.json"
    state = json.loads(previous.read_text()).get("discovery", {}) if previous.exists() else {}
    cursor = state.get("next_index", 0) % max(len(files), 1)
    reports = dict(state.get("collections", {}))
    additions = {}
    verified = {}
    for file in files:
        policy = OWNERSHIP.get(file.stem, {})
        rules = set(policy.get("verified_rules", []))
        if not rules or not policy.get("evidence"):
            continue
        if any(rule.split(",", 1)[0] not in {"domain", "domain-suffix"}
               or not approved_candidate(file.stem, rule.split(",", 1)[1]) for rule in rules):
            raise ValueError("已核实规则超出集合归属范围")
        key = file.relative_to(source / "rule/Clash").as_posix()
        additions[key] = rules
        verified[key] = {"rules": sorted(rules), "evidence": policy["evidence"]}
    started = time.monotonic()
    attempted = 0
    # 全部集合轮询；每次有请求数量和时长上限，不为“全网”发起无界爬取。
    for offset in range(min(limit, len(files))):
        if time.monotonic() - started >= budget_seconds:
            break
        file = files[(cursor + offset) % len(files)]
        relative = file.parent.relative_to(source / "rule/Clash").as_posix()
        detail = {"checked_at": timestamp, "name": file.stem}
        try:
            candidates, sources = search(file.stem)
            accepted = sorted(x for x in candidates if approved_candidate(file.stem, x))
            # 精确主机匹配，不将某个第三方服务自动扩大为整个根域。
            additions.setdefault(relative + "/" + file.name, set()).update("domain," + domain for domain in accepted)
            detail.update({"status": "checked" if file.stem in OWNERSHIP else "needs_ownership_evidence",
                           "sources": sources, "candidates": sorted(candidates)[:100],
                           "accepted": accepted, "ownership_evidence": OWNERSHIP.get(file.stem, {}).get("evidence", [])})
        except Exception as exc:
            # 搜索失败不影响可信上游同步；失败结果不能授权新增域名。
            detail.update({"status": "search_failed", "error": type(exc).__name__, "accepted": []})
        reports[relative + "/" + file.name] = detail
        attempted += 1
        time.sleep(0.25)
    return additions, {"engine": "Bing public RSS", "checked_at": timestamp,
                       "next_index": (cursor + attempted) % max(len(files), 1),
                       "attempted": attempted, "total_collections": len(files),
                       "verified_additions": verified, "collections": reports}
