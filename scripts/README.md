# 云端规则同步

工作流每天 00:00、12:00 UTC 运行，也可在 GitHub Actions 手动启动。仅公开仓库使用标准 `ubuntu-latest`；私有仓库或可见性未知时跳过，不使用付费 API、缓存或构建产物上传。分支保护若禁止机器人提交，任务会失败，不绕过保护。

## 脚本职责

- `discover.py`：通过免费的公开 RSS 搜索查找候选来源，按集合轮询并依据自有域名及精确遥测白名单筛选。已核实并登记在 `verified_rules` 的条件每次同步直接参与对应集合合并，不受轮询进度或搜索失败影响；记录在 `verified_additions`，与实际搜索结果分开。每轮最多 24 个集合、预算约 90 秒；公开接口可能拒绝请求或更改格式，失败会记录，不绕过验证。尚无可信归属映射的集合只记候选，不自动加入；映射登记在 `OWNERSHIP`，只有核实依据后才能扩充。
- `convert.py`：读取上游全部 Clash LIST、YAML、TXT 路径，以完整 Git 历史取得每份文件的 Last commit date。每份文件独立转换：YAML 保留原名，LIST/TXT 在原文件名后追加 `.yaml`。YAML 只接受生成器的 `payload` 字符串列表；Domain 与 IP 专用文件分别按其值域转换，不支持的通配符记入跳过记录。集合 README 保留上游正文和排版，仅替换已同步规则的下载 URL，来源与致谢链接保持原样；README 独立核对，不依赖单份规则是否跳过。
- `merge.py`：将本地已有条件、上游条件及该集合的有效搜索补充合并。归一化完全重复条件，保留顺序；遵循 Core 的同类保守覆盖规则，不跨类型裁剪。无最终策略时不裁剪可能为 REJECT 的 IP／端口；策略冲突交给 Core。
- `sync.py`：使用 UTC 分钟时间协调上述步骤，写入变化文件，删除旧的 `README.upstream.md` 副本，仅将上游 GPL-2.0 许可证同步到根 `LICENSE`，不再创建 `ThirdParty/ios_rule_script`。集合 README 使用上游原文，不另存上游说明副本。

## 转换边界

`DOMAIN`、`DOMAIN-SUFFIX` 使用小写 Nodus 类型；关键词须满足远程正文值域。IPv4／IPv6 CIDR 统一为 `ip-cidr`。不支持的进程、ASN 等条件及非法值写入 `rules/sync-report.json`，未知类型停止本轮发布。`no-resolve` 无 Nodus 对应选项，保留 IP 条件并记录选项移除，不能声称 DNS 语义完全等价。

输出不带策略，导入者选择直连或代理。大集合不拆分；文件生成成功不代表当前 Core 的容量限制或实际加载已验收。当前无策略上下文，跨策略冲突及最终编译裁剪仍由 Core 执行。

合并采用增量并集，手工原文不另存，已合并条件不会仅因上游删除而自动消失。数据、模板或搜索补充未变化时，不重写规则；集合 README 转换后的正文未变化时不写入；生成模板版本升级时会进行一次必要迁移；只改变 README 时保留未变化规则的正文和头注释时间。搜索检查记录可更新，但不据此刷新未变化规则的时间。

## 执行入口

```sh
python3 scripts/sync.py --source .upstream --discover
```

上游 checkout 必须保留完整提交历史（`fetch-depth: 0`），才能正确取得每个文件的 Last commit date；不应使用浅层 HEAD 日期代替。依赖仅 Python 标准库。回归验证入口为 `python3 -m unittest discover -s tests -v`，覆盖多格式隔离、嵌套路径、旧输出迁移、README 仅改 URL 及增量同步。全部转换准备成功后才写入；写入失败不会在 Actions 中提交发布。自动同步仍需仓库允许机器人写入内容。

本项目与上游统一按 [GPL-2.0](../LICENSE) 分发，来源和感谢信息保留；脚本维护直接在 GitHub 完成，全量输出在 Actions 云端生成。

集合 README 以转换 URL 后的上游原文直接覆盖，不保留其中的手工内容。MASTER 和 RELEASE 下载链接均指向本仓库实际同步的 `main`，保留上游段落文字；上游的 Clash 使用说明及统计不代表 Nodus 用法或转换后的数量。旧版 LIST 输出中累积的条件只迁到对应 `.list.yaml`，不混入新恢复的 YAML/TXT 版本。搜索补充保持原有 LIST 作用范围。运行期间远程分支变化导致推送失败时，在临时运行器读取最新 main、重新生成后重试，最多三次；不强推、不回退远程历史。

上游 README 如引用了当前上游已不存在的文件，保留该原始 URL，并记录到 `rules/sync-report.json` 的 `readme_warnings`；不生成虚构规则或猜测替代集合。
