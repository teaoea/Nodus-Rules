# ChatGPT

用于将 ChatGPT 网页及客户端相关域名分流至代理节点，覆盖登录、静态资源、文件域名和 OpenAI 官方网络建议列出的第三方依赖。规则头注释记录来源、核对日期、条目总数及各类型数量。

```text
https://raw.githubusercontent.com/teaoea/nodus-rules/main/rules/ChatGPT/ChatGPT.yaml
```

## 使用边界

- `domain` 精确匹配域名；`domain-suffix` 匹配根域及有标签边界的子域。官方通配条目已转换为后缀规则，并去除被覆盖的重复条件。
- 官方来源：[ChatGPT 网络建议](https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web-and-apps)。这些是网络放行建议，本集将其转换为代理匹配条件。
- 第三方共享域名的匹配不区分调用应用，也可能代理其他应用访问相同域名的流量；`openai.com` 后缀还会覆盖其他 OpenAI 服务。
- 本集不包含动态语音服务器 IP，无法保证按 IP 连接的 UDP 语音流量命中；ChatGPT 语音的额外网络要求见官方来源。
- 规则命中不代表服务可用；仍取决于节点、网络、账户及客户端环境。本地格式核对不等于真实 App 或外部服务验证。
