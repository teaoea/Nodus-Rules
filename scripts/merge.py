"""Nodus 同名规则合并与精确去重；不保留原文副本。"""
import json
import ipaddress
import re

TYPES = ("domain", "domain-suffix", "domain-keyword", "ip-cidr", "geoip", "protocol", "port")
RULE_PRIORITY = ("process-name", "protocol", "port", "domain", "domain-suffix", "domain-keyword", "ip-cidr", "geoip", "final")
SPECIAL_REJECT = frozenset({"domain", "ip-cidr", "protocol", "port"})

def read_local(path):
    if not path.exists():
        return set()
    # 本仓库正文是单个 rules 字符串列表；不猜测其他 YAML 结构。
    rules, seen, found = [], set(), False
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
            if value not in seen:
                rules.append(value)
                seen.add(value)
        else:
            raise ValueError(f"本地文件结构无法安全合并：{path}")
    if not found:
        raise ValueError(f"本地文件缺少 rules：{path}")
    return rules


def normalize(rule):
    parts = rule.split(",")
    kind = parts[0]
    if kind not in TYPES or len(parts) < 2:
        raise ValueError("非法 Nodus 条件")
    if kind in {"domain", "domain-suffix", "domain-keyword"}:
        if len(parts) != 2:
            raise ValueError("远程条件不能附带策略")
        parts[1] = parts[1].lower()
        if kind != "domain-keyword":
            parts[1] = parts[1].removesuffix(".")
    elif kind == "ip-cidr":
        if len(parts) != 2:
            raise ValueError("远程条件不能附带策略")
        parts[1] = str(ipaddress.ip_network(parts[1], strict=True))
    elif kind == "port" and len(parts) == 2:
        first, _, last = parts[1].partition("-")
        first, last = int(first), int(last or first)
        if not 1 <= first <= last <= 65535:
            raise ValueError("非法端口区间")
        parts[1] = str(first) if first == last else f"{first}-{last}"
    elif kind in {"port", "protocol"} and len(parts) == 3:
        parts[2] = parts[2].lower().removesuffix(".")
    return ",".join(parts)


def merge_conditions(*groups, policy=None, stats=None):
    """对照 Core Snapshot::generate/Index::coverage，保留同类原始顺序。

    正文没有策略；未知 policy 时不裁剪可能为 REJECT 的 IP/端口。
    远程 suffix 在 REJECT 导入阶段被忽略，因此同类型 suffix 完整覆盖可安全去除。
    不用 suffix 删除精确 domain，不用关键词子串删除关键词，不据 DNS 结果合并 IP/域名。
    """
    kept, exact, suffixes, networks, ports = [], set(), set(), {4: [], 6: []}, []
    duplicates = pruned = 0
    for group in groups:
        ordered = sorted(group) if isinstance(group, set) else group
        for original in ordered:
            rule = normalize(original)
            if rule in exact:
                duplicates += 1
                continue
            kind, value = rule.split(",", 1)
            covered = False
            if kind == "domain-suffix" and policy != "reject":
                labels = value.split(".")
                covered = any(".".join(labels[i:]) in suffixes for i in range(len(labels)))
            elif kind == "ip-cidr" and policy in {"direct", "proxy"}:
                network = ipaddress.ip_network(value, strict=True)
                covered = any(network.subnet_of(parent) for parent in networks[network.version])
            elif kind == "port" and "," not in value and policy in {"direct", "proxy"}:
                first, _, last = value.partition("-")
                first, last = int(first), int(last or first)
                covered = any(left <= first and last <= right for left, right in ports)
            if covered:
                pruned += 1
                continue
            exact.add(rule)
            kept.append(rule)
            if kind == "domain-suffix":
                suffixes.add(value)
            elif kind == "ip-cidr" and policy in {"direct", "proxy"}:
                network = ipaddress.ip_network(value, strict=True)
                networks[network.version].append(network)
            elif kind == "port" and "," not in value and policy in {"direct", "proxy"}:
                first, _, last = value.partition("-")
                ports.append((int(first), int(last or first)))
    if stats is not None:
        stats.update({"duplicates": duplicates, "pruned": pruned, "conflicts": 0,
                      "policy": policy or "unknown; policy-dependent pruning deferred to Core"})
    return kept

