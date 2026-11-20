let managementLoaded=false;
const sizeText=n=>n>=1024*1024?`${(n/1024/1024).toFixed(2)} MB`:`${(n/1024).toFixed(1)} KB`;
async function refreshManagement(){try{
 const [a,h,s]=await Promise.all([api('/api/automation'),api('/api/history'),api('/api/status')]);
 if(!managementLoaded){$('automation-enabled').checked=a.enabled;$('cleanup-enabled').checked=h.policy.enabled;$('cleanup-days').value=h.policy.days;$('cleanup-mb').value=h.policy.max_mb;managementLoaded=true;}
 const selected=$('command-paper').value;$('command-paper').replaceChildren();const empty=element('option','不使用论文（通用指令）');empty.value='';$('command-paper').append(empty);s.papers.forEach(name=>{const o=element('option',name);o.value=name;$('command-paper').append(o);});if(s.papers.includes(selected))$('command-paper').value=selected;
 $('commands').replaceChildren();if(!a.commands.length)$('commands').append(element('p','尚无自动化指令。'));
 const states={manual:'手动',scheduled:'等待触发',waiting_quota:'等待额度刷新',held:'已暂停调度',running:'已发起执行',done:'完成',needs_attention:'需要检查'};
 a.commands.forEach(c=>{const row=element('article','');row.append(element('h3',c.title),element('p',`${states[c.state]||c.state} · ${c.note}`));if(['scheduled','waiting_quota','running'].includes(c.state))row.append(action('暂停这条指令的后续调度','/api/automation-hold',{id:c.task_id}));$('commands').append(row);});
 $('storage-total').textContent=`任务输出共 ${sizeText(h.total_bytes)} · ${h.items.length} 个任务文件夹`;
 $('history-items').replaceChildren();if(!h.items.length)$('history-items').append(element('p','暂无历史输出。'));
 h.items.forEach(item=>{const row=element('article','');row.append(element('h3',item.title),element('p',`${sizeText(item.bytes)} · ${item.file_count} 个文件 · ${item.archived?'历史归档':'工作目录'} · ${item.eligible?'可清理':'未完成或运行中，受保护'}`));if(item.status==='completed'){const a=element('a','查看排版结果');a.href='/api/result/'+item.id;a.target='_blank';a.rel='noopener';row.append(a);const d=element('a',' 下载 HTML');d.href='/api/result/'+item.id+'?download=1';row.append(d);}if(item.eligible){const b=element('button','预览清除此任务输出');b.className='secondary';b.onclick=()=>cleanupPreview([item.id]);row.append(b);}$('history-items').append(row);});
}catch(e){message('管理页读取失败：'+e.message);}}
async function cleanupPreview(ids){try{
 const plan=await api('/api/cleanup-preview',ids?{ids}:{});const area=$('cleanup-plan');area.replaceChildren();
 if(!plan.items.length){area.append(element('p','没有符合条件的历史输出，无需清理。'));return;}
 area.append(element('h3',`将永久清除 ${plan.items.length} 个任务输出，约 ${sizeText(plan.total_bytes)}`));
 plan.items.forEach(item=>area.append(element('p',`${item.title} · ${sizeText(item.bytes)}`)));
 area.append(element('p','将删除上述任务的阶段文件、旧尝试及最终结果，不能通过网站恢复。论文原件和任务记录保留。'));
 const confirmButton=element('button','确认永久清除以上输出');confirmButton.onclick=async()=>{if(!confirm('确定永久删除预览列表中的输出？请先下载需要保留的文件。论文原件和任务记录不删除。'))return;confirmButton.disabled=true;try{await api('/api/cleanup-commit',{token:plan.token,confirm:true});area.replaceChildren(element('p','输出已清理，任务记录保留。'));await refresh();await refreshManagement();}catch(e){message(e.message);confirmButton.disabled=false;}};area.append(confirmButton);
}catch(e){message(e.message);}}
$('command-trigger').onchange=()=>{$('command-time-label').hidden=$('command-trigger').value!=='at_time';$('command-time').required=$('command-trigger').value==='at_time';};
$('command').onsubmit=async e=>{e.preventDefault();if(!confirm('保存这条指令？若已开启自动调度，将在所选条件满足后调用 Codex 并消耗额度。'))return;$('command-submit').disabled=true;try{await api('/api/automation-command',{title:$('command-title').value,kind:$('command-kind').value,target:$('code-target').value,paper:$('command-paper').value,prompt:$('command-prompt').value,trigger:$('command-trigger').value,run_at:$('command-time').value});$('command').reset();$('command-trigger').onchange();message('指令已保存；手动指令请到任务页开始，其他指令需开启自动调度。');await refresh();await refreshManagement();}catch(e){message(e.message);}finally{$('command-submit').disabled=false;}};
$('automation-switch').onsubmit=async e=>{e.preventDefault();const enabled=$('automation-enabled').checked;if(enabled&&!confirm('开启后，已保存的自动指令会按条件调用 Codex，受新增 30 个百分点软预算保护。夜间自动工作未启用。确认开启？'))return;try{await api('/api/automation-switch',{enabled});message(enabled?'自动调度已开启':'自动调度已关闭；正在执行的任务请在任务页停止');await refreshManagement();}catch(e){message(e.message);}};
$('history-policy').onsubmit=async e=>{e.preventDefault();const enabled=$('cleanup-enabled').checked;if(enabled&&!confirm('允许以后自动永久清除超期或超容量的最旧已完成输出？请先下载需长期保留的结果，论文原件和未完成任务不会删除。'))return;try{await api('/api/history-policy',{enabled,days:Number($('cleanup-days').value),max_mb:Number($('cleanup-mb').value),confirm:true});message('历史清理策略已保存');await refreshManagement();}catch(e){message(e.message);}};
$('cleanup-preview').onclick=()=>cleanupPreview();
refreshManagement();setInterval(()=>{if(!document.hidden&&['#history','#command'].includes(location.hash))refreshManagement();},15000);

$('command-kind').onchange=()=>{$('code-target-label').hidden=$('command-kind').value!=='coding';$('command-paper').required=$('command-kind').value==='paper_reading';};$('command-kind').onchange();
