"""Isolated coding workspaces and bounded, sandboxed website artifact access."""
import io
import hashlib
import mimetypes
from pathlib import Path
import shutil
import zipfile
import control
import history

TARGETS=('new_site','station_copy')

def init():
    with control.connect() as db:db.execute('CREATE TABLE IF NOT EXISTS code_targets(task_id TEXT PRIMARY KEY,target TEXT)')

def register(ident,target):
    if target not in TARGETS:raise ValueError('请选择新建网站或论文小站副本')
    with control.connect() as db:db.execute('INSERT OR REPLACE INTO code_targets VALUES(?,?)',(ident,target))

def project(task):
    root=control.PROJECT/'results'/task['id']/'project'
    if root.exists():return root
    with control.connect() as db:r=db.execute('SELECT target FROM code_targets WHERE task_id=?',(task['id'],)).fetchone()
    target=r['target'] if r else 'new_site'
    root.mkdir(parents=True)
    with control.connect() as db:revision=db.execute('SELECT parent_id FROM revisions WHERE task_id=?',(task['id'],)).fetchone()
    if revision:
        previous=history.folder(revision['parent_id'])/'project'
        if previous.is_dir() and not previous.is_symlink() and not previous.is_junction():
            for source in previous.rglob('*'):
                relative=source.relative_to(previous)
                if any(p in ('node_modules','.git','.venv','__pycache__') for p in relative.parts):continue
                if source.is_file() and not source.is_symlink() and source.resolve().is_relative_to(previous.resolve()):
                    destination=root/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
            return root
    if target=='station_copy':
        destination=root/'quota-web';destination.mkdir()
        source=control.PROJECT/'quota-web'
        for p in source.iterdir():
            if p.is_file() and p.suffix.lower() in ('.py','.html','.css','.js','.md') and not p.is_symlink():
                shutil.copy2(p,destination/p.name)
        (root/'COPY_NOTICE.md').write_text('这是论文小站的源码副本，不含凭据、数据库、论文或运行数据。请只修改此目录内的副本。当前网站不会自动替换。',encoding='utf-8')
    return root

def convert(data):
    target=data.get('target','new_site')
    if target not in TARGETS:raise ValueError('网站目标无效')
    with control.connect() as db:row=db.execute('SELECT * FROM tasks WHERE id=?',(data.get('id'),)).fetchone()
    if not row:raise ValueError('任务不存在')
    if row['status']=='running':raise ValueError('请先停止原任务，再转换')
    ident=control.create_task({'title':row['title']+' · 网站代码','prompt':row['prompt'],
        'kind':'coding','paper':row['paper']})
    register(ident,target)
    return ident

def artifact_root(ident):
    folder=history.folder(ident)
    if folder.is_symlink() or folder.is_junction() or folder.resolve().parent not in (history.live_root().resolve(),history.archive_root().resolve()):raise ValueError('无效项目目录')
    raw=folder/'project'
    if raw.is_symlink() or raw.is_junction():raise ValueError('不支持链接目录')
    root=raw.resolve()
    if not root.is_dir():raise ValueError('尚未生成项目文件')
    return root

def fingerprint(root):
    result={}
    for path in Path(root).rglob('*'):
        if not path.is_file() or path.is_symlink():continue
        relative=path.relative_to(root)
        if any(p in ('node_modules','.git','.venv','__pycache__') for p in relative.parts):continue
        if path.stat().st_size>10*1024*1024:continue
        result[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def has_implementation(files):
    extensions={'.html','.css','.js','.jsx','.ts','.tsx','.py','.go','.rs','.php','.java','.cs','.cpp','.c'}
    return any(Path(name).suffix.lower() in extensions for name in files)

def static_file(ident,name):
    root=artifact_root(ident)
    if not name or name.endswith('/'):name+='index.html'
    path=(root/name).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():raise ValueError('预览文件不存在')
    allowed={'.html','.css','.js','.json','.svg','.png','.jpg','.jpeg','.webp','.woff','.woff2','.txt','.ico'}
    if path.suffix.lower() not in allowed or path.stat().st_size>10*1024*1024:raise ValueError('该文件不支持网页预览')
    return path,mimetypes.guess_type(path.name)[0] or 'application/octet-stream'

def summary(ident):
    try:root=artifact_root(ident)
    except ValueError:return None
    names=[];total=0
    for p in root.rglob('*'):
        if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root):
            relative=p.relative_to(root)
            if any(x in ('node_modules','.git','.venv','__pycache__') for x in relative.parts):continue
            names.append(str(relative).replace('\\','/'));total+=p.stat().st_size
    preview=next((x for x in ('index.html','dist/index.html','quota-web/console.html') if x in names),None)
    return {'files':names[:100],'file_count':len(names),'bytes':total,'preview':preview}

def archive(ident):
    root=artifact_root(ident);info=summary(ident)
    if info['bytes']>64*1024*1024 or info['file_count']>100:raise ValueError('项目过大，请在电脑项目目录中取出文件')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name in info['files']:
            p=(root/name).resolve()
            if not p.is_relative_to(root):raise ValueError('路径无效')
            z.write(p,name)
    return buffer.getvalue()
