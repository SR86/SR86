const $=id=>document.getElementById(id);let loaded=false;
async function api(path,data){const r=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const b=await r.json();if(!r.ok)throw Error(b.error||'请求失败');return b;}
function message(text){$('notice').textContent=text;}
function element(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
function action(label,path,data){const b=element('button',label);b.className='secondary';b.onclick=async()=>{if(data.action==='start'&&!confirm('开始调用 Codex 执行任务？本次会消耗额度；单次消耗和停止延迟无法保证精确卡在 30%。'))return;try{await api(path,data);await refresh();}catch(e){message(e.message);}};return b;}
async function refresh(){try{const s=await api('/api/status');$('summary').textContent=s.papers.length?`发现 ${s.papers.length} 篇论文 · 阅读提醒${s.settings.reminders_enabled?'已开启':'已暂停'}`:'组会文件夹暂无 PDF，请先添加论文；PPT 参考文件已记录。';
const buckets=Object.values(s.quota);$('quota').textContent=buckets.length?buckets.map(w=>`${w.bucket}：剩余 ${Math.max(0,100-w.usedPercent)}%，下次刷新 ${new Date(w.resetsAt*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}`).join('；')+`（${s.quota_age_seconds} 秒前检查）`:'尚无额度数据';
if(!loaded){$('reminders').checked=s.settings.reminders_enabled;['morning','afternoon','evening'].forEach((id,i)=>$(id).value=s.settings.reminder_times[i]);$('minutes').value=s.settings.reading_minutes;loaded=true;}
const prior=$('paper').value;$('paper').replaceChildren();const none=element('option','暂不选择论文');none.value='';$('paper').append(none);s.papers.forEach(p=>{const o=element('option',p);o.value=p;$('paper').append(o);});if(s.papers.includes(prior))$('paper').value=prior;
$('tasks').replaceChildren();if(!s.tasks.length)$('tasks').append(element('p','尚未提交任务。'));
const states={queued:'已排队',running:'正在执行',completed:'已完成',cancelled:'已取消',paused:'已暂停',failed:'执行失败',interrupted:'已中断'};
s.tasks.forEach(t=>{
 const card=element('article','');card.append(element('h3',t.title),element('p',`${states[t.status]||t.status} · ${t.paper||'未选择论文'}`),element('p',t.prompt));
 if(t.run)card.append(element('p',t.run.note));
 if(t.kind==='coding'&&t.code){card.append(element('p',`项目文件 ${t.code.file_count} 个`));const zip=element('a','下载网站／代码 ZIP');zip.href='/api/project-zip/'+t.id;card.append(zip);if(t.code.preview){const view=element('a',' 隔离预览网站');view.href='/site/'+t.id+'/'+t.code.preview;view.target='_blank';view.rel='noopener';card.append(view);}card.append(element('p','预览在隔离环境中运行，后端和浏览器存储能力需在正式部署后验证。'));}
 if(t.kind==='general'&&t.status!=='running'){
  const box=element('details',''),summary=element('summary','需要实际写代码？转换为网站任务');box.append(summary);
  const target=element('select','');[['station_copy','修改论文小站副本'],['new_site','新建独立网站']].forEach(([v,label])=>{const o=element('option',label);o.value=v;target.append(o);});box.append(target);
  const button=element('button','保留原任务，创建网站代码任务');button.onclick=async()=>{button.disabled=true;try{await api('/api/convert-code',{id:t.id,target:target.value});message('网站代码任务已创建，请在新任务上点击开始执行。原任务保留。');await refresh();}catch(e){message(e.message);}finally{button.disabled=false;}};box.append(button);card.append(box);
 }
if(t.revision)card.append(element('p','修改版 · 已带入旧版结果和你的意见，原结果保留'));
 if(t.progress){card.append(element('p',`已保存阶段 ${t.progress.completed}/${t.progress.total}`));t.progress.stages.forEach((stage,i)=>{const p=element('p',`${i+1}. ${stage.name} · ${stage.status==='completed'?'已保存':'待继续'}`);if(stage.status==='completed'){const a=element('a',' 查看阶段结果');a.href=`/api/checkpoint/${t.id}/${i+1}`;a.target='_blank';a.rel='noopener';p.append(a);}card.append(p);});}
 if(['queued','paused','failed','interrupted'].includes(t.status)&&['paper_reading','general','coding'].includes(t.kind))card.append(action(t.progress?'继续执行':'开始执行','/api/task-action',{id:t.id,action:'start'}));
 if(t.status==='running')card.append(action('停止执行','/api/task-action',{id:t.id,action:'stop'}));
 if(t.status==='queued')card.append(action('取消排队','/api/task-action',{id:t.id,action:'cancel'}));
 if(t.status==='cancelled')card.append(action('重新排队','/api/task-action',{id:t.id,action:'queue'}));
 if(t.outputs_cleared)card.append(element('p','输出已清理，任务记录保留'));
 if(t.status==='completed'&&!t.outputs_cleared){const link=element('a','查看排版结果');link.href='/api/result/'+t.id;link.target='_blank';link.rel='noopener';card.append(link);const download=element('a',' 下载 HTML 文件');download.href='/api/result/'+t.id+'?download=1';card.append(download);}
 if(!t.outputs_cleared&&t.status!=='running'&&(t.status==='completed'||t.progress?.completed>0)){
  const details=element('details',''),summary=element('summary','提出修改意见');details.append(summary);
  const label=element('label','希望怎样改？'),input=element('textarea','');input.rows=4;input.maxLength=10000;input.placeholder='例如：逐步解释拉格朗日插值公式，补充符号定义，减少长表格。';label.append(input);details.append(label);
  const submit=element('button','保存意见并创建修改版任务');submit.type='button';
  submit.onclick=async()=>{if(!input.value.trim()){message('请先填写修改意见');return;}submit.disabled=true;try{await api('/api/revision',{id:t.id,feedback:input.value});message('修改版任务已创建，点击新任务的开始执行才会调用 Codex；旧结果保留。');await refresh();}catch(e){message(e.message);}finally{submit.disabled=false;}};
  details.append(submit);card.append(details);
 }
 $('tasks').append(card);
});
$('readings').replaceChildren();if(!s.readings.length)$('readings').append(element('p','到提醒时间后，这里会出现阅读任务。'));s.readings.forEach(t=>{const card=element('article','');card.append(element('h3',`${t.day} ${t.slot} · ${{todo:'待阅读',done:'已完成',skip:'已跳过'}[t.status]}`),element('p',t.paper||'待添加论文'),element('p',t.goal));const buttons=element('div','');buttons.className='times';[['完成','done'],['稍后处理','todo'],['跳过','skip']].forEach(([label,a])=>buttons.append(action(label,'/api/reading-action',{id:t.id,action:a})));card.append(buttons);$('readings').append(card);});
}catch(e){message('连接失败：'+e.message);}}
$('schedule').onsubmit=async e=>{e.preventDefault();try{await api('/api/settings',{reminders_enabled:$('reminders').checked,reminder_times:['morning','afternoon','evening'].map(id=>$(id).value),reading_minutes:Number($('minutes').value)});message('阅读计划已保存');await refresh();}catch(e){message(e.message);}};
$('task').onsubmit=async e=>{e.preventDefault();if(!confirm('保存到队列？保存后需要点击任务卡片的“开始执行”，才会调用 Codex。'))return;try{await api('/api/tasks',{title:$('title').value,kind:$('kind').value,paper:$('paper').value,prompt:$('prompt').value,due:$('due').value});$('task').reset();message('任务已保存，尚未执行');await refresh();}catch(e){message(e.message);}};
$('notify').onclick=async()=>{try{await api('/api/test-notification',{});message('确认通知已提交给 Gotify');}catch(e){message(e.message);}};
$('upload').onsubmit=async e=>{
e.preventDefault();const file=$('pdf').files[0];if(!file)return;
if(!file.name.toLowerCase().endsWith('.pdf')||file.size>64*1024*1024||!file.size){$('upload-status').textContent='请选择 64 MB 以内的 PDF 文件';return;}
$('upload-button').disabled=true;$('upload-status').textContent='正在上传并检查 PDF，请保持此页面打开…';
try{const r=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/pdf','X-Filename':encodeURIComponent(file.name)},body:file});const b=await r.json();if(!r.ok)throw Error(b.error||'上传失败');await refresh();$('paper').value=b.name;$('upload-status').textContent=`上传成功：${b.name}（${b.pages} 页）。已在任务表单中选中这篇论文。`;$('upload').reset();}
catch(e){$('upload-status').textContent='上传失败：'+e.message;}
finally{$('upload-button').disabled=false;}
};

const panels=['files','reading','tasks','command','history','status'];
function selectPanel(name){
 if(!panels.includes(name))name='tasks';
 for(const p of panels){document.getElementById('panel-'+p).hidden=p!==name;const tab=document.getElementById('tab-'+p);tab.setAttribute('aria-selected',String(p===name));tab.tabIndex=p===name?0:-1;}
}
for(const tab of document.querySelectorAll('[data-panel]')){
 tab.addEventListener('click',()=>{location.hash=tab.dataset.panel;selectPanel(tab.dataset.panel);});
 tab.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const i=panels.indexOf(tab.dataset.panel);const next=panels[(i+(e.key==='ArrowRight'?1:panels.length-1))%panels.length];location.hash=next;selectPanel(next);document.getElementById('tab-'+next).focus();});
}
addEventListener('hashchange',()=>selectPanel(location.hash.slice(1)));
selectPanel(location.hash.slice(1));

refresh();setInterval(()=>{if(!document.hidden)refresh();},15000);
