# Claude

用于将 Claude／Anthropic 控制的相关域名及官方明确列出的第三方遥测主机分流至代理节点，覆盖 Claude 网页、桌面端、Code 及官方内容服务。采用 Nodus `rules:` 格式，导入后选择已配置的代理节点作为策略。

```text
https://raw.githubusercontent.com/teaoea/nodus-rules/main/rules/Claude/Claude.yaml
```

## 使用边界

- 来源：[官方网络要求](https://code.claude.com/docs/en/network-config)和[桌面端网络要求](https://code.claude.com/docs/en/desktop#network-access-requirements)。头注释记录核对日期和规则数量。
- 收录 Claude／Anthropic 控制的相关域名，以及官方网络要求中用于 Code 遥测事件和错误报告的两个 Datadog 主机；其他第三方登录、验证、字体、脚本、支付和客服域名不收录。
- 第三方遥测使用 `domain` 精确匹配，不扩展至 Datadog 整个域名；这些主机是共享服务，其他应用访问相同主机也可能命中。规则只改变路由，不会启用已关闭的遥测。
- `domain-suffix` 匹配根域及有标签边界的子域；`anthropic.com` 也会覆盖 Anthropic 官网及其他官方服务。
- 按用户要求排除 Apple 域名；自定义 MCP、企业 SSO、外部网站及第三方模型提供商的域名不属于本集范围。
- 规则只声明条件，代理策略由主配置提供；规则命中不代表服务可用，格式核对不等于真实客户端联网验证。
