// Headless DOM shim for frontend state behavior; not a visual browser test.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class El{
 constructor(tag='div'){this.tagName=tag;this.childNodes=[];this.dataset={};this.attributes={};this.value='';this.hidden=false;this.textContent='';}
 append(...nodes){this.childNodes.push(...nodes);}
 replaceChildren(...nodes){this.childNodes=[...nodes];}
 setAttribute(k,v){this.attributes[k]=String(v);}
 getAttribute(k){return this.attributes[k];}
 addEventListener(k,fn){this['on'+k]=fn;}
 focus(){}scrollIntoView(){}reset(){}
 get classList(){return {add(){},remove(){},toggle(){}};}
}
const html=fs.readFileSync(__dirname+'/ui.html','utf8'),els={};
for(const m of html.matchAll(/id="([^"]+)"/g))els[m[1]]=new El();
for(const name of ['files','reading','tasks','command','history','status'])els['tab-'+name].dataset.panel=name;
els['task-filter'].value='all';els['command-kind'].value='coding';els['command-trigger'].value='manual';
const task={id:'a'.repeat(32),title:'测试任务',kind:'general',paper:'',prompt:'生成学习计划',status:'completed',run:{note:'已完成'},progress:null};
let payload={papers:['a.pdf'],tasks:[task],readings:[],settings:{reminder_times:['09:00','14:00','19:30'],reading_minutes:120,reminders_enabled:true},quota:{},quota_age_seconds:1};
const ctx={console,document:{getElementById:id=>els[id],createElement:tag=>new El(tag),querySelectorAll:()=>Object.keys(els).filter(x=>x.startsWith('tab-')).map(x=>els[x]),hidden:false},
 location:{hash:'#tasks'},history:{replaceState(){}},addEventListener(){},setInterval(){},confirm:()=>true,
 fetch:async path=>({ok:true,json:async()=>path==='/api/automation'?{enabled:false,commands:[]}:path==='/api/history'?{policy:{enabled:false,days:30,max_mb:1024},items:[],total_bytes:0}:payload})};ctx.window=ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__dirname+'/app-v2.js','utf8'),ctx);
vm.runInContext(fs.readFileSync(__dirname+'/management-v2.js','utf8'),ctx);
const visit=(node,tag)=>node.childNodes.flatMap(n=>n instanceof El?[...(n.tagName===tag?[n]:[]),...visit(n,tag)]:[]);
(async()=>{
 await vm.runInContext('refresh()',ctx);
 let input=visit(els.tasks,'textarea')[0];assert(input,'revision form exists');input.value='请保留这段未提交意见';input.oninput();
 await vm.runInContext('refresh()',ctx);assert.strictEqual(visit(els.tasks,'textarea')[0],input,'unchanged refresh must preserve DOM');
 task.run.note='状态更新';await vm.runInContext('refresh()',ctx);assert.equal(visit(els.tasks,'textarea')[0].value,'请保留这段未提交意见','changed card must restore draft');
 vm.runInContext("selectPanel('history')",ctx);assert.equal(els['panel-history'].hidden,false);assert.equal(els['panel-tasks'].hidden,true);
 els['command-kind'].value='paper_reading';els['command-kind'].onchange();assert.equal(els['command-paper'].required,true);assert.equal(els['command-paper-label'].hidden,false);
 els['command-kind'].value='coding';els['command-kind'].onchange();assert.equal(els['command-paper'].required,false);assert.equal(els['code-target-label'].hidden,false);
 els['task-filter'].value='active';els['task-filter'].onchange();assert.equal(visit(els.tasks,'article').length,0);
 const originalFetch=ctx.fetch;let posts=0,finish;
 ctx.fetch=(path,options)=>path==='/api/test-notification'?(posts++,new Promise(resolve=>finish=resolve)):originalFetch(path,options);
 const first=els.notify.onclick(),second=els.notify.onclick();assert.equal(posts,1,'double-click must not submit duplicate notifications');finish({ok:true,json:async()=>({ok:true})});await Promise.all([first,second]);assert.equal(els.notify.disabled,false);
 const requests=[];ctx.fetch=(path,options)=>path==='/api/status'?new Promise(resolve=>requests.push(resolve)):originalFetch(path,options);
 const oldRefresh=vm.runInContext('refresh()',ctx),newRefresh=vm.runInContext('refresh()',ctx);
 requests[1]({ok:true,json:async()=>payload});await newRefresh;requests[0]({ok:true,json:async()=>({...payload,papers:[]})});await oldRefresh;
 assert.equal(vm.runInContext('cachedState.papers.length',ctx),1,'late stale response must not overwrite latest state');
 ctx.fetch=originalFetch;
 ctx.fetch=async()=>{throw Error('network temporary failure')};await vm.runInContext('refresh()',ctx);assert.equal(els.notice.textContent,'network temporary failure');
 ctx.fetch=originalFetch;await vm.runInContext('refresh()',ctx);assert.equal(els.notice.textContent,'','recovered connection must clear stale connection error');
 console.log('PASS: drafts, navigation, optional papers, filters, duplicate clicks, stale responses and connection recovery');
})().catch(e=>{console.error(e);process.exitCode=1;});
