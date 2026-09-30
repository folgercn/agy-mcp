"""Per-call business entry: no business modules are cached in the MCP host."""
import asyncio
import contextlib
import logging
import sys
from pathlib import Path
from agy_mcp.inspectors import ToolInspector
from agy_mcp.manager_client import ManagerClient
from agy_mcp.quota_reader import QuotaReader
from agy_mcp.usage_tracker import UsageTracker
sys.path.insert(0, str(Path(__file__).parent / "core"))
import agy_service as service
inspector = ToolInspector()
manager_client = ManagerClient()
quota_reader = QuotaReader()
usage_tracker = UsageTracker()
logger = logging.getLogger(__name__)
invoke = service.dispatch

async def list_accounts_tool() -> dict:
    """
    List all registered accounts with rich quota breakdown and weekly limits.
    Allows Codex to view remaining quotas (Gemini 3.1 Pro 5h, Weekly global ceiling,
    Claude Sonnet) across accounts and pick the most suitable account to switch to.
    """
    cap_report = inspector.get_capabilities_report()
    has_manager = cap_report["features"]["multi_account_quota_pool"]

    if not has_manager:
        return {
            "supported": False,
            "message": "未检测到 Antigravity-Manager (~/.antigravity_tools/)，不提供多账号聚合额度池功能。当前以单账号本地模式运行。",
            "capabilities": cap_report,
            "accounts": [],
        }

    # Query manager client first; fallback to local quota_reader if manager API is unavailable
    accounts = await manager_client.list_accounts()
    if not accounts:
        accounts = quota_reader.list_all_accounts()

    usage_summary = usage_tracker.get_summary()

    # Inject task count to each account
    for acc in accounts:
        email = acc.get("email", "")
        stats = usage_tracker.get_account_stats(email) or {}
        acc["task_dispatch_count"] = stats.get("task_count", 0)
        acc["switch_in_count"] = stats.get("switch_in_count", 0)

    return {
        "supported": True,
        "capabilities": cap_report,
        "total_accounts": len(accounts),
        "accounts": accounts,
        "usage_leaderboard": usage_summary.get("leaderboard", []),
    }


async def switch_account_tool(account_or_email: str) -> dict:
    """
    Safely switch active Antigravity account using Antigravity-Manager.
    Passes an account email (e.g. 'target@example.com') or account_id.
    Performs safe credential rotation with official app restart (/Applications/Antigravity.app).
    """
    # 1. Capture current active email BEFORE switching
    before_active = await manager_client.get_current_account()
    before_email = before_active.get("email") if before_active else None
    if not before_email:
        before_local = quota_reader.get_current_active_identity()
        before_email = before_local.get("current_email")

    from agy_mcp.switching import guarded_switch
    success, msg, details = await guarded_switch(manager_client, account_or_email, invoke)
    if success:
        target_email = details.get("email") or account_or_email
        target_id = details.get("account_id")

        if target_email:
            await usage_tracker.record_switch(
                from_email=before_email,
                to_email=target_email,
                account_id=target_id,
                reason="codex_instructed_switch",
            )
    return {
        "success": success,
        "message": msg,
        "details": details,
    }


async def account_usage_tool() -> dict:
    """
    Read the active signed-in account's identity, subscription plan, and every quota bucket
    from Antigravity-Manager, enriched with multi-account inspection report.
    """
    current = await manager_client.get_current_account()
    if current:
        usage = {
            "active_email": current.get("email"),
            "account_id": current.get("account_id"),
            "name": current.get("name"),
            "subscription_tier": current.get("quota", {}).get("subscription_tier"),
            "quota": current.get("quota"),
            "raw_quota": current.get("raw_quota"),
        }
    else:
        try:
            usage = await invoke("account_usage", {})
        except Exception as e:  # noqa: BLE001
            usage = {"error": str(e), "message": "Failed to read usage from both Manager and desktop RPC"}

    # Manager selection can differ from the actual Desktop credential.
    try:
        usage["desktop"] = await invoke("account_usage", {})
    except Exception as exc:
        usage["desktop"] = {"status": "UNKNOWN", "error_type": type(exc).__name__}
    cap_report = inspector.get_capabilities_report()
    usage["capabilities_report"] = cap_report
    usage["usage_summary"] = usage_tracker.get_summary()
    return usage


async def account_leaderboard_tool() -> dict:
    """
    Get comprehensive usage statistics, rankings, and distribution across all accounts.
    Shows who is used most/least, total task distribution, and switch counts.
    """
    return usage_tracker.get_summary()


async def tool_status_tool() -> dict:
    """
    Check health and runtime availability of Antigravity-Manager.
    Informs whether multi-account quota reading and safe switching are currently active.
    """
    is_avail, avail_msg = await manager_client.is_available()
    report = inspector.get_capabilities_report()
    report["manager_api_status"] = {
        "available": is_avail,
        "message": avail_msg,
        "port": manager_client.get_port(),
    }
    return report


async def submit_tool(
    task_id: str,
    prompt: str,
    cwd: str,
    request_id: str,
    mode: str = "implement",
    timeout_seconds: float = 600,
    ack_uncertain: bool = False,
) -> dict:
    """
    Submit an authorized work block, or continue a finished task's SAME desktop conversation.
    Supply exact scope and acceptance criteria in prompt. Idempotent per task_id/request_id.
    Returns immediately with a job_id; follow with one watch call.
    """
    active_email = ""
    with contextlib.suppress(Exception):
        active_info = quota_reader.get_current_active_identity()
        active_email = active_info.get("current_email") or ""

    if active_email:
        try:
            await usage_tracker.record_task(
                email=active_email,
                task_id=task_id,
                prompt_preview=prompt,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to record task dispatch: %s", e)

    try:
        return await invoke(
            "submit",
            {
                "task_id": task_id,
                "prompt": prompt,
                "cwd": cwd,
                "request_id": request_id,
                "mode": mode,
                "timeout_seconds": timeout_seconds,
                "ack_uncertain": ack_uncertain,
            },
        )
    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "quota" in err_str or "exhaust" in err_str:
            logger.warning("Task execution hit quota limit / 429: %s", e)
            if active_email:
                await usage_tracker.record_429(active_email)
        raise


async def status_tool(job_id: str | None = None) -> dict:
    """
    Read a job or shared adapter state without submitting work. Does not launch the desktop.
    - When job_id is provided: inspects that job's conversation readiness (readiness: ready/busy/unknown,
      unfinished_steps count, blocking_job_ids, can_continue boolean).
    - When job_id is omitted: checks local adapter queues, active tasks and concurrency limits.
    """
    res = await invoke("status", {"job_id": job_id})
    if not job_id and isinstance(res, dict):
        with contextlib.suppress(Exception):
            current_acc = await manager_client.get_current_account()
            if current_acc:
                res["active_account"] = {
                    "email": current_acc.get("email"),
                    "gemini_5h_fraction": current_acc.get("quota", {}).get("gemini_5h_fraction"),
                    "gemini_weekly_fraction": current_acc.get("quota", {}).get("gemini_weekly_fraction"),
                }
    return res

HANDLERS = {name.removesuffix("_tool"): value for name, value in list(globals().items()) if name.endswith("_tool")}
async def dispatch(operation, arguments, on_events=None, on_status=None):
    if operation in HANDLERS:
        result = await HANDLERS[operation](**arguments)
    else:
        result = await invoke(operation, arguments, on_events, on_status)
    if operation == "status" and isinstance(result, dict):
        result.setdefault("runtime", {})["all_business_reload"] = "per_call"
    return result

if __name__ == "__main__":
    service.init()
    service.dispatch = dispatch
    try:
        asyncio.run(service.call_from_stdio())
    except Exception as exc:
        service.send_frame("error", {"type": type(exc).__name__, "message": service.desktop.clean(str(exc))})
