"""Read Codex quota without starting model turns; send self-only PushPlus notices."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import ctypes
import importlib.util

import keyring

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'state.json'
SERVICE = 'CodexQuotaNotifier.PushPlus'


def current_package_family():
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    api = ctypes.WinDLL('kernel32').GetCurrentPackageFamilyName
    api.argtypes = [ctypes.POINTER(wintypes.UINT), wintypes.LPWSTR]
    api.restype = wintypes.LONG
    length = wintypes.UINT()
    status = api(ctypes.byref(length), None)
    if status != 122 or not 0 < length.value < 32768:
        return None
    buffer = ctypes.create_unicode_buffer(length.value)
    return buffer.value if api(ctypes.byref(length), buffer) == 0 else None


def codex_environment(environ=None, system_proxies=None):
    """Use the already-enabled local system proxy for CLI children only."""
    env = dict(os.environ if environ is None else environ)
    # Request the registered backend only after Windows confirms package identity.
    # This flag cannot grant identity: Codex independently authenticates the caller.
    family = current_package_family()
    if family == 'OpenAI.Codex_2p2nqsd0c76g0':
        env['CODEX_WINDOWS_REGISTERED_CORE'] = '1'
        env['CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY'] = family
    if any(env.get(key) for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')):
        return env
    proxies = urllib.request.getproxies() if system_proxies is None else system_proxies
    candidate = proxies.get('http') or proxies.get('https')
    if not candidate:
        return env
    try:
        proxy = urlsplit(candidate)
        if proxy.hostname not in ('127.0.0.1', 'localhost', '::1') or not proxy.port or proxy.username or proxy.password:
            return env
        host = '['+proxy.hostname+']' if proxy.hostname == '::1' else proxy.hostname
        address = 'http://'+host+':'+str(proxy.port)
    except ValueError:
        return env
    env['HTTP_PROXY'] = env['HTTPS_PROXY'] = address
    bypass = env.get('NO_PROXY', env.get('no_proxy', ''))
    env['NO_PROXY'] = env['no_proxy'] = ','.join(filter(None, (bypass, '127.0.0.1,localhost,::1')))
    return env


def read_limits(timeout=35):
    config_path = ROOT / 'runtime.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    exe = config.get('codex_path') or shutil.which('codex')
    # Scheduled tasks do not inherit the desktop app's temporary PATH entries.
    if not exe:
        candidates = list(Path('C:/Program Files/WindowsApps').glob('OpenAI.Codex_*/app/resources/codex.exe'))
        if candidates:
            exe = str(max(candidates, key=lambda p: p.stat().st_mtime))
    if not exe:
        raise RuntimeError('CodexExecutableUnavailable')
    proc = subprocess.Popen([exe, 'app-server', '--stdio'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW,
                            env=codex_environment())
    messages = queue.Queue()

    def read():
        for line in proc.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put(None)

    threading.Thread(target=read, daemon=True).start()

    def send(obj):
        proc.stdin.write(json.dumps(obj) + '\n')
        proc.stdin.flush()

    def result(i):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                msg = messages.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError('QuotaReadTimeout') from None
            if msg is None:
                raise RuntimeError('QuotaReaderExited')
            if msg.get('id') == i:
                if 'error' in msg:
                    raise RuntimeError('QuotaReadRejected')
                return msg['result']
        raise TimeoutError('QuotaReadTimeout')

    try:
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'quota_notifier', 'version': '1.0'}}})
        result(1)
        send({'method': 'initialized', 'params': {}})
        send({'id': 2, 'method': 'account/rateLimits/read', 'params': {}})
        return result(2)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        proc.stdin.close()
        proc.stdout.close()


def windows(result):
    buckets = result.get('rateLimitsByLimitId') or {'codex': result.get('rateLimits')}
    found = []
    for bucket_id, bucket in buckets.items():
        if not bucket:
            continue
        for name in ('primary', 'secondary'):
            w = bucket.get(name)
            if w and w.get('windowDurationMins') == 300:
                found.append({'bucket': bucket_id, 'window': name,
                              'usedPercent': w['usedPercent'], 'resetsAt': w['resetsAt']})
    return found


def store():
    spec=importlib.util.spec_from_file_location('quota_store',ROOT/'quota_store.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.Store(ROOT/'quota_state.sqlite3')


def tracked_windows(result):
    try:seed=json.loads(STATE.read_text(encoding='utf-8'))
    except (OSError,ValueError):seed={}
    return store().observe(windows(result),seed=seed)


def notify(title, content, dedupe_key=None):
    if dedupe_key:
        return store().send_once(dedupe_key,lambda:_deliver(title,content))
    return _deliver(title,content)


def _deliver(title, content):
    token = keyring.get_password('CodexQuotaNotifier.Gotify', 'app_token')
    if not token:
        raise RuntimeError('PushTokenMissing')
    body = json.dumps({'title': title, 'message': content,
                       'priority': 8}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:8769/message', data=body,
                                 headers={'Content-Type': 'application/json', 'X-Gotify-Key': token})
    # Do not follow redirects carrying a credential-bearing request.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError('PushRejected')
    # Accepted by local server does not establish phone delivery.
    return 'accepted'


def save_state(data):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, STATE)


def check():
    current = tracked_windows(read_limits())
    if not current:
        raise RuntimeError('FiveHourWindowUnavailable')
    save_state({w['bucket']+':'+w['window']:w for w in current})
    database=store()
    for event,w in database.pending_refreshes():
        remaining = max(0, 100 - w['usedPercent'])
        plan = (ROOT / 'next_plan.txt').read_text(encoding='utf-8').strip()
        notify('Codex 五小时额度已恢复',
                   f"额度池：{w['bucket']}\n当前剩余：{remaining}%\n"
                   f"时间：{dt.datetime.now().astimezone().isoformat(timespec='minutes')}\n\n"
                   f"下一步计划：\n{plan}\n\n本程序没有调用模型，不消耗模型推理额度。",dedupe_key=event)
        database.handled(event)
    return current


def setup():
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.title('微信通知配置（仅本机保存）')
    root.geometry('520x210')
    tk.Label(root, text='粘贴 PushPlus Token；内容隐藏，不会写入脚本或日志。').pack(pady=15)
    entry = tk.Entry(root, show='*', width=55)
    entry.pack(padx=15)
    entry.focus_set()

    def save():
        token = entry.get().strip()
        if not token or not token.isascii() or not token.isalnum():
            messagebox.showerror('未保存', '请检查 Token，只接受英文字母和数字。')
            return
        keyring.set_password(SERVICE, 'token', token)
        entry.delete(0, tk.END)
        messagebox.showinfo('已保存', '已保存到 Windows 凭据管理器。请回聊天告知已保存，再测试通知。')
        root.destroy()

    tk.Button(root, text='保存到 Windows 凭据管理器', command=save).pack(pady=20)
    root.mainloop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'check', 'setup', 'test'])
    args = parser.parse_args()
    try:
        if args.action == 'inspect':
            print(json.dumps(windows(read_limits()), ensure_ascii=False))
        elif args.action == 'setup':
            setup()
        elif args.action == 'test':
            print(notify('Codex 额度通知测试', '这是一条发送给你自己的测试消息。收到后请在聊天中确认。'))
        else:
            print(json.dumps(check(), ensure_ascii=False))
    except Exception as exc:
        # Never print exception messages, HTTP bodies or authentication responses.
        print('error_type=' + type(exc).__name__)
        raise SystemExit(1)
