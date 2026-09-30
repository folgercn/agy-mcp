# Prompt and handoff protocol

Use this protocol only after the explicit-user-invocation gate and total-cost decision in `SKILL.md`. This document does not itself authorize delegation. For discretionary allocation, execute an already-known command sequence directly; honor an explicit user assignment to agy.

## Work-unit rule

A work unit is one cohesive outcome with one scope, one acceptance target, and one shared context. Assign one Antigravity conversation to own the full unit from targeted discovery through its final handoff.

- Keep implementation, focused tests, self-review, and evidence collection in the same conversation.
- Keep research, source verification, synthesis, and citations in the same conversation.
- Keep log scoping, filtering, evidence extraction, hypothesis ranking, and read-only next checks in the same conversation.
- New work blocks use new task IDs and concise necessary handoff conclusions; do not grow one conversation indefinitely.
- Split only genuinely independent outcomes. Never run two conversations against the same files or the same unresolved question.
- Let agy choose its internal execution strategy, including subagents. Encourage parallel independent research and coding when useful; agy coordinates ownership, integration and verification and returns one consolidated handoff. Every subagent inherits the same scope, permissions and stopping conditions. Codex remains responsible for overall scope and acceptance.
- A review correction is a continuation of the same work unit. Use the same explicit `AGY_TASK_ID` after the prior turn finishes; the adapter retains its exact conversation ID. Retirement preserves the exact desktop conversation ID.

## Continuation and successor handoff

Use the session ownership rules in SKILL.md to decide whether to reuse or split. On a normal continuation, send only the delta: requested next step, changed constraints, new evidence and exact review corrections. Preserve the existing task ID and settled scope.

When a new successor is justified, save a short handoff in the authorized workspace and reference it from the new task. Include:

- Original and successor task IDs, objective and current authorization boundaries.
- Current worktree/files and revision or relevant state; accepted decisions.
- Completed work and passed checks, with evidence paths and dates where state can drift.
- Remaining steps, unresolved risks, and anything whose outcome must be verified before further action.

The handoff replaces transcript copying; it does not replace reading the current project rules or validating stale state. Finish/reconcile the predecessor before the successor executes against the same change. Report a newly discovered unrelated issue to Codex instead of silently adding it to the current work block.

## Dispatch prompt

Every dispatch must contain only the context needed to execute the unit:

1. Objective and expected deliverable.
2. Acceptance criteria that can be checked.
3. Allowed repository, worktree, files, module, logs, or sources.
4. Forbidden scope and operations.
5. Known evidence and constraints, including applicable project instructions.
6. Required tests or evidence format.

Give the desired outcome and relevant entry points, not a command-by-command remote-control script. Do not perform the complete investigation just to prepare the handoff. Include known useful evidence without duplicating large files that agy can read itself.

State existing authorization rather than asking agy to decide permissions. State unknowns explicitly and require it to stop with a concrete question if an unknown materially changes scope or correctness; routine execution choices remain with agy.

## Mode-specific requirements

### Implement

Require a minimal change, actual changed-file/object list, exact verification outcomes, and explicit unverified items. Preserve unrelated changes. State the current task's authorization for any branch changes, commits, pushes, deployment, production, trading, or account actions. Operational work also needs target-specific completion evidence and stopping conditions; an uncertain mutation outcome must be checked before retrying.

### Research

Require source URLs, publication or retrieval dates when available, claims supported by each source, and a separate section for inference. Prefer primary sources and disclose inaccessible or conflicting sources.

### Logs

Provide the smallest redacted excerpt or an authorized read-only path plus time range. Require exact evidence lines or stable search patterns, ranked hypotheses, and the next read-only checks. Never include secrets, account identifiers, or production mutations.

## Final handoff

The final response must be concise and use these fields:

```text
状态: SUCCESS | PARTIAL | BLOCKED | FAILED
工作块: <one-line objective>
完成内容: <what was actually done>
修改文件/来源/输入范围: <mode-appropriate evidence scope>
验证: <commands, results, URLs, timestamps, or log evidence>
风险与未验证项: <none or explicit list>
建议下一步: <review-ready action or concrete blocker>
```

Return a concise summary and paths to complete artifacts/logs instead of printing the full source, report, or raw logs into the conversation. Preserve failures and unresolved questions in the summary. For code, Codex independently reads the final diff, necessary code, and relevant test evidence. For research, Codex checks material claims against cited sources. For logs, Codex verifies the cited time range and patterns. Do not repeat the entire investigation or all checks without a concrete reason. A `SUCCESS` label or zero exit code is not acceptance; inspect tool errors and `denied_actions` as well as actual results.

## Remediation prompt

Continue the exact conversation ID and send only:

1. Review finding with file/line or evidence pointer.
2. Why it violates the acceptance criteria or creates a concrete risk.
3. Required correction and exact affected scope; change only the named sections and preserve already-passing behavior. Inspect the actual diff.
4. Tests or evidence that must be rerun.

The same task conversation corrects its work and returns the full final handoff again. Do not open a fresh conversation unless the prior conversation is unavailable or the work unit has materially changed.
