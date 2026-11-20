"""Private Edge Web Push capability probe. Does not invoke model inference."""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from pywebpush import webpush

ROOT = Path(__file__).parent
HOST = 'your-device.your-tailnet.ts.net'
ORIGIN = 'https://' + HOST
KEY = ec.generate_private_key(ec.SECP256R1())
PRIVATE = base64.urlsafe_b64encode(KEY.private_bytes(serialization.Encoding.DER,
    serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode().rstrip('=')
PUBLIC = base64.urlsafe_b64encode(KEY.public_key().public_bytes(
    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
LOCK = threading.Lock()
STATE = {'phase': '等待手机订阅', 'received': False}
SUBSCRIPTION = None
PENDING = False

def validate_subscription(data):
    endpoint = urlsplit(data['endpoint'])
    allowed = ('fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com')
    host = endpoint.hostname or ''
    if (endpoint.scheme != 'https' or endpoint.port not in (None, 443)
        or endpoint.username or endpoint.password
        or not (host in allowed or host.endswith('.notify.windows.com'))):
        raise ValueError('UnsupportedPushProvider')
    if not all(isinstance(data['keys'][k], str) and len(data['keys'][k]) < 300
               for k in ('auth', 'p256dh')):
        raise ValueError('InvalidKeys')
    return {'endpoint': data['endpoint'], 'keys': data['keys']}

def delayed_push(subscription):
    global PENDING
    time.sleep(30)
    try:
        webpush(subscription_info=subscription,
                data=json.dumps({'title': 'Codex 后台通知测试',
                                 'body': '如果锁屏时收到这条通知，说明后台推送链路可用。'}),
                vapid_private_key=PRIVATE, vapid_claims={'sub': ORIGIN},
                ttl=300, timeout=15)
        with LOCK:
            STATE['phase'] = '推送服务已接受，等待手机确认'
    except Exception as exc:
        with LOCK:
            STATE['phase'] = '推送失败：' + type(exc).__name__
    finally:
        with LOCK:
            PENDING = False

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log subscription endpoints or request bodies.

    def reply(self, status, body, mime='application/json; charset=utf-8'):
        data = (json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else body).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def trusted(self):
        host = self.headers.get('Host', '')
        return host in ('127.0.0.1:8768', 'localhost:8768') or (
            host == HOST and bool(self.headers.get('Tailscale-User-Login')))

    def do_GET(self):
        if not self.trusted():
            return self.reply(403, {'error': 'PrivateAccessOnly'})
        if self.path == '/api/status':
            with LOCK:
                return self.reply(200, dict(STATE, publicKey=PUBLIC))
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8'),
                 '/sw.js': ('sw.js', 'text/javascript; charset=utf-8')}
        if self.path not in files:
            return self.reply(404, {'error': 'NotFound'})
        name, mime = files[self.path]
        self.reply(200, (ROOT / name).read_text(encoding='utf-8'), mime)

    def do_POST(self):
        global SUBSCRIPTION, PENDING
        if not self.trusted() or self.headers.get('Origin') not in (
            ORIGIN, 'http://127.0.0.1:8768', 'http://localhost:8768'):
            return self.reply(403, {'error': 'OriginRejected'})
        try:
            size = int(self.headers.get('Content-Length', 0))
            if not 0 < size < 8192:
                raise ValueError()
            data = json.loads(self.rfile.read(size))
            if self.path == '/api/subscribe':
                sub = validate_subscription(data)
                with LOCK:
                    SUBSCRIPTION = sub
                    STATE['phase'] = '订阅成功，可以测试锁屏通知'
            elif self.path == '/api/test':
                with LOCK:
                    if not SUBSCRIPTION or PENDING:
                        return self.reply(409, {'error': 'SubscribeFirstOrTestPending'})
                    PENDING = True
                    STATE.update(phase='将在 30 秒后发送，请现在锁屏', received=False)
                    sub = dict(SUBSCRIPTION)
                threading.Thread(target=delayed_push, args=(sub,), daemon=True).start()
            elif self.path == '/api/confirm':
                with LOCK:
                    STATE.update(received=True, phase='用户已确认收到通知')
            else:
                return self.reply(404, {'error': 'NotFound'})
            self.reply(200, {'ok': True})
        except Exception as exc:
            self.reply(400, {'error': type(exc).__name__})

if __name__ == '__main__':
    print('Preview: http://127.0.0.1:8768', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8768), Handler).serve_forever()
