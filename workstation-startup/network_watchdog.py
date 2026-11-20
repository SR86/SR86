"""Monitor continuously; recover confirmed outages with bounded login attempts."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
from network_check import is_online,portal_reachable

ROOT=Path(__file__).resolve().parent
INTERVAL=20
HEALTHY_INTERVAL=3600
MAX_ATTEMPTS=3
COOLDOWN=900
RETRY_DELAYS=(30,120)
REPAIR_EXE=Path(r'C:\Program Files (x86)\360\360Safe\netmon\360NetRepair.exe')


def check_interval(state):
    return HEALTHY_INTERVAL if state=='online' else INTERVAL


class RepairLauncher:
    """Open the existing assistant only; launching does not prove a repair."""
    def __init__(self, root=ROOT, launch=os.startfile):
        self.path=root/'network-repair-state.json';self.launch=launch
        try:self.last=float(json.loads(self.path.read_text(encoding='utf-8'))['last_launch'])
        except (OSError,ValueError,KeyError,TypeError):self.last=0

    def run(self, at):
        if at-self.last<3600:return 'rate_limited'
        if not REPAIR_EXE.is_file():return 'assistant_missing'
        # Persist before launching: restart or ambiguous launch must not create a loop.
        self.last=at
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'last_launch':at}),encoding='utf-8')
        temp.replace(self.path)
        try:self.launch(str(REPAIR_EXE));return 'assistant_open_requested'
        except OSError:return 'assistant_launch_failed'


class Recovery:
    def __init__(self):
        self.failures=0;self.attempts=0;self.next_attempt=0;self.blocked=False;self.state='starting'

    def step(self, online, reachable, at, login):
        if online:
            self.failures=0;self.attempts=0;self.next_attempt=0;self.blocked=False
            self.state='online';return
        self.failures+=1
        if self.failures<2:self.state='confirming_outage';return
        if self.blocked:self.state='authentication_blocked';return
        if self.attempts>=MAX_ATTEMPTS:
            if at<self.next_attempt:self.state='cooldown';return
            self.attempts=0
        if at<self.next_attempt:self.state='retry_wait';return
        if not reachable:self.state='waiting_for_campus_network';return
        self.attempts+=1
        started=time.monotonic()
        result=login()
        at+=max(0,time.monotonic()-started)
        if result==0:
            self.failures=0;self.attempts=0;self.next_attempt=0;self.state='online';return
        if result in (2,3,4):
            self.blocked=True;self.state='authentication_blocked';return
        if self.attempts>=MAX_ATTEMPTS:
            self.next_attempt=at+COOLDOWN;self.state='cooldown'
        else:
            self.next_attempt=at+RETRY_DELAYS[self.attempts-1];self.state='retry_wait'


def login_once():
    python=Path(sys.executable).with_name('python.exe')
    proc=subprocess.Popen([str(python),str(ROOT/'campus_login.py')],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:return proc.wait(timeout=100)
    except subprocess.TimeoutExpired:
        # Terminate only this authentication process and the browser it spawned.
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        return 1


def main():
    logs=ROOT/'logs';logs.mkdir(exist_ok=True)
    handler=RotatingFileHandler(logs/'network-watchdog.log',maxBytes=1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger=logging.getLogger('network_watchdog');logger.setLevel(logging.INFO);logger.addHandler(handler)
    with (ROOT/'network-watchdog.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:return
        recovery=Recovery();repair=RepairLauncher();last=None;logger.info('monitor_started')
        while True:
            delay=INTERVAL
            try:
                online=is_online()
                reachable=False if online else portal_reachable()
                def authenticate():
                    logger.info('authentication_attempt number=%d',recovery.attempts)
                    result=login_once()
                    if result==1 and not is_online():
                        logger.info('repair_status=%s',repair.run(time.time()))
                    return result
                recovery.step(online,reachable,time.time(),authenticate)
                if recovery.state!=last:
                    logger.info('state=%s',recovery.state);last=recovery.state
                state={'updated':int(time.time()),'state':recovery.state,
                    'failed_checks':recovery.failures,'authentication_attempts':recovery.attempts,
                    'next_attempt_at':int(recovery.next_attempt),
                    'next_check_at':int(time.time()+check_interval(recovery.state)),
                    'repair_last_launch':int(repair.last),
                    'repair_mode':'open_assistant_only'}
                temp=ROOT/'network-watchdog-status.tmp'
                temp.write_text(json.dumps(state,indent=2),encoding='utf-8')
                temp.replace(ROOT/'network-watchdog-status.json')
                delay=check_interval(recovery.state)
            except Exception as exc:logger.info('error_type=%s',type(exc).__name__)
            time.sleep(delay)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.check:print(json.dumps({'online':is_online(),'portal_reachable':portal_reachable()}))
    else:main()
