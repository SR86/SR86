"""Logged-in Windows user monitor; no model turns, no credential logging."""
import datetime
import importlib.util
import msvcrt
from pathlib import Path
import time
import urllib.request
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def log(event):
    directory = ROOT / 'logs'
    directory.mkdir(exist_ok=True)
    now = datetime.datetime.now().astimezone()
    with (directory / (now.strftime('%Y-%m-%d') + '.log')).open('a', encoding='utf-8') as file:
        file.write(now.isoformat(timespec='seconds') + ' ' + event + '\n')

def gotify_ready():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:8769/health', timeout=5) as response:
            return response.status == 200
    except Exception:
        return False

def main():
    # A file lock is released by Windows even when the process exits unexpectedly.
    with (ROOT / 'monitor.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        quota = load('quota_notify', ROOT / 'quota_notify.py')
        gotify = load('start_gotify', ROOT.parent / 'gotify' / 'start_gotify.py')
        console = load('package_launch', ROOT / 'package_launch.py')
        log('monitor_started')
        failure_count = 0
        while True:
            try:
                if not gotify_ready():
                    gotify.start()
                    time.sleep(3)
                if not gotify_ready():
                    raise ConnectionError()
                try:
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8768/api/status', timeout=3) as response:
                        response.read(100000)
                except Exception:
                    console.start(ROOT.parent)
                quota.check()
                if failure_count:
                    log('monitor_recovered')
                failure_count = 0
            except Exception as exc:
                failure_count += 1
                # Record only class names; URLs, tokens and response bodies stay private.
                if failure_count == 1 or failure_count % 10 == 0:
                    log('error_type=' + type(exc).__name__)
                    if type(exc) is RuntimeError and str(exc) in (
                        'CodexExecutableUnavailable', 'QuotaReaderExited', 'QuotaReadRejected',
                        'PushTokenMissing', 'FiveHourWindowUnavailable', 'PushRejected'):
                        log('error_code=' + str(exc))
            time.sleep(min(120 * (2 ** min(failure_count, 3)), 900))

if __name__ == '__main__':
    main()
