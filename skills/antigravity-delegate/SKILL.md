---
name: antigravity-delegate
description: Delegate a complete work block only when the user explicitly requests agy MCP or Antigravity.
---

# Antigravity delegation

Use the installed `antigravity` MCP. Do not infer delegation from project name, complexity, or available tools. Maintenance of this bridge is not authorization to submit a model task.

1. Check status and resolve `projects(cwd)` for the exact authorized directory. A missing binding is an error, not permission to choose another project.
2. Give one task a clear objective, scope, constraints, and acceptance criteria. Keep one parent task/session per work block. Agy may coordinate parallel subagents within that scope.
3. Submit once with a unique request ID. Watch the same job/cursor; each watch returns within 60 seconds. A disconnect does not cancel a job and is not permission to replay it.
4. After the main job returns, use watch/result to observe the parent conversation. Child reviewer activity is visible only when reflected there. `TASK_BUSY` rejects a continuation; it does not queue it.
5. Verify real diff, test evidence and review findings. Neither idle nor a model's success statement proves delivery. Reconcile uncertain effects before continuing.

## Account recovery

On confirmed quota exhaustion during authorized work, preserve task/job/cursor and check all work is drained. Query enabled accounts and compare Gemini five-hour and weekly quota and reset times. Missing data is unknown. Use at most three eligible candidates in a recovery episode.

`switch_account` may restart the shared Desktop. Never interrupt someone else's task to switch. Require `success=true`, `details.verified=true`, `dispatch_blocked=false`, then reread `account_usage.desktop` for the target identity and positive Gemini five-hour/weekly quota. Recheck project binding before continuing. Do not manually remove a dispatch block or treat connection failure as quota exhaustion.

## Updates and retention

All business modules load per call. Verify `status.runtime.all_business_reload == "per_call"`. Running calls retain their code. Initial frontend installation and schema/transport/environment/dependency changes require appropriate MCP reload; normal business edits do not require restarting Codex or Antigravity.

Terminal jobs with result files are pruned after three days or outside the newest five valid jobs. Archive audit evidence before retention expires. Do not replay a historical request after its record is deleted.

See [handoff guidance](references/prompt-and-handoff.md) and [MCP operations](references/mcp-operations.md).
