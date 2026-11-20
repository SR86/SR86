"""Stable quota observations and cross-process notification receipts. No secrets."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import urllib.error
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path=Path(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS windows(
                    name TEXT PRIMARY KEY, window_id INTEGER, deadline INTEGER,
                    used REAL, peak REAL, observed REAL);
                CREATE TABLE IF NOT EXISTS refreshes(
                    event_key TEXT PRIMARY KEY, payload TEXT, created REAL, handled INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS receipts(
                    event_key TEXT PRIMARY KEY, state TEXT, attempts INTEGER, updated REAL);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=15)
        db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def observe(self, values, at=None, seed=None):
        at=time.time() if at is None else at
        result=[]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for value in values:
                w=dict(value)
                used=float(w['usedPercent']); deadline=int(w['resetsAt'])
                if not 0<=used<=100 or deadline<=0:raise ValueError('InvalidQuotaObservation')
                name=w['bucket']+':'+w['window']
                row=db.execute('SELECT * FROM windows WHERE name=?',(name,)).fetchone()
                if row is None and seed and name in seed:
                    old=seed[name]
                    row={'window_id':old.get('windowId',old['resetsAt']),
                         'deadline':old.get('windowResetAt',old['resetsAt']),
                         'used':old['usedPercent'],'peak':old.get('peakUsedPercent',old['usedPercent'])}
                refreshed=False
                if row is None:
                    ident=anchor=deadline; peak=used
                else:
                    ident=row['window_id']; anchor=row['deadline']; peak=max(row['peak'],used)
                    # Moving ETA is insufficient. Require actual restored capacity after
                    # the stable boundary, with a future boundary for the next period.
                    refreshed=(at>=anchor and deadline>anchor+60 and deadline>at and used<row['peak'])
                    idle_start=(at>=anchor and row['peak']==0 and row['used']==0 and used>0 and deadline>at)
                    if refreshed or idle_start:
                        ident=max(ident+1,deadline); anchor=deadline; peak=used
                w.update(windowId=ident,windowResetAt=anchor,peakUsedPercent=peak)
                db.execute('INSERT OR REPLACE INTO windows VALUES(?,?,?,?,?,?)',
                    (name,ident,anchor,used,peak,at))
                if refreshed:
                    key='quota:'+name+':'+str(ident)
                    db.execute('INSERT OR IGNORE INTO refreshes VALUES(?,?,?,0)',
                        (key,json.dumps(w),at))
                result.append(w)
        return result

    def pending_refreshes(self, at=None):
        at=time.time() if at is None else at
        with self.connect() as db:
            # Do not flood the phone with stale events after an offline period.
            db.execute('UPDATE refreshes SET handled=1 WHERE created<?',(at-1800,))
            return [(r['event_key'],json.loads(r['payload'])) for r in db.execute(
                'SELECT * FROM refreshes WHERE handled=0 ORDER BY created LIMIT 4')]

    def handled(self,key):
        with self.connect() as db:db.execute('UPDATE refreshes SET handled=1 WHERE event_key=?',(key,))

    def send_once(self,key,deliver):
        key=hashlib.sha256(key.encode('utf-8')).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM receipts WHERE event_key=?',(key,)).fetchone()
            if row and (row['state']!='retry' or row['attempts']>=3):return 'suppressed'
            attempts=row['attempts']+1 if row else 1
            # Claim before sending. A crash or ambiguous timeout must not replay it.
            db.execute('INSERT OR REPLACE INTO receipts VALUES(?,?,?,?)',(key,'sending',attempts,time.time()))
        try:deliver()
        except Exception as exc:
            reason=exc.reason if isinstance(exc,urllib.error.URLError) else None
            definite=(isinstance(reason,ConnectionRefusedError) or
                      (isinstance(exc,RuntimeError) and str(exc)=='PushTokenMissing'))
            with self.connect() as db:db.execute('UPDATE receipts SET state=?,updated=? WHERE event_key=?',
                ('retry' if definite else 'uncertain',time.time(),key))
            raise
        with self.connect() as db:db.execute("UPDATE receipts SET state='sent',updated=? WHERE event_key=?",(time.time(),key))
        return 'accepted'
