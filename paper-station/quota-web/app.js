const $ = id => document.getElementById(id);
const supported = isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
$('support').textContent = supported ? '支持检测通过。请点击按钮，允许 Edge 显示通知。' : '当前浏览器或地址不支持后台推送。请使用手机 Edge 打开 HTTPS 地址。';
$('subscribe').disabled = !supported;
async function api(path, data) {
  const r = await fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const body = await r.json();
  if (!r.ok) throw new Error(body.error || '请求失败');
  return body;
}
function keyBytes(key) {return Uint8Array.from(atob(key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-key.length%4)%4)), c=>c.charCodeAt(0));}
async function refresh(){try{const s=await api('/api/status');$('status').textContent=s.phase;}catch{$('status').textContent='连接中断，请检查 Tailscale 和电脑是否在线';}}
$('subscribe').onclick=async()=>{
  $('subscribe').disabled=true;
  try{
    if(await Notification.requestPermission()!=='granted')throw new Error('通知权限未允许，请在 Edge 网站权限中开启');
    await navigator.serviceWorker.register('/sw.js');
    const reg=await navigator.serviceWorker.ready;
    const s=await api('/api/status');
    // Test server keys are ephemeral. Replace any old test subscription.
    const old=await reg.pushManager.getSubscription(); if(old)await old.unsubscribe();
    $('status').textContent='正在连接浏览器推送服务…';
    const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:keyBytes(s.publicKey)});
    await api('/api/subscribe',sub.toJSON());$('test').disabled=false;await refresh();
  }catch(e){$('status').textContent=e.message;}finally{$('subscribe').disabled=false;}
};
$('test').onclick=async()=>{try{await api('/api/test',{});await refresh();}catch(e){$('status').textContent=e.message;}};
$('confirm').onclick=async()=>{try{await api('/api/confirm',{});await refresh();}catch(e){$('status').textContent=e.message;}};
setInterval(()=>{if(!document.hidden)refresh();},5000);
