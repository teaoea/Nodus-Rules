"""云端协调：搜索候选、转换、合并、更新说明和许可证。"""
import argparse
from datetime import datetime, timezone
import json
import subprocess
from pathlib import Path
from convert import prepare, write_changed
from discover import discover


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--search-limit", type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.search_limit <= 24:
        parser.error("每轮候选搜索数量必须为 1–24")
    shallow = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "--is-shallow-repository"], text=True).strip()
    if shallow != "false":
        parser.error("Last commit date 判断需要上游完整提交历史，请设置 fetch-depth: 0")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    additions, search_report = discover(args.source, args.root, timestamp, limit=args.search_limit) if args.discover else ({}, None)
    planned, report = prepare(args.source, args.root, timestamp, additions=additions)
    report_path = args.root / "rules/sync-report.json"
    data = json.loads(planned[report_path])
    if search_report is not None:
        data["discovery"] = search_report
    planned[report_path] = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    for path, content in planned.items():
        write_changed(path, content)
    for detail in report.values():
        if "merged_alias" in detail:
            (args.root / detail["merged_alias"]).unlink()
    removed_readmes = 0
    for readme in (args.root / "rules").rglob("README.upstream.md"):
        readme.unlink()
        removed_readmes += 1
    print(json.dumps({"collections": len(report), "rules": sum(x["rules"] for x in report.values()),
                      "skipped": sum(len(x["skipped"]) for x in report.values()),
                      "removed_upstream_readmes": removed_readmes,
                      "searches": search_report["attempted"] if search_report else 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
