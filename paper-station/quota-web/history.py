"""Output archival and narrowly scoped, previewed cleanup."""
import hashlib
import json
from pathlib import Path
import shutil
import threading
import time
import uuid
import control

PREVIEWS={}
MUTEX=threading.RLock()

def live_root():return control.PROJECT/'results'
def archive_root():return control.PROJECT/'history'/'outputs'
def valid_id(ident):return isinstance(ident,str) and len(ident)==32 and all(c in '0123456789abcdef' for c in ident)
def folder(ident):
    if not valid_id(ident):raise ValueError('任务编号无效')
    old=live_root()/ident
    return old if old.exists() else archive_root()/ident

def init():
    with control.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS history_policy(id INTEGER PRIMARY KEY,value TEXT);
          CREATE TABLE IF NOT EXISTS cleared_outputs(task_id TEXT PRIMARY KEY,cleared_at TEXT);''')
        db.execute('INSERT OR IGNORE INTO history_policy VALUES(1,?)',
          (json.dumps({'enabled':False,'days':30,'max_mb':1024}),))

def policy():
    with control.connect() as db:return json.loads(db.execute('SELECT value FROM history_policy WHERE id=1').fetchone()[0])

def set_policy(data):
    if type(data.get('enabled')) is not bool:raise ValueError('自动清理开关无效')
    days=int(data.get('days',30));mb=int(data.get('max_mb',1024))
    if not 1<=days<=3650 or not 16<=mb<=102400:raise ValueError('保留期限为 1—3650 天，容量为 16—102400 MB')
    if data['enabled'] and data.get('confirm') is not True:raise ValueError('请确认自动永久清理范围')
    with control.connect() as db:db.execute('UPDATE history_policy SET value=? WHERE id=1',
        (json.dumps({'enabled':data['enabled'],'days':days,'max_mb':mb}),))

def file_inventory(path):
    root=path.resolve();result=[]
    if path.is_symlink() or path.is_junction():raise ValueError('不处理链接目录')
    for p in sorted(path.rglob('*')):
        if p.is_symlink() or p.is_junction() or not p.resolve().is_relative_to(root):
            raise ValueError('输出目录包含链接，已拒绝清理')
        if p.is_file():
            st=p.stat();result.append((str(p.relative_to(path)),st.st_size,st.st_mtime_ns))
    return result

def records(active=None):
    with control.connect() as db:tasks={r['id']:dict(r) for r in db.execute('SELECT * FROM tasks')}
    output=[]
    for root in (live_root(),archive_root()):
        if not root.exists():continue
        for path in root.iterdir():
            if not valid_id(path.name) or not path.is_dir():continue
            task=tasks.get(path.name)
            if not task:continue
            try:
                files=file_inventory(path)
                total=sum(f[1] for f in files)
                modified=max([f[2] for f in files],default=path.stat().st_mtime_ns)/1e9
                safe=path.name!=active and task['status'] in ('completed','cancelled')
                fingerprint=hashlib.sha256(json.dumps(files).encode()).hexdigest()
                output.append({'id':path.name,'title':task['title'],'status':task['status'],
                    'bytes':total,'modified':modified,'eligible':safe,'archived':root==archive_root(),
                    'fingerprint':fingerprint,'file_count':len(files)})
            except (ValueError,OSError):
                output.append({'id':path.name,'title':task['title'],'status':task['status'],
                    'bytes':0,'modified':0,'eligible':False,'archived':root==archive_root(),
                    'fingerprint':'unsafe','file_count':0})
    return output

def snapshot(active=None):
    rows=records(active)
    return {'items':sorted(rows,key=lambda r:r['modified'],reverse=True),
            'total_bytes':sum(r['bytes'] for r in rows),'policy':policy()}

def archive_completed(active=None):
    archive_root().mkdir(parents=True,exist_ok=True)
    for row in records(active):
        if row['status']!='completed' or row['archived'] or not row['eligible']:continue
        source=(live_root()/row['id']).resolve();destination=(archive_root()/row['id']).resolve()
        if source.parent!=live_root().resolve() or destination.parent!=archive_root().resolve():raise ValueError('路径越界')
        if not destination.exists():source.rename(destination)

def candidates(ids=None,active=None):
    rows=records(active)
    if ids is not None:
        if not isinstance(ids,list) or not ids or len(ids)>200 or not all(valid_id(i) for i in ids):raise ValueError('请选择需要清理的历史输出')
        selected=[r for r in rows if r['id'] in ids]
        if len(selected)!=len(set(ids)) or not all(r['eligible'] for r in selected):raise ValueError('选择中包含不存在或未完成的输出')
        return selected
    cfg=policy();now=time.time();chosen=[];remaining=sum(r['bytes'] for r in rows)
    for row in sorted(rows,key=lambda r:r['modified']):
        if row['eligible'] and (now-row['modified']>cfg['days']*86400 or remaining>cfg['max_mb']*1024*1024):
            chosen.append(row);remaining-=row['bytes']
    return chosen

def preview(ids=None,active=None):
    with MUTEX:
        for k in list(PREVIEWS):
            if PREVIEWS[k]['expires']<time.time():PREVIEWS.pop(k,None)
        rows=candidates(ids,active);token=uuid.uuid4().hex
        PREVIEWS[token]={'expires':time.time()+300,'rows':rows}
        return {'token':token,'items':[{'id':r['id'],'title':r['title'],'bytes':r['bytes']} for r in rows],
                'total_bytes':sum(r['bytes'] for r in rows)}

def commit(token,confirmed,active=None):
    if confirmed is not True:raise ValueError('需要确认永久删除这些历史输出')
    with MUTEX:
        entry=PREVIEWS.pop(token,None)
        if not entry or entry['expires']<time.time():raise ValueError('清理预览已过期，请重新预览')
        current={r['id']:r for r in records(active)}
        for row in entry['rows']:
            r=current.get(row['id'])
            if not r or not r['eligible'] or r['fingerprint']!=row['fingerprint']:
                raise ValueError('输出或运行状态发生变化，请重新预览')
        removed=[]
        for row in entry['rows']:
            path=folder(row['id']).resolve()
            allowed=(live_root().resolve(),archive_root().resolve())
            if path.parent not in allowed or path.name!=row['id']:raise ValueError('清理路径越界')
            file_inventory(path)
            # Only validated task-owned output folders, never input papers or project root.
            shutil.rmtree(path)
            with control.connect() as db:db.execute('INSERT OR REPLACE INTO cleared_outputs VALUES(?,?)',(row['id'],control.now().isoformat()))
            removed.append(row['id'])
        return {'removed':removed}

def maintenance(active=None):
    with MUTEX:
        archive_completed(active)
        if policy()['enabled']:
            p=preview(active=active)
            if p['items']:commit(p['token'],True,active)
