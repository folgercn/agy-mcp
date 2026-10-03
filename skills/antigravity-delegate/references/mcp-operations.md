# MCP bridge operations

Server: `antigravity`, stdio `agy-mcp --transport stdio`, dependencies declared in `pyproject.toml`. Config is in `~/.codex/config.toml`; existing tool approval policies are unchanged. Desktop must be running and signed in.

## Normal MCP workflow

`submit` requires one existing exact single-folder project environment. The
connector verifies the native startup environment ID and sole workspace URI
before sending a model message; missing receipts cannot be bypassed with
`ack_uncertain`. No automatic environment registration or default fallback.

`reconcile(job_id)` archives an owned stale slot after terminal related jobs,
known results, dead processes and live idle/zero unfinished proof. It does not
retry, cancel, delete history or acknowledge uncertain execution. Retries
recheck current state and reuse the preserved archive.

Live trajectory pagination retries up to three snapshots, with a shared
64-page/100000-step read budget. A paginated IDLE result rechecks its terminal
boundary; unknown or incomplete recovery proof still blocks reconciliation.
`TRAJECTORY_UNSTABLE` does not cancel an in-flight turn: retain its uncertain
record and observe the same job/conversation, never resubmit or clear its slot.

Discover server `antigravity` in the current tool catalog and invoke its `status` tool. Disk configuration or an independent SDK client proves neither current-task tool loading nor desktop model responsiveness. `status` checks bridge state only; a completed minimal submit/wait/result checks a model round trip when requested. Tools missing from the catalog require a supported host reload or reopening Codex; do not promise that a new message automatically loads them. Keep other tasks running unless a restart is authorized.

Example tool arguments (use returned IDs and cursors; these are not shell commands):

1. `submit`: `{"task_id":"repo-issue123","request_id":"implementation-1","cwd":"/absolute/worktree","mode":"implement","prompt":"Objective, authorized files/actions, stop conditions and acceptance evidence","timeout_seconds":600}`. Modes: implement, research, logs. Timeout includes queue time. Save the returned `job_id` immediately. If TASK_BUSY is returned, observe the existing job; do not create another task to bypass it.
2. `watch`: `{"job_id":"<returned job_id>","cursor":0,"timeout_seconds":1800}`. Hold one subscription at a time; each call returns model-visible activity within 60 seconds. On `progress_update`, read `activity` and immediately resume the SAME job using `resume.cursor`; do not submit/message again. Save the byte cursor from each fully received notification. On disconnect resume the SAME job with the last received cursor (or 0 if none was received); replay can duplicate events, never execution. Do not use a cursor merely observed on disk as proof of delivery. If watch is unavailable, check status at 180–300 second intervals.
3. On completed/failed/cancelled/worker_lost, drain unread events while `has_more`, then `result`: `{"job_id":"<same job_id>","offset":0,"max_chars":8000}`. Follow `next_offset` until null. Inspect outcome, errors, issues and actual evidence; completed is a returned turn, not accepted delivery.
4. After a finished turn, `message`: `{"task_id":"repo-issue123","request_id":"review-fix-1","prompt":"Fix only these findings; preserve passed content. Evidence paths: ...","timeout_seconds":600}`. Save its NEW job_id and repeat watch/result. task_id retains the same conversation and cwd/mode. A new work block gets a new task_id. If the submit response was lost, repeat the original request_id with identical input only to recover the SAME job; this never reruns it. If that job ends uncertain, first inspect and reconcile its effects. An authorized continuation then uses a NEW request_id and `ack_uncertain:true` on the SAME task_id; never create a different task_id to bypass uncertainty.
5. Read-only check: `status` with `{}` gives active_tasks, queued and execution_limit; `{"job_id":"<job_id>"}` checks one job. To stop an authorized own job use `cancel` with that job_id, then wait/result. cancel_requested is not cancellation confirmation. Inspect uncertain effects before setting `ack_uncertain:true` on any continuation; it is not a retry flag.

The bridge runs in its own `.mcp-venv` (ARM64 Python 3.11). Commands inside a delegated project use that project's verified venv. No CLI worker pool or per-task desktop launch is needed; concurrency defaults to 2 and supports 1–4 shared slots.

## Complete upstream output

`wait.events` contains `upstream_payload` events. These carry complete upstream stream messages (including end/error messages), full trajectory replies used for recovery/finalization, and the bridge final result. Compact `progress` and `efficiency` events are supplementary; never substitute them for inspecting the actual upstream data.

Each payload has a `payload_id`, `source`, `offset`, `total_chars`, `final` and `data`. Group fragments by payload_id, concatenate data in offset order, verify the final length, then JSON-decode. Offsets count Unicode characters; the outer wait cursor counts bytes in the event file. Preserve every fragment across wait pages, including terminal pages with has_more. Fragmentation changes transport size only, not field selection; unknown fields, complete combinedOutput, command parameters, output text and errors are retained. Stream data wraps the original decoded message with its frame flags. Only auth tokens/credential values are redacted. Do not infer absence of an error from the short summary when raw output says otherwise.

Full payloads can be large and repeat history when the backend returns a snapshot. This is intentional transparency; consumers may summarize for the user after reading, but the bridge must not discard fields or silently truncate. The final bridge_result payload includes all result fields, even those absent from the convenience result response. Keep draining until both the job is terminal and has_more is false.

Already-running workers keep their loaded adapter code; full forwarding applies to new calls without restarting Antigravity. Do not stop another task to change its output format.

## Job lifecycle

One desktop task ID keeps one conversation; each submitted turn has a distinct job_id. A request_id uniquely identifies one submission for that task. Retrying identical input with the same request_id returns the same job, including after reconnect. Different input with an old request_id is rejected. Never use a generic permanent task ID for unrelated work.

Submit returns immediately. Watch accepts a requested timeout up to 3600 seconds but caps each subscription at 60 seconds for model-visible progress; configure the host tool timeout above this maximum (3660 seconds). Legacy wait accepts at most 50 seconds and is for explicit evidence reads, not a monitoring loop. The cursor belongs to that job's event file. Terminal jobs can still have unread events: drain has_more and retrieve result. Long responses paginate via next_offset. Status includes worker status plus phase: queued_or_preparing, executing, or terminal. A running worker is not necessarily executing a model task yet.

Message reuses a completed task's saved cwd/mode/conversation. Active-task messages return TASK_BUSY rather than injecting an interrupt. This first bridge version does not expose active-turn steering.

Cancel writes a job-specific request. A queued task exits without sending a prompt; an executing task attempts cancellation of its own desktop conversation and records confirmation. Wait/result are authoritative. A worker lost unexpectedly is uncertain; inspect the desktop task before further mutation. No shared desktop process is killed.

## Durable files

`.desktop/mcp/jobs/<job_id>/` contains job.json, request.json, events.jsonl, result.json, worker.log and an optional cancel marker. Files are private to the user. Request bodies are passed through files rather than process arguments. Submitted workers continue across MCP client disconnects. These durable bridge job files currently require manual retention management; adapter logs have separate retention. Do not delete active job directories.

The bridge does not claim that notifications automatically wake Codex. Codex must hold watch or explicitly read events to consume updates. Efficiency snapshots appear in wait and result; one-minute adapter snapshots are not a substitute for final diff/test acceptance.

## Concurrency

The shared desktop adapter defaults to 2 concurrent managed tasks, with a hard configuration range of 1–4. Set `max_concurrency` in `.desktop/config.json` after draining managed jobs. Slot zero retains the legacy lock for already-running callers. `status.active_tasks` lists all execution slots; `active` remains a compatibility view of the first task. Waiting tickets exclude executing jobs. Independent task IDs keep separate conversations; never run two tasks editing the same files without an explicit coordination boundary. This limit does not control manually started desktop conversations.

## Recovery evidence and host loading

`recovery.error_history` preserves each observed failed step; `exact_retry_succeeded` links to a later DONE/exit 0 command with identical commandLine, cwd and shell. It proves that retry only, not repair of side effects or task acceptance. Changed commands, unknown tools and missing identity stay unverified. `unresolved_issue_indices` means no exact recovery evidence; it does not alone prove the current task is blocked. Check fresh status and subsequent full output before reporting a blocker. Historical `issues` and `REVIEW_REQUIRED` remain review evidence even when exact retries succeeded.

`status`, `wait`, final `result`, and progress events expose recovery for new workers. Old running workers retain their loaded code; missing recovery fields mean unknown, so inspect saved full output. Completed job evidence is read from that job's result, not another turn of the same task.

`logging/setLevel` is session scoped. Upstream notifications use info level; a higher threshold suppresses delivery without advancing the cursor, leaving raw data available via events. Save only fully received notification cursors; after an ambiguous disconnect replay from the last confirmed cursor. No consumer acknowledgment is inferred from a server-side send.

Disk config, a fresh SDK process, and the current Codex host are separate checks. Updating tool_timeout_sec or the stable frontend does not prove an existing connection reloaded; business-module updates are loaded by the next call after the new frontend is active. Verify a held host call beyond 65 seconds; if a connection still uses the old timeout, retain job/cursor and report pending host reload. Never restart the shared desktop or other tasks to activate bridge changes.

A generator error followed by a nonempty DONE planner response is marked `generation_resumed`, linked to that response step. This proves response generation resumed within the same turn, not that failed tools recovered. Only generator errors after the last completed response remain terminal errors; all historical error entries remain visible.

## Updating business code without restarting Codex

Keep `agy_mcp/server.py`, public tool names/arguments and host config stable. Put ordinary behavior changes in `agy_service.py` (jobs, watch, result, dispatch), `agy_desktop.py` (desktop execution) or `agy_account.py` (account shaping). The resident frontend launches a fresh process per call, exchanges internal version-1 JSON frames, and never imports these business modules. Fresh helpers bypass stale bytecode caches, so same-size rapid edits are read too.

A call or detached job already running uses its loaded code through completion. Updates do not restart, cancel or replay it. The next call sees updated business files. Replace each edited file atomically after validation; changes spanning modules must remain compatible during rollout. Syntax/import failures surface as tool errors, never silently fall back to stale code; repair the file and retry read-only calls, or reconcile the same job/request_id for mutations.

For watch, the helper sends raw event pages and waits for the frontend delivery/filter acknowledgment before advancing its cursor. Disconnect terminates only that subscription helper, leaving the detached job untouched. Preserve the last fully received cursor for replay.

This split requires a one-time host reload to replace the previous monolithic frontend. Verify global status contains `runtime.business_reload: per_call`. Thereafter routine business edits need no Codex restart; changing the public tool schema, stable transport or host configuration remains an exceptional reload case. No new port, daemon, credential, configuration item or permission is introduced.
