# Google

## 前言

分流规则是互联网公共服务的域名和IP地址汇总，所有数据均收集自互联网公开信息，不代表我们支持或使用这些服务。

> ![中华人民共和国 People's Republic of China](../../assets/china-label.svg)
>
> 请通过合法的互联网出入口信道访问规则中的地址，并确保在使用过程中符合相关法律法规。

## 规则统计

最后更新时间：2026-10-30 05:43 UTC

各类型规则统计：

| 类型 | 数量(条) |
| ---- | ---- |
| domain | 1 |
| domain-keyword | 5 |
| domain-suffix | 684 |
| ip-cidr | 5 |
| process-name | 6 |
| total | 701 |

## Nodus Core

### 配置建议

- Google.yaml 单独使用。

### 规则链接

#### MASTER分支 (每日更新)

```text
https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Google/Google.yaml
```

#### MASTER分支 CDN (每日更新)

```text
https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Google/Google.yaml
```

#### MASTER分支 GHProxy (每日更新)

```text
https://ghproxy.com/https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Google/Google.yaml
```

## 子规则/排除规则

当前分流规则，已包含以下子规则，除非特殊需求否则不建议重复引用：

| 子规则 |  |  |
| ---- | ---- | ---- |
| GoogleDrive | GoogleSearch | GoogleVoice |

当前分流规则，已排除以下规则：

| 排除规则 |  |
| ---- | ---- |
| YouTube | YouTubeMusic |
