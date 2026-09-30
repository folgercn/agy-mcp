"""Serialize account restarts with dispatch; verify native identity and quota."""
import asyncio
import fcntl
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'core'))
import agy_service as service
import agy_desktop as desktop


def verify_native(usage, email):
    actual = usage.get('account', {}).get('email')
    if not isinstance(actual, str) or actual.lower() != email.lower():
        return False, 'DESKTOP_IDENTITY_MISMATCH'
    windows = {}
    groups = usage.get('quota', {}).get('groups')
    for group in groups if isinstance(groups, list) else []:
        if 'gemini' not in str(group.get('displayName', '')).lower():
            continue
        buckets = group.get('buckets')
        for bucket in buckets if isinstance(buckets, list) else []:
            windows[bucket.get('window')] = bucket.get('remainingFraction')
    for window in ('5h', 'weekly'):
        value = windows.get(window)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return False, 'QUOTA_UNKNOWN'
        if value <= 0:
            return False, 'QUOTA_EXHAUSTED'
    return True, 'VERIFIED'


def parse_inventory(response):
    # Protobuf JSON omits empty maps: successful {} means no conversations.
    # Only that exact empty response gets the default; malformed/error payloads fail closed.
    if not isinstance(response, dict):
        raise RuntimeError('DESKTOP_INVENTORY_UNKNOWN')
    if response == {}:
        return {}
    if 'error' in response:
        raise RuntimeError('DESKTOP_INVENTORY_UNKNOWN')
    summaries = response.get('trajectorySummaries')
    if not isinstance(summaries, dict) or any(
        not isinstance(cid, str) or not cid or not isinstance(item, dict)
        for cid, item in summaries.items()
    ):
        raise RuntimeError('DESKTOP_INVENTORY_UNKNOWN')
    return summaries


def acquire_barrier():
    service.init()
    handles = []
    try:
        # Same locks as the old and new bridge, plus all shell execution slots.
        for path in [service.ROOT / 'bridge.lock'] + [desktop.slot_path(i, 'execution') for i in range(4)]:
            handle = path.open('a'); handles.append(handle)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in service.JOBS.glob('*/job.json'):
            record = desktop.read(path, {})
            if record.get('status') not in service.TERMINAL:
                raise RuntimeError('JOBS_NOT_DRAINED')
        for path in (desktop.STATE / 'queue').glob('*.json'):
            record = desktop.read(path, {})
            if record.get('pid') and desktop.alive(record['pid']):
                raise RuntimeError('QUEUE_NOT_DRAINED')
        backend = desktop.Desktop()
        # Covers desktop work started manually or by other callers as well.
        summaries = parse_inventory(backend.rpc('GetAllCascadeTrajectories', {}))
        if any(x.get('status') != desktop.IDLE for x in summaries.values()):
            raise RuntimeError('DESKTOP_HAS_ACTIVE_OR_UNKNOWN_WORK')
        for path in (desktop.STATE / 'tasks').glob('*.json'):
            record = desktop.read(path, {})
            cid = record.get('conversation_id')
            # Historical mappings from other accounts are not current Desktop sessions.
            if cid in summaries and desktop.conversation_state(backend.trajectory(cid))['readiness'] != 'ready':
                raise RuntimeError('DESKTOP_CONVERSATION_NOT_IDLE')
        return handles
    except BaseException:
        for handle in reversed(handles):handle.close()
        raise


async def guarded_switch(manager, target, invoke):
    try:
        handles = await asyncio.to_thread(acquire_barrier)
    except Exception as exc:
        # No restart on active/unknown work or a busy cross-process lock.
        return False, '切号未执行：任务尚未排空或状态未知。', {'error': str(exc) if type(exc) is RuntimeError and str(exc) in ('JOBS_NOT_DRAINED','QUEUE_NOT_DRAINED','DESKTOP_INVENTORY_UNKNOWN','DESKTOP_HAS_ACTIVE_OR_UNKNOWN_WORK','DESKTOP_CONVERSATION_NOT_IDLE') else type(exc).__name__}
    marker = service.ROOT / 'dispatch-block.json'
    try:
        desktop.save(marker, {'reason': 'ACCOUNT_SWITCH_UNVERIFIED', 'created_at': time.time()})
        success, message, details = await manager.switch_account(target)
        if not success:
            return False, message, dict(details, verified=False, dispatch_blocked=True)
        email = details.get('email')
        if not email:
            return False, '目标账号身份缺失，禁止派单。', {'verified': False, 'dispatch_blocked': True}
        reason = 'DESKTOP_UNAVAILABLE'
        for attempt in range(6):
            try:
                usage = await invoke('account_usage', {})
                verified, reason = verify_native(usage, email)
                if verified:
                    marker.unlink(missing_ok=True)
                    return True, 'Desktop 实际账号与目标一致，Gemini 五小时和周额度均可用。', dict(details, verified=True, native_verification=usage, dispatch_blocked=False)
            except Exception:
                reason = 'DESKTOP_UNAVAILABLE'
            if attempt < 5:await asyncio.sleep(2)
        return False, '切号后实际身份或额度未通过验证，禁止派单。', {'verified': False, 'error': reason, 'dispatch_blocked': True}
    finally:
        for handle in reversed(handles):handle.close()
