"""Provision a self-hosted notification application; never print credentials."""
import base64
import json
import time
import urllib.request
import keyring

SERVICE = 'CodexQuotaNotifier.Gotify'
BASE = 'http://127.0.0.1:8769'

def connect():
    password = keyring.get_password(SERVICE, 'admin')
    if not password:
        raise RuntimeError('LocalCredentialMissing')
    headers = {'Authorization': 'Basic ' + base64.b64encode(('admin:' + password).encode()).decode(),
               'Content-Type': 'application/json'}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(BASE + '/application', headers=headers), timeout=10) as r:
        apps = json.load(r)
    app = next((a for a in apps if a['name'] == 'Codex quota notifier'), None)
    if app is None:
        req = urllib.request.Request(BASE + '/application', headers=headers,
            data=json.dumps({'name': 'Codex quota notifier', 'description': 'Quota refresh and next-step plan'}).encode())
        with opener.open(req, timeout=10) as r:
            app = json.load(r)
    keyring.set_password(SERVICE, 'app_token', app['token'])
    print('notification_application_ready=True', flush=True)
    time.sleep(30)
    req = urllib.request.Request(BASE + '/message',
        headers={'X-Gotify-Key': app['token'], 'Content-Type': 'application/json'},
        data=json.dumps({'title': 'Codex 后台通知测试', 'message': '如果锁屏时收到这条消息，请回聊天确认。', 'priority': 8}, ensure_ascii=False).encode())
    with opener.open(req, timeout=10) as r:
        print('test_message_accepted=' + str(r.status == 200), flush=True)

if __name__ == '__main__':
    try:
        connect()
    except Exception as exc:
        print('error_type=' + type(exc).__name__, flush=True)
        raise SystemExit(1)
