"""Durable phone task inbox and local reading assignments (no model calls)."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import threading
import uuid
import checkpoints
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
PAPERS = Path('C:/Papers')
DB = ROOT / 'control.sqlite3'
LOCK = threading.RLock()
DEFAULTS = {'reminders_enabled': False, 'reminder_times': ['07:00', '14:00', '20:00'],
            'reading_minutes': 30, 'mode': 'manual', 'day_start': '07:00',
            'night_enabled': False, 'work_start': '07:00', 'work_end': '23:59'}

@contextmanager
def connect():
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def init():
    with connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, title TEXT, paper TEXT,
            kind TEXT, prompt TEXT, status TEXT, created TEXT, due TEXT);
          CREATE TABLE IF NOT EXISTS readings(id TEXT PRIMARY KEY, day TEXT, slot TEXT,
            paper TEXT, goal TEXT, status TEXT, notified INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0, UNIQUE(day,slot));
          CREATE TABLE IF NOT EXISTS revisions(task_id TEXT PRIMARY KEY,parent_id TEXT,feedback TEXT,created TEXT);''')
        db.execute('CREATE TABLE IF NOT EXISTS code_targets(task_id TEXT PRIMARY KEY,target TEXT)')
        db.execute('INSERT OR IGNORE INTO settings VALUES(1,?)', (json.dumps(DEFAULTS),))

def settings():
    with connect() as db:
        return dict(DEFAULTS, **json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0]))

def time_value(value):
    dt.datetime.strptime(value, '%H:%M')
    if len(value) != 5:
        raise ValueError('时间格式应为 HH:MM')
    return value

def save_settings(data):
    value = settings()
    for key in ('reminders_enabled', 'night_enabled'):
        if key in data:
            if type(data[key]) is not bool:
                raise ValueError('开关类型错误')
            value[key] = data[key]
    if 'mode' in data:
        if data['mode'] not in ('manual', 'paused', 'scheduled'):
            raise ValueError('工作模式错误')
        value['mode'] = data['mode']
    for key in ('day_start', 'work_start', 'work_end'):
        if key in data:
            value[key] = time_value(data[key])
    if 'reminder_times' in data:
        times = data['reminder_times']
        if not isinstance(times, list) or len(times) != 3 or len(set(times)) != 3:
            raise ValueError('请设置三个不同的提醒时间')
        value['reminder_times'] = sorted(time_value(t) for t in times)
    if 'reading_minutes' in data:
        minutes = int(data['reading_minutes'])
        if not 5 <= minutes <= 120:
            raise ValueError('阅读时长应为 5 至 120 分钟')
        value['reading_minutes'] = minutes
    with connect() as db:
        db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(value),))
    return value

def papers():
    return sorted(p.name for p in PAPERS.glob('*.pdf') if p.is_file()) if PAPERS.exists() else []

def create_task(data, max_prompt=10000):
    title = str(data.get('title', '')).strip()
    prompt = str(data.get('prompt', '')).strip()
    paper = str(data.get('paper', ''))
    kind = data.get('kind')
    if not title or len(title) > 150 or not prompt or len(prompt) > max_prompt:
        raise ValueError('请填写标题和具体要求（要求最多一万字）')
    if kind not in ('paper_reading', 'presentation_creation', 'general', 'coding'):
        raise ValueError('请选择任务类型')
    if paper and paper not in papers():
        raise ValueError('未找到所选论文')
    if kind=='coding' and data.get('target','new_site') not in ('new_site','station_copy'):
        raise ValueError('网站目标无效')
    due = str(data.get('due', ''))
    if due:
        dt.datetime.fromisoformat(due)
    ident = uuid.uuid4().hex
    # Queue intake is separate from model execution; never pretend a task is running.
    with connect() as db:
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',
                   (ident, title, paper, kind, prompt, 'queued', now().isoformat(), due))
        if kind=='coding':db.execute('INSERT INTO code_targets VALUES(?,?)',(ident,data.get('target','new_site')))
    return ident


def transition_task(ident, action):
    states={'cancel':('cancelled','queued'),'queue':('queued','cancelled')}
    if action not in states:raise ValueError('未知操作')
    target,source=states[action]
    with connect() as db:
        row=db.execute('SELECT status FROM tasks WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('任务不存在')
        if row['status']!=source:raise ValueError('任务状态已改变，请刷新后重试')
        db.execute('UPDATE tasks SET status=? WHERE id=? AND status=?',(target,ident,source))

def update_task(data):
    action = data.get('action')
    if action not in ('cancel', 'hold', 'queue'):
        raise ValueError('不支持的操作')
    status = {'cancel': 'cancelled', 'hold': 'held', 'queue': 'queued'}[action]
    with connect() as db:
        row = db.execute('SELECT status FROM tasks WHERE id=?', (data.get('id'),)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        db.execute('UPDATE tasks SET status=? WHERE id=?', (status, data['id']))

def create_revision(data):
    import history
    feedback=str(data.get('feedback','')).strip()
    if not feedback or len(feedback)>10000:raise ValueError('请填写修改意见，最多一万字')
    with connect() as db:
        row=db.execute('SELECT * FROM tasks WHERE id=?',(data.get('id'),)).fetchone()
    if not row:raise ValueError('原任务不存在')
    parent=dict(row)
    if parent['status']=='running':raise ValueError('请先等待任务完成或停止，再提交修改意见')
    folder=history.folder(parent['id'])
    final=folder/'reading.md'
    old=final.read_text(encoding='utf-8') if final.exists() and final.stat().st_size>100 else ''
    if not old:
        progress=checkpoints.load(folder)
        if progress:
            old='\n\n'.join((folder/s['file']).read_text(encoding='utf-8') for s in progress['stages']
                if s['status']=='completed' and (folder/s['file']).is_file())
    if not old:raise ValueError('还没有可修改的结果，请先完成至少一个阶段')
    with connect() as db:old_target=db.execute('SELECT target FROM code_targets WHERE task_id=?',(parent['id'],)).fetchone()
    ident=create_task({'title':(parent['title']+' · 修改版')[:150], 'paper':parent['paper'],
        'kind':parent['kind'],'prompt':parent['prompt']+'\n\n本次修改意见（优先回应）：\n'+feedback,
        'target':old_target['target'] if old_target else 'new_site'},max_prompt=22000)
    target=PROJECT/'results'/ident
    try:
        target.mkdir(parents=True)
        (target/'revision_context.md').write_text(old[:80000],encoding='utf-8')
        with connect() as db:
            db.execute('INSERT INTO revisions VALUES(?,?,?,?)',(ident,parent['id'],feedback,now().isoformat()))
    except Exception:
        with connect() as db:
            db.execute('DELETE FROM tasks WHERE id=?',(ident,))
            db.execute('DELETE FROM code_targets WHERE task_id=?',(ident,))
        raise
    return ident

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))

GOALS = [
    '读摘要和引言。写出研究问题、已有方法的不足、本文的主要贡献；每点标记来源页码。',
    '读预备知识和核心构造。整理符号表，逐步解释一个关键算法或推导，列出三个不懂的问题。',
    '读安全分析、实验和结论。检查假设、比较基线与局限，写五句话总结，并准备三个组会讨论问题。',
]

def send(title, body, dedupe_key=None):
    spec = importlib.util.spec_from_file_location('quota_transport', PROJECT/'quota-notifier'/'quota_notify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.notify(title, body,dedupe_key=dedupe_key)

def tick(at=None, sender=None):
    at = at or now()
    cfg = settings()
    if not cfg['reminders_enabled']:
        return
    available = papers()
    for i, slot in enumerate(cfg['reminder_times']):
        start = at.replace(hour=int(slot[:2]), minute=int(slot[3:]), second=0, microsecond=0)
        # No flood of stale assignments after late boot; only catch up within 30 minutes.
        if not 0 <= (at-start).total_seconds() < 1800:
            continue
        with connect() as db:
            count = db.execute("SELECT count(*) FROM readings WHERE status='done'").fetchone()[0]
            paper = available[(count//3) % len(available)] if available else ''
            goal = GOALS[i] if paper else '请先把一篇论文 PDF 放入组会文件夹，在手机面板中选择阅读对象。当前仅检测到参考 PPT，不会凭空安排论文内容。'
            db.execute('INSERT OR IGNORE INTO readings(id,day,slot,paper,goal,status) VALUES(?,?,?,?,?,?)',
                (uuid.uuid4().hex, at.date().isoformat(), slot, paper, goal, 'todo'))
            row = db.execute('SELECT * FROM readings WHERE day=? AND slot=?', (at.date().isoformat(),slot)).fetchone()
            if row['notified'] or row['attempts'] >= 3 or row['status'] in ('done','skip'):
                continue
            claimed=db.execute('UPDATE readings SET notified=-1,attempts=attempts+1 WHERE id=? AND notified=0 AND attempts<3', (row['id'],)).rowcount
            if not claimed:continue
        body = (f"建议时长：{cfg['reading_minutes']} 分钟\n论文：{row['paper'] or '待添加'}\n"
                f"任务：{row['goal']}\n完成后在手机面板标记完成，也可以稍后处理或跳过。\n"
                'https://your-device.your-tailnet.ts.net/')
        try:
            if sender:sender('论文阅读任务 · '+slot, body)
            else:send('论文阅读任务 · '+slot,body,dedupe_key='reading:'+row['day']+':'+slot)
        except Exception:
            with connect() as db:db.execute('UPDATE readings SET notified=0 WHERE id=?',(row['id'],))
            continue
        with connect() as db:
            db.execute('UPDATE readings SET notified=1 WHERE id=?', (row['id'],))

def update_reading(data):
    action = data.get('action')
    if action not in ('done', 'skip', 'todo'):
        raise ValueError('不支持的操作')
    with connect() as db:
        db.execute('UPDATE readings SET status=? WHERE id=?', (action, data.get('id')))

def snapshot():
    import history
    import codejobs
    with connect() as db:
        tasks = [dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY created DESC LIMIT 50')]
        readings = [dict(r) for r in db.execute('SELECT * FROM readings ORDER BY day DESC,slot DESC LIMIT 21')]
    state = PROJECT/'quota-notifier'/'state.json'
    try:
        quota = json.loads(state.read_text(encoding='utf-8'))
        age = int(now().timestamp() - state.stat().st_mtime)
    except Exception:
        quota, age = {}, None
    with connect() as db:
        if db.execute("SELECT name FROM sqlite_master WHERE name='runs'").fetchone():
            runs={r['task_id']:dict(r) for r in db.execute('SELECT * FROM runs')}
            for task in tasks:
                task['run']=runs.get(task['id'])
    for task in tasks:
        task['progress']=checkpoints.overview(history.folder(task['id']))
        task['outputs_cleared']=False
        if task['kind']=='coding':task['code']=codejobs.summary(task['id'])
    with connect() as db:
        if db.execute("SELECT name FROM sqlite_master WHERE name='cleared_outputs'").fetchone():
            cleared={r[0] for r in db.execute('SELECT task_id FROM cleared_outputs')}
            for task in tasks:task['outputs_cleared']=task['id'] in cleared
        if db.execute("SELECT name FROM sqlite_master WHERE name='revisions'").fetchone():
            revisions={r['task_id']:dict(r) for r in db.execute('SELECT * FROM revisions')}
            for task in tasks:task['revision']=revisions.get(task['id'])
    return {'settings': settings(), 'papers': papers(), 'tasks': tasks, 'readings': readings,
            'quota': quota, 'quota_age_seconds': age, 'executor_enabled': True,
            'reference': 'PS签名专题.pptx', 'server_time': now().isoformat()}
