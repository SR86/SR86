const $=id=>document.getElementById(id);
let cachedState=null,settingsLoaded=false,lastTaskKey='',lastReadingKey='',lastPaperKey='',refreshSerial=0,connectionError=null;
const pendingActions=new Set();
const revisionDrafts=new Map(),openCards=new Map();
const panelNames=['files','reading','tasks','command','history','status'];
function element(tag,text='',className=''){const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;return node;}
function message(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
async function api(path,data){const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const body=await response.json();if(!response.ok)throw Error(body.error||'请求失败');return body;}
function link(text,url){const node=element('a',text,'action-link');node.href=url;node.target='_blank';node.rel='noopener';return node;}
function action(label,path,data,primary=false){const button=element('button',label,primary?'':'secondary'),key=path+JSON.stringify(data);button.type='button';button.disabled=pendingActions.has(key);button.onclick=async()=>{if(pendingActions.has(key))return;pendingActions.add(key);button.disabled=true;try{await api(path,data);pendingActions.delete(key);await refresh();if(typeof refreshManagement==='function')await refreshManagement();}catch(e){message(e.message,true);}finally{pendingActions.delete(key);button.disabled=false;}};return button;}
function details(key,title){const box=element('details');box.open=Boolean(openCards.get(key));box.append(element('summary',title));box.addEventListener('toggle',()=>openCards.set(key,box.open));return box;}
function selectPanel(name,update=true){if(!panelNames.includes(name))name='tasks';for(const p of panelNames){$('panel-'+p).hidden=p!==name;$('tab-'+p).setAttribute('aria-selected',String(p===name));$('tab-'+p).tabIndex=p===name?0:-1;}if(update)history.replaceState(null,'','#'+name);if(typeof refreshManagement==='function'&&['command','history'].includes(name))refreshManagement();}
for(const tab of document.querySelectorAll('[data-panel]')){tab.onclick=()=>{selectPanel(tab.dataset.panel);window.scrollTo({top:0,behavior:'smooth'});};tab.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const i=panelNames.indexOf(tab.dataset.panel),next=panelNames[(i+(e.key==='ArrowRight'?1:panelNames.length-1))%panelNames.length];selectPanel(next);$('tab-'+next).focus();};}
addEventListener('hashchange',()=>selectPanel(location.hash.slice(1),false));selectPanel(location.hash.slice(1),false);
$('new-task').onclick=()=>{selectPanel('command');$('command-prompt').focus();};
const stateNames={queued:'待开始',running:'执行中',completed:'已完成',cancelled:'已取消',paused:'已暂停',failed:'失败',interrupted:'已中断'};
const kindNames={coding:'网站／代码',general:'文字／方案',paper_reading:'论文阅读',presentation_creation:'PPT'};
function taskCard(t){
 const card=element('article','','task-card'),heading=element('div','','card-heading');heading.append(element('h2',t.title),element('span',stateNames[t.status]||t.status,'badge state-'+t.status));card.append(heading);
 card.append(element('p',[kindNames[t.kind],t.paper].filter(Boolean).join(' · '),'meta'));
 if(t.run?.note)card.append(element('p',t.run.note,'hint'+(t.status==='failed'?' error':'')));
 const info=details(t.id+'-prompt','查看要求');info.append(element('p',t.prompt));card.append(info);
 if(t.progress){const p=element('progress');p.max=t.progress.total;p.value=t.progress.completed;p.setAttribute('aria-label',`已保存 ${p.value}/${p.max} 阶段`);card.append(p);const box=details(t.id+'-stages',`阶段 ${t.progress.completed}/${t.progress.total}`);t.progress.stages.forEach((s,i)=>{const row=element('div','','stage-row');row.append(element('span',`${i+1}. ${s.name}`));row.append(s.status==='completed'?link('查看',`/api/checkpoint/${t.id}/${i+1}`):element('span',s.status==='running'?'执行中':'待完成','muted'));box.append(row);});card.append(box);}
 const actions=element('div','','actions');
 if(['queued','paused','failed','interrupted'].includes(t.status)&&['paper_reading','general','coding'].includes(t.kind))actions.append(action(t.progress?.completed?'继续':'开始','/api/task-action',{id:t.id,action:'start'},true));
 if(t.status==='running')actions.append(action('停止','/api/task-action',{id:t.id,action:'stop'}));
 if(t.status==='paused'){
  const remove=element('button','删除','danger');remove.type='button';remove.onclick=async()=>{remove.disabled=true;try{
    const plan=await api('/api/task-delete-preview',{id:t.id});
    const size=plan.bytes>=1048576?(plan.bytes/1048576).toFixed(1)+' MB':(plan.bytes/1024).toFixed(1)+' KB';
    if(!confirm(`永久删除“${plan.title}”？\n包括任务记录及 ${plan.file_count} 个输出文件（${size}）。\n论文原件保留，删除后不可恢复。`))return;
    await api('/api/task-delete-commit',{token:plan.token,confirm:true});
    revisionDrafts.delete(t.id);message('任务及输出已删除');await refresh();if(typeof refreshManagement==='function')await refreshManagement();
  }catch(e){message(e.message,true);}finally{remove.disabled=false;}};actions.append(remove);
 }
 if(t.status==='queued')actions.append(action('取消','/api/task-action',{id:t.id,action:'cancel'}));
 if(t.status==='cancelled')actions.append(action('重新排队','/api/task-action',{id:t.id,action:'queue'}));
 if(t.outputs_cleared)card.append(element('p','输出已清理','hint'));
 if(t.status==='completed'&&!t.outputs_cleared)actions.append(link(t.kind==='coding'?'交付说明':'查看结果','/api/result/'+t.id),link('下载 HTML','/api/result/'+t.id+'?download=1'));
 if(t.kind==='coding'&&t.code?.file_count){actions.append(link('下载代码','/api/project-zip/'+t.id));if(t.code.preview){actions.append(link('静态预览','/site/'+t.id+'/'+t.code.preview));card.append(element('p','预览仅展示页面；上传下载等功能需启动项目后端。','hint'));}}
 if(actions.childNodes.length)card.append(actions);
 if(!t.outputs_cleared&&t.status!=='running'&&(t.status==='completed'||t.progress?.completed>0)){
  const box=details(t.id+'-revision','提出修改意见'),input=element('textarea');input.rows=4;input.maxLength=10000;input.placeholder='哪里需要调整？';input.value=revisionDrafts.get(t.id)||'';input.setAttribute('aria-label','修改意见');input.oninput=()=>revisionDrafts.set(t.id,input.value);box.append(input);
  const button=element('button','创建修改版');button.type='button';button.onclick=async()=>{if(!input.value.trim())return message('请填写修改意见',true);button.disabled=true;try{await api('/api/revision',{id:t.id,feedback:input.value});revisionDrafts.delete(t.id);message('修改版已创建，可在新任务中开始。');await refresh();}catch(e){message(e.message,true);}finally{button.disabled=false;}};box.append(button);card.append(box);
 }
 if(t.kind==='general'&&t.status!=='running'){
  const box=details(t.id+'-convert','转为网站／代码任务'),select=element('select');select.setAttribute('aria-label','代码目标');[['station_copy','论文小站副本'],['new_site','新建网站']].forEach(([v,text])=>{const o=element('option',text);o.value=v;select.append(o);});const b=element('button','创建代码任务');b.onclick=async()=>{b.disabled=true;try{await api('/api/convert-code',{id:t.id,target:select.value});message('代码任务已创建，原任务保留。');await refresh();}catch(e){message(e.message,true);}finally{b.disabled=false;}};box.append(select,b);card.append(box);
 }
 return card;
}
function renderTasks(force=false){if(!cachedState)return;const filter=$('task-filter').value,rows=cachedState.tasks.filter(t=>filter==='all'||(filter==='completed'?t.status==='completed':!['completed','cancelled'].includes(t.status)));const key=JSON.stringify(rows)+filter;if(!force&&key===lastTaskKey)return;lastTaskKey=key;$('tasks').replaceChildren(...(rows.length?rows.map(taskCard):[element('div','暂无任务','empty')]));}
$('task-filter').onchange=()=>renderTasks(true);
function setOptions(select,names,empty){const previous=select.value,key=JSON.stringify(names);if(select.dataset.options===key)return;select.dataset.options=key;select.replaceChildren();const first=element('option',empty);first.value='';select.append(first);names.forEach(name=>{const o=element('option',name);o.value=name;select.append(o);});if(names.includes(previous))select.value=previous;}
async function refresh(){const serial=++refreshSerial;try{
 const s=await api('/api/status');if(serial!==refreshSerial)return null;cachedState=s;$('connection').textContent='已连接';$('connection').classList.remove('offline');if(connectionError&&$('notice').textContent===connectionError)message('');connectionError=null;const active=s.tasks.filter(t=>!['completed','cancelled'].includes(t.status)).length;$('summary').textContent=`${s.papers.length} 篇论文 · ${active} 个待处理任务`;
 const times=s.settings.reminder_times.join(' · '),duration=s.settings.reading_minutes;$('reading-summary').textContent=`${times}　/　每次 ${duration%60===0?duration/60+' 小时':duration+' 分钟'}${s.settings.reminders_enabled?'':' · 已关闭'}`;
 const buckets=Object.values(s.quota);$('quota').replaceChildren();buckets.forEach(w=>{const row=element('div','','quota-row');row.append(element('strong',`${Math.max(0,100-w.usedPercent)}%`),element('span','五小时额度剩余'));const p=element('progress');p.max=100;p.value=Math.max(0,100-w.usedPercent);const time=new Date(w.resetsAt*1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'});const age=s.quota_age_seconds,checked=age==null?'检查时间未知':`${Math.max(0,age)} 秒前检查${age>300?' · 数据可能已过期':''}`;row.append(p,element('small',`预计 ${time} 恢复（可能变化） · ${checked}`));$('quota').append(row);});if(!buckets.length)$('quota').append(element('p','暂无额度数据'));
 if(!settingsLoaded){$('reminders').checked=s.settings.reminders_enabled;['morning','afternoon','evening'].forEach((id,i)=>$(id).value=s.settings.reminder_times[i]);$('minutes').value=s.settings.reading_minutes;settingsLoaded=true;}
 renderTasks();
 const rk=JSON.stringify(s.readings);if(rk!==lastReadingKey){lastReadingKey=rk;$('readings').replaceChildren();if(!s.readings.length)$('readings').append(element('div','下一次提醒时，阅读任务会出现在这里。','empty'));s.readings.forEach(t=>{const card=element('article','','task-card'),h=element('div','','card-heading');h.append(element('h2',`${t.day} ${t.slot}`),element('span',{todo:'待阅读',done:'完成',skip:'已跳过'}[t.status],'badge'));card.append(h,element('p',t.paper||'待添加论文','meta'),element('p',t.goal));const buttons=element('div','','actions');[['完成','done'],['稍后','todo'],['跳过','skip']].forEach(([text,a])=>buttons.append(action(text,'/api/reading-action',{id:t.id,action:a})));card.append(buttons);$('readings').append(card);});}
 const pk=JSON.stringify(s.papers);if(pk!==lastPaperKey){lastPaperKey=pk;$('paper-library').replaceChildren();if(!s.papers.length)$('paper-library').append(element('div','还没有论文，先上传一篇。','empty'));s.papers.forEach(name=>{const row=element('div','','library-row');row.append(element('span',name));const b=element('button','新建阅读任务','small secondary');b.onclick=()=>window.usePaper?.(name);row.append(b);$('paper-library').append(row);});}
 return s;
}catch(e){if(serial!==refreshSerial)return null;$('connection').textContent='连接中断';$('connection').classList.add('offline');connectionError=e.message;message(e.message,true);return null;}}
$('schedule').onsubmit=async e=>{e.preventDefault();try{await api('/api/settings',{reminders_enabled:$('reminders').checked,reminder_times:['morning','afternoon','evening'].map(id=>$(id).value),reading_minutes:Number($('minutes').value)});message('阅读计划已保存');await refresh();}catch(e){message(e.message,true);}};
$('notify').onclick=async()=>{if($('notify').disabled)return;$('notify').disabled=true;try{await api('/api/test-notification',{});message('通知请求已处理，请查看 Gotify');}catch(e){message(e.message,true);}finally{$('notify').disabled=false;}};
$('upload').onsubmit=async e=>{e.preventDefault();const file=$('pdf').files[0];if(!file)return;if(!file.name.toLowerCase().endsWith('.pdf')||!file.size||file.size>64*1024*1024)return $('upload-status').textContent='请选择 64 MB 以内的 PDF';$('upload-button').disabled=true;$('upload-status').textContent='上传中…';try{const r=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/pdf','X-Filename':encodeURIComponent(file.name)},body:file}),b=await r.json();if(!r.ok)throw Error(b.error||'上传失败');$('upload-status').textContent=`已上传 ${b.name} · ${b.pages} 页`;$('upload').reset();await refresh();if(typeof refreshManagement==='function')await refreshManagement();}catch(e){$('upload-status').textContent=e.message;}finally{$('upload-button').disabled=false;}};
$('refresh-now').onclick=()=>refresh();
refresh();setInterval(()=>{if(!document.hidden)refresh();},15000);
