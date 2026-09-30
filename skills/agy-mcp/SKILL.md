---
name: agy-mcp
description: 用户明确说“agy MCP”“agy mcp”“用 agy”“调用 agy”或“Antigravity MCP”时的快捷入口，直接定位已安装的 antigravity MCP 和委派规则。仅用于明确请求的调用或相关问题，不因普通开发任务自动委派。
---

# agy MCP 快捷入口

“agy MCP”就是本机已配置的 **antigravity** MCP，不是需要另找的插件、网站或桌面自动化工具。

1. 直接读取同级 `../antigravity-delegate/SKILL.md`，遵守其中的显式授权、总成本分配、项目绑定和验收规则；不要重复搜索其他 Skill 或扫描仓库来猜它在哪里。若该文件不存在，再定向查找或报告缺失。
2. 工具目录按服务名 `antigravity` 定向定位；常见工具名为 `mcp__antigravity__status`、`projects`、`submit`、`watch`、`result`，以实际工具目录为准。已发现就直接使用；不可调用时明确说明，不反复全局搜索。
3. 真正调用前按主 Skill 检查 status；派单前确认实际 cwd 的项目绑定。首次派单读取 `../antigravity-delegate/references/prompt-and-handoff.md`，具体参数查 `../antigravity-delegate/references/mcp-operations.md`。
4. 仅询问、检查或修改 agy 的配置/规则不代表授权提交模型任务。用户明确要求使用 agy 执行工作时才委派；同一工作块续用已有授权，不每轮重新确认。
5. 不需要桌面控制、屏幕共享或鼠标键盘操作。项目未登记时报告目录问题，由用户在 Antigravity 手动处理，不自动操作界面或改建项目。
6. 确认 agy 额度不足后，已授权自主选择和切换有额度的账号。先保留原 task/job/cursor、核实任务停止和既有操作结果，不能打断其他任务；查询 list_accounts 选择启用且 Gemini 五小时与周额度均可用的候选，调用 switch_account。必须验证 Desktop 实际账号与目标一致、额度可用，再检查项目绑定并续发。Manager 返回成功不等于验证成功；验证失败禁止派单。每次恢复最多尝试三个不同候选；无候选、无法验证或仍有任务占用时报告并暂停。连接故障不能当成额度不足。完整规则见主 Skill 的 “Quota exhaustion: autonomous account selection and verified switching”。

此入口只负责快速定位，完整执行规则以 antigravity-delegate 为准。不修改 MCP 配置、工具接口或项目 AGENTS。
