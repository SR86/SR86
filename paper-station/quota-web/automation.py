"""Explicit local task schedules, not arbitrary shell commands."""
import json
import time
import control
import executor

def init():
    with control.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS automation_commands(
          task_id TEXT PRIMARY KEY,trigger TEXT,run_at TEXT,anchor INTEGER,state TEXT,note TEXT);
          CREATE TABLE IF NOT EXISTS automation_switch(id INTEGER PRIMARY KEY,enabled INTEGER);
          CREATE TABLE IF NOT EXISTS automation_windows(task_id TEXT PRIMARY KEY,anchor_id INTEGER);
          INSERT OR IGNORE INTO automation_switch VALUES(1,0);''')

def enabled():
    with control.connect() as db:return bool(db.execute('SELECT enabled FROM automation_switch WHERE id=1').fetchone()[0])

def set_enabled(value):
    if type(value) is not bool:raise ValueError('自动调度开关无效')
    with control.connect() as db:db.execute('UPDATE automation_switch SET enabled=? WHERE id=1',(int(value),))

def create(data):
    trigger=data.get('trigger','manual')
    if trigger not in ('manual','immediate','after_reset','at_time'):raise ValueError('请选择执行方式')
    paper=str(data.get('paper') or '').strip()
    kind=data.get('kind') or ('paper_reading' if paper else 'general')
    if kind not in ('paper_reading','general','coding'):raise ValueError('请选择论文阅读、通用文字或网站代码任务')
    when=''
    if trigger=='at_time':
        when=str(data.get('run_at',''))
        try:
            stamp=control.dt.datetime.fromisoformat(when)
            if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=control.now().tzinfo)
        except Exception:raise ValueError('预约时间无效，请使用北京时间日期和时间')
        if stamp<=control.now():raise ValueError('预约时间需要晚于现在')
        when=stamp.isoformat()
    if paper and paper not in control.papers():raise ValueError('所选论文不存在')
    if kind=='paper_reading' and not paper:raise ValueError('论文阅读任务需要选择论文；不看论文请选择通用任务')
    current=executor.quota() if trigger=='after_reset' else None
    anchor=current.get('windowId',current['resetsAt']) if current else 0
    ident=control.create_task({'title':data.get('title') or str(data.get('prompt',''))[:60],
      'prompt':data.get('prompt'),'paper':paper,'kind':kind,'target':data.get('target','new_site')})
    with control.connect() as db:db.execute('INSERT INTO automation_commands VALUES(?,?,?,?,?,?)',
      (ident,trigger,when,anchor,'manual' if trigger=='manual' else 'scheduled','等待手动开始' if trigger=='manual' else '等待触发条件'))
    if current:
        with control.connect() as db:db.execute('INSERT OR REPLACE INTO automation_windows VALUES(?,?)',(ident,anchor))
    return ident

def hold(ident):
    with control.connect() as db:db.execute("UPDATE automation_commands SET state='held',note='用户已暂停此指令' WHERE task_id=?",(ident,))

def snapshot():
    with control.connect() as db:
        rows=[dict(r) for r in db.execute('SELECT a.*,t.title,t.status FROM automation_commands a JOIN tasks t ON a.task_id=t.id ORDER BY t.created DESC LIMIT 100')]
    return {'enabled':enabled(),'commands':rows,'night_enabled':False}

def tick():
    with control.connect() as db:
        rows=[dict(r) for r in db.execute('SELECT a.*,t.status FROM automation_commands a JOIN tasks t ON a.task_id=t.id')]
    for row in rows:
        if row['state']!='running':continue
        if row['status']=='running':continue
        if row['status']=='completed':state,note='done','任务已完成'
        else:
            with control.connect() as db:r=db.execute('SELECT note FROM runs WHERE task_id=?',(row['task_id'],)).fetchone()
            note=r['note'] if r else '请检查任务状态'
            if '额度' in note or '预算' in note:
                try:
                    current=executor.quota();anchor=current.get('windowId',current['resetsAt'])
                except Exception:continue
                with control.connect() as db:
                    db.execute("UPDATE automation_commands SET state='waiting_quota',anchor=?,note=? WHERE task_id=?",(anchor,note,row['task_id']))
                    db.execute('INSERT OR REPLACE INTO automation_windows VALUES(?,?)',(row['task_id'],anchor))
                continue
            state='needs_attention'
        with control.connect() as db:db.execute('UPDATE automation_commands SET state=?,note=? WHERE task_id=?',(state,note,row['task_id']))
    if not enabled() or executor.ACTIVE or control.now().hour<7:return
    cfg=control.settings()
    if cfg['mode']=='paused':return
    current_time=control.now().strftime('%H:%M')
    if not cfg['work_start']<=current_time<=cfg['work_end']:return
    for row in rows:
        if row['state'] not in ('scheduled','waiting_quota'):continue
        if row['status'] not in ('queued','paused','failed','interrupted'):continue
        if row['trigger']=='at_time' and control.now()<control.dt.datetime.fromisoformat(row['run_at']):continue
        if row['trigger']=='after_reset' or row['state']=='waiting_quota':
            current=executor.quota()
            anchor=current.get('windowId',current['resetsAt'])
            with control.connect() as db:old=db.execute('SELECT anchor_id FROM automation_windows WHERE task_id=?',(row['task_id'],)).fetchone()
            if old is None:
                # Rebase old ETA-based schedules conservatively, without triggering them.
                with control.connect() as db:db.execute('INSERT OR REPLACE INTO automation_windows VALUES(?,?)',(row['task_id'],anchor))
                continue
            if anchor<=old['anchor_id']:continue
        executor.start(row['task_id'])
        with control.connect() as db:db.execute("UPDATE automation_commands SET state='running',note='已启动，受白天新增30个百分点软预算限制' WHERE task_id=?",(row['task_id'],))
        return
