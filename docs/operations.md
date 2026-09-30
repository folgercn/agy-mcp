# 运行与维护

## 状态与升级

默认 Desktop 状态：`~/.local/share/agy-mcp/state`；统计：`~/.local/share/agy-mcp/data`。
旧版本升级可在 MCP 环境中设置 `AGY_DESKTOP_STATE` 指向原状态目录，保留 job、会话映射与锁。

业务更新在下一次调用生效。`status.runtime.all_business_reload = "per_call"` 表示当前连接已启用统一加载入口。不要为更新而打断任务。

## 传输

- 推荐：`agy-mcp --transport stdio`。
- SSE：`agy-mcp --transport sse`，默认 `127.0.0.1:8765`。
- Unix socket：`agy-mcp --transport socket`，默认数据目录下 `run/antigravity_mcp.sock`。

网络模式应设置 `AGY_MCP_API_KEY` 并保持本机绑定；不要将无认证接口暴露到公网。配置详情见 `agy_mcp/config.py` 与 `agy-mcp --help`。

## 额度与切号

查询列表无需逐个切号。额度和重置时间是 Manager 保存的快照，不代表强制刷新上游。
成功切号要求 `success=true`、`details.verified=true`、`dispatch_blocked=false`，再用 `account_usage.desktop` 复验目标身份及 Gemini 五小时/周额度。
验证失败保留派单保护；不要手动删除保护标记。Desktop 启动慢可能导致核验超时，不应直接重发任务。

## 保留与备份

启动业务调用时自动检查历史 job：有 `result.json` 的终态记录，超过 3 天或位于全部有效 job 最新 5 项之外将被删除。`worker_lost` 也属于终态。没有结果文件的记录与非终态任务不清理。

这是自动删除策略，并不保证永久幂等或历史审计。清理后的旧请求不要重试；需要保留证据时，在更新或运行前另行归档状态目录。代码仓库不包含这些备份。

## 故障报告

提供 Python/Desktop 版本、工具名、脱敏错误码、job 状态和是否启用按调用加载即可。不要公开 API key、账号 JSON、完整提示词或事件正文。
