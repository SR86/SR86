"""Versioned, atomic per-stage checkpoints; no credentials or raw model events."""
import hashlib
import json
import os
from pathlib import Path
import uuid

STAGES = [
    ('任务定位与证据', '先界定用户任务所需概念、范围，列出来自论文的关键证据和 PDF 页码。不要提前写最终综述。'),
    ('分析与内容展开', '根据原任务展开论述。发展史任务应给出有证据的时间线、概念演进及本文位置；缺少的来源明确标注。利用上一阶段结果，不重复空泛总结。'),
    ('整合与核对', '整合之前阶段，生成可直接阅读的最终成果。逐项回应用户要求；核对摘录中的页码和证据，列出尚不能核实的内容，不把推断写成事实。'),
]

def stages_for(task):
    if task['kind']=='coding':
        return [('方案与最小实现','理解需求并创建可运行的最小网站和代码文件；不要只写方案。'),
                ('完善功能与界面','在现有项目文件基础上实现剩余功能，修复问题并运行必要检查。'),
                ('验证与交付','检查项目功能和文件完整性，修复可见问题，补充启动说明并总结验证结果。')]
    if task['kind']!='general':return STAGES
    return [('任务理解与提纲','明确用户目标、约束和交付提纲；列出所缺信息，不假装已操作电脑。'),
            ('内容生成','按照任务要求完成实质性内容；复用提纲，清楚区分事实、建议及需要核验的内容。'),
            ('整合与核对','输出最终可直接使用的文字成果，检查是否逐项回应任务要求，列出剩余限制。')]

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def save(folder, data):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    temp=folder/('progress-'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(temp,folder/'progress.json')
    finally:temp.unlink(missing_ok=True)

def load(folder):
    path=Path(folder)/'progress.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def prepare(task, source, folder):
    key=hashlib.sha256(json.dumps({k:task[k] for k in ('title','prompt','paper','kind')},
        sort_keys=True,ensure_ascii=False).encode()).hexdigest()+':'+(digest(source) if source else 'no-paper')
    revision=Path(folder)/'revision_context.md'
    if revision.exists():key+=':'+digest(revision)
    progress=load(folder)
    if progress:
        if progress.get('version')!=1 or progress.get('fingerprint')!=key:
            raise RuntimeError('论文或任务要求已变化，请创建新任务，旧存档不会被覆盖')
        invalid=False
        for stage in progress['stages']:
            if stage['status']=='completed' and not invalid:
                path=Path(folder)/stage['file']
                invalid=not path.is_file() or digest(path)!=stage.get('sha256')
            if invalid:
                stage['status']='pending'
                stage.pop('sha256',None)
    else:
        progress={'version':1,'fingerprint':key,'stages':[
            {'name':name,'status':'pending','file':''} for name,_ in stages_for(task)]}
        (Path(folder)/'stages').mkdir(parents=True,exist_ok=True)
    save(folder,progress)
    return progress

def overview(folder):
    try:
        progress=load(folder)
        if not progress:return None
        return {'completed':sum(s['status']=='completed' for s in progress['stages']),
                'total':len(progress['stages']),
                'stages':[{'name':s['name'],'status':s['status']} for s in progress['stages']]}
    except Exception:return None

def run_pipeline(task, source, folder, perform, current_status, set_status, stopped):
    folder=Path(folder)
    progress=prepare(task,source,folder)
    for index, (name,instruction) in enumerate(stages_for(task)):
        stage=progress['stages'][index]
        if stage['status']=='completed':continue
        if stopped():
            set_status('paused','用户请求停止，已完成阶段已保存');return
        draft=''
        if stage.get('file'):
            old=folder/stage['file']
            partial=old if old.is_file() else old.with_name('partial.md')
            if partial.is_file():
                draft='\n上次本阶段未完成草稿（未经核对，请结合原文决定是否复用）：\n'+partial.read_text(encoding='utf-8')[:12000]
        attempt=folder/'stages'/f'{index+1:02d}-{uuid.uuid4().hex}'
        attempt.mkdir(parents=True)
        stage.update(status='running',file=str((attempt/'reading.md').relative_to(folder)))
        save(folder,progress)
        previous='\n\n'.join((folder/s['file']).read_text(encoding='utf-8')[:24000]
            for s in progress['stages'][:index] if s['status']=='completed')
        work=dict(task,_output_folder=str(attempt),_previous_notes=previous+draft,
                  _stage_instruction=f'当前阶段 {index+1}/3：{name}。{instruction}')
        set_status('running',f'执行第 {index+1}/3 阶段：{name}；之前已完成阶段直接复用')
        perform(work)
        path=attempt/'reading.md'
        if current_status()!='running' or not path.is_file() or path.stat().st_size<100:
            stage['status']='interrupted';save(folder,progress);return
        stage.update(status='completed',sha256=digest(path))
        save(folder,progress)
    # The final integration is the third stage; never overwrite an earlier attempt.
    final=(folder/progress['stages'][-1]['file']).read_text(encoding='utf-8')
    temp=folder/'reading.tmp'
    footer='代码与说明已保存，实际运行请按交付说明验证。' if task['kind']=='coding' else '阶段已完成，事实和引文仍建议人工核对。'
    temp.write_text(final+'\n\n---\n自动生成：'+footer+'\n',encoding='utf-8')
    os.replace(temp,folder/'reading.md')
    note={'coding':'全部三个阶段已完成，代码与交付说明已保存；静态预览不代表后端已经启动',
          'general':'全部三个阶段已完成，结果已保存'}.get(task['kind'],'全部三个阶段已完成，阅读结果已生成；事实与引文仍需人工核对')
    set_status('completed',note)
