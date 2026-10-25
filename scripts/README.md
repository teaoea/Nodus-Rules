# 上游规则自动同步

GitHub Actions 每天新加坡时间 04:23 运行，也可在 Actions 中手动运行“同步 Nodus 规则集”。需要仓库允许 `GITHUB_TOKEN` 写入内容；受保护分支若禁止机器人直接推送，任务会报错，不会绕过保护。工作流提交到 `main` 后才会启用，本地配置完成不代表线上任务已经运行。

仅在公开仓库运行，使用标准 `ubuntu-latest` 托管运行器；不使用大型运行器、付费外部服务、Actions 缓存或上传构建产物。按 [GitHub 当前计费规则](https://docs.github.com/en/billing/concepts/product-billing/github-actions)，公开仓库的标准运行器免费。仓库转为私有或缺少公开可见性信息时整项任务跳过；仅每日定时及手动触发，定时任务遇到上游提交未变化时跳过转换和提交。GitHub 将来的政策变化不在本项目控制范围内。

上游为 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) 的 `master`，读取 `rule/Clash` 下全部 `.list`，包含嵌套集合；各集合的 README 原文保存为 `README.upstream.md`。只读取上游数据，不执行其代码。本项目与上游统一采用 [GPL-2.0](../LICENSE)，根 LICENSE 和上游许可证副本均在同步时更新；转换器由本项目独立编写，同样按 GPL-2.0 分发。原作者、来源和修改日期分别见各集合说明、上游 README、YAML 头注释及转换记录。

## 转换和合并

- 输出到 `rules/{上游内容目录}/{规则集}.yaml`，目录、集合划分和规则集名称以上游为准，同一文件夹可包含多个规则集。文件名仅在不符合 Nodus 安全文件名约束时将特殊字符替换为短横线。手工已有同名文件直接合并条件并去重，每个同名规则集只保留一个合并 YAML，不保存手工原文副本。不同条件类型不互相替代，不自动削减后缀覆盖。
- 同步采用增量并集：上游新增条件会加入，已合并的条件不会仅因上游后续删除而自动消失。需要删除时，同时检查上游当前是否仍包含该条件，否则下次同步会重新加入。
- 自动同步不添加 `-direct`，不推断代理或直连策略；导入者在主配置设置 `policy`。`-direct` 命名约束只用于手工上传的直连规则集。上游内容分类不等于域名所有权审计。
- `DOMAIN`、`DOMAIN-SUFFIX` 转为小写 Nodus 条件；仅接受符合 Nodus 的 `DOMAIN-KEYWORD`。IPv4／IPv6 CIDR 统一写为 `ip-cidr`，保留地址族和严格网络对齐要求。
- `PROCESS-NAME`、`IP-ASN` 等不支持的条件，以及不符合 Nodus 值域的条目，记录到 [sync-report.json](../rules/sync-report.json)，不扩大成其他匹配。未知类型使任务失败，已有文件不更新。
- `no-resolve` 无 Nodus 对应选项，转换保留 IP 条件并在记录中统计移除的选项数量，因此不能声称与上游 DNS 行为完全等价。后缀／关键词在 `policy: reject` 时会被当前 Core 忽略，广告类集合不能据转换成功宣称可完整拦截。
- 大集合保持单文件，超过当前 Core 8 MiB／100,000 条限制时仍生成并标记，不能宣称可加载；Core 容量需求已登记，未来须按实际版本验证。全体集合不应一次性全部导入，合并快照也受当前条目和预算约束。
- 各集合只生成名称、来源核对日期、总数和各类型数量的简洁头注释；用法、来源及转换边界放在 README。

## 本地执行

准备上游只读 checkout 后执行：

```sh
python3 -m unittest discover -s tests -v
python3 scripts/sync_rules.py --source /path/to/ios_rule_script
```

不依赖第三方 Python 包。全部文件读取和转换准备成功后才开始写入；单文件以临时文件替换。磁盘写入中断可能留下部分本地结果，但 Actions 只有命令成功才提交，不会推送失败的转换结果。同步只更新生成的规则、集合说明、来源许可和记录，同步更新根 LICENSE，不自动修改项目主 README 或开发约束。
