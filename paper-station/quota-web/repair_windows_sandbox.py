"""Use Codex's own sandbox readiness/setup protocol; never requests model turns."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import executor


def main(action):
    reader = executor.transport()
    runtime = json.loads((Path(__file__).resolve().parent.parent/'quota-notifier'/'runtime.json').read_text(encoding='utf-8'))
    proc = subprocess.Popen([runtime['codex_path'], 'app-server', '--stdio', '-c', 'sandbox_mode="workspace-write"',
                             '-c', 'approval_policy="never"', '-c', 'windows.sandbox="elevated"'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW, env=reader.codex_environment())
    messages = queue.Queue()
    def collect():
        for line in proc.stdout:
            try: messages.put(json.loads(line))
            except ValueError: pass
        messages.put(None)
    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    def send(ident, method, params=None):
        message = {'method': method, 'params': params or {}}
        if ident is not None: message['id'] = ident
        proc.stdin.write(json.dumps(message)+'\n'); proc.stdin.flush()
    def result(ident, timeout=35):
        deadline = time.monotonic()+timeout
        while time.monotonic()<deadline:
            try: msg = messages.get(timeout=min(1, max(.01, deadline-time.monotonic())))
            except queue.Empty: continue
            if msg is None: raise RuntimeError('SandboxProtocolExited')
            if msg.get('id') == ident:
                if 'error' in msg: raise RuntimeError('SandboxProtocolRejected')
                return msg.get('result')
        raise TimeoutError('SandboxProtocolTimeout')
    try:
        send(1, 'initialize', {'clientInfo': {'name':'local_sandbox_maintenance','version':'1.0'},
                               'capabilities': {'experimentalApi':True}})
        result(1)
        send(None,'initialized')
        send(2,'windowsSandbox/readiness')
        before = result(2)
        print(json.dumps({'readiness_before':before}),flush=True)
        if action=='probe':
            folder=executor.ROOT.parent/'backups'/'sandbox-write-probe'
            folder.mkdir(exist_ok=True)
            code="$ErrorActionPreference='Stop'; $p=Join-Path (Get-Location) 'probe.txt'; [IO.File]::WriteAllText($p,'sandbox write ok'); if([IO.File]::ReadAllText($p) -ne 'sandbox write ok'){throw 'ProbeMismatch'}; Remove-Item -LiteralPath $p; Write-Output 'SandboxWriteVerified'"
            shell=Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
            send(3,'command/exec',{'command':[str(shell),'-NoProfile','-Command',code],'cwd':str(folder),
                'sandboxPolicy':{'type':'workspaceWrite','networkAccess':False,'writableRoots':[str(folder)]},'timeoutMs':30000})
            response=result(3,45)
            print(json.dumps({'sandbox_write_success':response.get('exitCode')==0 and 'SandboxWriteVerified' in response.get('stdout',''),
                'exit_code':response.get('exitCode'),'marker_removed':not (folder/'probe.txt').exists()}),flush=True)
            return
        if action=='inspect' or before.get('status')=='ready': return
        send(3,'windowsSandbox/setupStart',{'mode':'elevated','cwd':str(executor.ROOT)})
        print(json.dumps({'setup_requested':result(3)}),flush=True)
        # Keep the authorized maintenance request alive while Windows completes setup.
        deadline = time.monotonic()+180
        while time.monotonic()<deadline:
            try: msg = messages.get(timeout=10)
            except queue.Empty:
                print('WaitingForWindowsSandboxSetup',flush=True); continue
            if msg is None: raise RuntimeError('SandboxProtocolExited')
            if msg.get('method')=='windowsSandbox/setupCompleted':
                payload=msg.get('params',{})
                # Setup errors contain infrastructure diagnostics, never authentication data.
                print(json.dumps({'setup_completed':payload},ensure_ascii=False),flush=True)
                break
        else: raise TimeoutError('SandboxSetupTimedOut')
        send(4,'windowsSandbox/readiness')
        print(json.dumps({'readiness_after':result(4)}),flush=True)
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        thread.join(timeout=2)
        proc.stdin.close(); proc.stdout.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action', choices=('inspect','repair','probe'))
    parser.add_argument('--output', type=Path)
    args=parser.parse_args()
    try:
        if args.output:
            with args.output.open('w',encoding='utf-8') as out, contextlib.redirect_stdout(out):main(args.action)
        else:main(args.action)
    except Exception as exc: print(type(exc).__name__+': '+str(exc)); raise SystemExit(1)
