# Imgur

<!-- upstream-sync:Imgur.yaml:start -->
## Imgur.yaml 上游同步

采用 Nodus `rules:` 格式，导入后按需要选择策略；正文不附带策略。

```text
https://raw.githubusercontent.com/teaoea/nodus-rules/main/rules/Imgur/Imgur.yaml
```

来源：[blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script/blob/master/rule/Clash/Imgur/Imgur.list)；[上游说明原文](README.upstream.md)。转换及合并由本项目执行，上游原文按 GPL-2.0 分发，许可与来源记录见 [同步说明](../../scripts/README.md)。

转换后共 2 条；未转换 0 条，详见 [转换记录](../sync-report.json)。不支持的条件不作等价替换；`no-resolve` 无对应选项，IP 条件保留但此选项不保留。

大集合保持单文件，当前 Core 的 8 MiB 正文及 100,000 条限制可能导致拒绝加载；容量支持待 Core 完成。含后缀／关键词的集合用于 `reject` 时这些条目会被 Core 忽略。
<!-- upstream-sync:Imgur.yaml:end -->
