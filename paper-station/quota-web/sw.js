self.addEventListener('push', event=>{
  const data=event.data ? event.data.json() : {};
  event.waitUntil(self.registration.showNotification(data.title || '额度助手',{
    body:data.body || '有一条新通知',tag:'quota-test',data:{url:'/'}}));
});
self.addEventListener('notificationclick', event=>{
  event.notification.close();event.waitUntil(clients.openWindow('/'));
});
