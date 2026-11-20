"""Confirmed deletion of paused tasks and their own output folders only."""
import hashlib
import json
import shutil
import time
import uuid
import control
import history

PREVIEWS={}

def inspect(ident,active=None):
    if not history.valid_id(ident):raise ValueError('任务编号无效')
    with control.connect() as db:row=db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('任务不存在')
    if row['status']!='paused':raise ValueError('只能删除已暂停任务')
    if active==ident:raise ValueError('任务正在收尾，请稍后重试')
    paths=[];manifest=[]
    for root in (history.live_root(),history.archive_root()):
        if not root.resolve().is_relative_to(control.PROJECT.resolve()):raise ValueError('输出目录无效')
        path=root/ident
        if path.is_symlink() or path.is_junction():raise ValueError('不能删除链接目录')
        if not path.exists():continue
        if not path.is_dir() or path.resolve().parent!=root.resolve():raise ValueError('输出目录无效')
        files=history.file_inventory(path)
        paths.append(path);manifest.append((str(path.relative_to(control.PROJECT)),files))
    fingerprint=hashlib.sha256(json.dumps({'task':dict(row),'outputs':manifest},sort_keys=True).encode()).hexdigest()
    return dict(row),paths,manifest,fingerprint

def preview(ident,active=None):
    for token in list(PREVIEWS):
        if PREVIEWS[token]['expires']<time.time():PREVIEWS.pop(token,None)
    row,paths,manifest,fingerprint=inspect(ident,active)
    token=uuid.uuid4().hex
    PREVIEWS[token]={'id':ident,'expires':time.time()+300,'fingerprint':fingerprint}
    return {'token':token,'id':ident,'title':row['title'],
            'bytes':sum(f[1] for _,files in manifest for f in files),
            'file_count':sum(len(files) for _,files in manifest)}

def commit(token,confirmed,active=None):
    if confirmed is not True:raise ValueError('请确认永久删除任务及输出')
    entry=PREVIEWS.pop(token,None)
    if not entry or entry['expires']<time.time():raise ValueError('预览已过期，请重试')
    row,paths,manifest,fingerprint=inspect(entry['id'],active)
    if fingerprint!=entry['fingerprint']:raise ValueError('任务或输出发生变化，请重新确认')
    # Server holds control.LOCK, preventing a start/schedule between validation and deletion.
    for path in paths:
        if path.resolve().parent not in (history.live_root().resolve(),history.archive_root().resolve()):
            raise ValueError('删除路径越界')
        history.file_inventory(path)
        shutil.rmtree(path)
    with control.connect() as db:
        for table,column in (('runs','task_id'),('revisions','task_id'),('code_targets','task_id'),
                             ('automation_commands','task_id'),('automation_windows','task_id'),('cleared_outputs','task_id')):
            if db.execute('SELECT name FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone():
                db.execute(f'DELETE FROM {table} WHERE {column}=?',(entry['id'],))
        db.execute('DELETE FROM tasks WHERE id=? AND status=\'paused\'',(entry['id'],))
    return {'ok':True,'removed':entry['id']}
