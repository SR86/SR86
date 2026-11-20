"""Bounded quota recovery and credential-free execution diagnostics."""
import queue
import threading
import time


class QuotaUnavailable(RuntimeError):
    pass


def checked_quota(read, on_retry=lambda: None):
    # Retry the read only: never retry a model request automatically.
    for attempt in range(2):
        try:
            return read()
        except (TimeoutError, OSError, RuntimeError, queue.Empty):
            if attempt:
                raise QuotaUnavailable('连续两次无法读取额度，已暂停以保护预算；联网恢复后可继续') from None
            on_retry()


def error_category(message):
    """Return fixed labels only. Never persist raw stderr, URLs or headers."""
    value = str(message).lower()
    if any(s in value for s in ('app runtime provisioning service is unavailable', 'registered core setup has not completed', 'sandbox provisioning is incomplete')):
        return 'Codex Windows 沙箱未就绪，需要修复运行环境'
    if any(s in value for s in ('usage limit', 'quota exceeded', 'insufficient_quota', 'rate limit', 'rate_limit', '429')):
        return '额度或请求频率受限'
    if any(s in value for s in ('unauthorized', '401', 'authentication', 'invalid token', 'not logged in')):
        return 'Codex 登录认证失败'
    if any(s in value for s in ('stream disconnected', 'reconnecting', 'connection', 'timed out', 'timeout', 'dns', 'proxy', 'failed to send', 'error sending request')):
        return 'Codex 连接服务失败或正在重试'
    if any(s in value for s in ('sandbox', 'access is denied', 'permission denied')):
        return '执行沙箱或文件权限错误'
    return 'Codex 返回执行错误'


class Diagnostics:
    def __init__(self):
        self.lock = threading.Lock()
        self.counts = {}
        self.errors = []
        self.last_activity = time.monotonic()
        self.last_progress = self.last_activity
        self.last_error = 0
        self.latest_error = None
        self.failed = False

    def error(self, message, allow_generic=True):
        with self.lock:
            category = error_category(message)
            if not allow_generic and category == 'Codex 返回执行错误':
                return
            self.last_error=time.monotonic()
            self.latest_error=category
            if category not in self.errors:
                self.errors.append(category)

    def observe(self, event):
        kind = event.get('type', '')
        # Whitelist event names; never copy tool arguments, responses or IDs.
        if kind in ('thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'item.started', 'item.completed', 'error'):
            with self.lock:
                self.counts[kind] = self.counts.get(kind, 0) + 1
                self.last_activity = time.monotonic()
                if kind not in ('error','turn.failed'):self.last_progress=self.last_activity
                self.failed |= kind == 'turn.failed'
        if kind in ('error', 'turn.failed'):
            error = event.get('error') or {}
            self.error(event.get('message') or (error.get('message', '') if isinstance(error, dict) else error))
        item = event.get('item') or {}
        if kind == 'item.completed' and item.get('type') == 'command_execution' and item.get('exit_code') not in (None, 0):
            # Inspect in memory, retaining only a known infrastructure category.
            self.error(item.get('aggregated_output', ''), allow_generic=False)

    def snapshot(self):
        with self.lock:
            return {'events': dict(self.counts), 'errors': list(self.errors), 'failed': self.failed,
                    'recent_error':self.latest_error if self.last_error>self.last_progress else None}

    def failure(self):
        data = self.snapshot()
        return '；'.join(data['errors']) or 'Codex 未生成有效结果'
