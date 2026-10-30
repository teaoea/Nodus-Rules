# CloudGlobal

## 前言

分流规则是互联网公共服务的域名和IP地址汇总，所有数据均收集自互联网公开信息，不代表我们支持或使用这些服务。

![请通过中华人民共和国合法的互联网出入口信道访问规则中的地址，并确保在使用过程中符合相关法律法规。](../../../assets/china-network-notice-inline.svg)

## 规则统计

最后更新时间：2026-10-30 17:40 UTC

各类型规则统计：

| 类型 | 数量(条) |
| ---- | ---- |
| domain-suffix | 19 |
| ip-cidr | 2842 |
| total | 2861 |

## Nodus Core

### 配置建议

- CloudGlobal_Classical.yaml 单独使用。
- CloudGlobal.yaml、CloudGlobal_IP.yaml 共同使用。

### 规则链接

#### MASTER分支 (每日更新)

```text
https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal.yaml
```

```text
https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal_IP.yaml
```

```text
https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal_Classical.yaml
```

```text
https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal_IP.yaml
```

#### MASTER分支 CDN (每日更新)

```text
https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Cloud/CloudGlobal/CloudGlobal.yaml
```

```text
https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Cloud/CloudGlobal/CloudGlobal_IP.yaml
```

```text
https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Cloud/CloudGlobal/CloudGlobal_Classical.yaml
```

```text
https://cdn.jsdelivr.net/gh/teaoea/Nodus-Rules@main/rules/Cloud/CloudGlobal/CloudGlobal_IP.yaml
```

#### MASTER分支 GHProxy (每日更新)

```text
https://ghproxy.com/https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal.yaml
```

```text
https://ghproxy.com/https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal_IP.yaml
```

```text
https://ghproxy.com/https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal_Classical.yaml
```

```text
https://ghproxy.com/https://raw.githubusercontent.com/teaoea/Nodus-Rules/main/rules/Cloud/CloudGlobal/CloudGlobal_IP.yaml
```

## 子规则/排除规则

当前分流规则，已包含以下子规则，除非特殊需求否则不建议重复引用：

| 子规则 |  |  |
| ---- | ---- | ---- |
| AkamaiCloud | AmazonCloud | HiNet |
