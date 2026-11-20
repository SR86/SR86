"""Start a loopback-only Gotify with a randomly generated local credential."""
import os
from pathlib import Path
import secrets
import subprocess
import keyring

ROOT = Path(__file__).resolve().parent
SERVICE = 'CodexQuotaNotifier.Gotify'

def start():
    password = keyring.get_password(SERVICE, 'admin')
    if not password:
        password = secrets.token_urlsafe(24)
        keyring.set_password(SERVICE, 'admin', password)
    env = os.environ.copy()
    env.update(GOTIFY_SERVER_LISTENADDR='127.0.0.1', GOTIFY_SERVER_PORT='8769',
               GOTIFY_DEFAULTUSER_NAME='admin', GOTIFY_DEFAULTUSER_PASS=password,
               GOTIFY_REGISTRATION='false', GOTIFY_LOGLEVEL='warn',
               GOTIFY_SERVER_SECURECOOKIE='true')
    subprocess.Popen([str(ROOT/'bin'/'gotify-windows-amd64.exe')], cwd=ROOT,
                     env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)

if __name__ == '__main__':
    start()
