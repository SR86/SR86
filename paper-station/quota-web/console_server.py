"""Private phone inbox and reading reminder console."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
import control
import uploads
import executor
import checkpoints
import exports
import history
import automation
import codejobs
import task_delete
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parent
HOST='your-device.your-tailnet.ts.net'
ORIGIN='https://'+HOST

def reminders():
    count=0
    while True:
        try: control.tick()
        except Exception: pass
        try:
            with control.LOCK:automation.tick()
        except Exception:pass
        if count%5==0:
            try:
                with control.LOCK:history.maintenance(executor.ACTIVE)
            except Exception:pass
        count+=1
        time.sleep(20)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,body,mime='application/json; charset=utf-8',document=False,download=False,preview=False):
        data=body if isinstance(body,bytes) else (json.dumps(body,ensure_ascii=False) if isinstance(body,dict) else body).encode()
        self.send_response(status)
        headers={'Content-Type':mime,'Content-Length':str(len(data)),'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"}
        if document:headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
        if download:headers['Content-Disposition']='attachment; filename="reading.html"'
        if mime=='application/zip':headers['Content-Disposition']='attachment; filename="website-project.zip"'
        if preview:headers['Content-Security-Policy']="sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'none'; form-action 'none'; frame-ancestors 'self'; base-uri 'none'"
        for key,value in headers.items(): self.send_header(key,value)
        self.end_headers();self.wfile.write(data)
    def trusted(self):
        host=self.headers.get('Host','')
        return host in ('127.0.0.1:8768','localhost:8768') or (host==HOST and bool(self.headers.get('Tailscale-User-Login')))
    def do_GET(self):
        if not self.trusted(): return self.reply(403,{'error':'PrivateAccessOnly'})
        download=self.path.endswith('?download=1')
        self.path=self.path.partition('?')[0]
        if self.path=='/api/status': return self.reply(200,control.snapshot())
        if self.path=='/api/history':return self.reply(200,history.snapshot(executor.ACTIVE))
        if self.path=='/api/automation':return self.reply(200,automation.snapshot())
        if self.path.startswith('/api/project-zip/'):
            ident=self.path.removeprefix('/api/project-zip/')
            try:return self.reply(200,codejobs.archive(ident),'application/zip')
            except ValueError as exc:return self.reply(400,{'error':str(exc)})
        if self.path.startswith('/site/'):
            parts=self.path.split('/',3)
            if len(parts)<4:return self.reply(400,{'error':'InvalidPreview'})
            try:
                path,mime=codejobs.static_file(parts[2],unquote(parts[3]))
                return self.reply(200,path.read_bytes(),mime,preview=True)
            except ValueError as exc:return self.reply(404,{'error':str(exc)})
        if self.path.startswith('/api/checkpoint/'):
            parts=self.path.split('/')
            if len(parts)!=5 or len(parts[3])!=32 or any(c not in '0123456789abcdef' for c in parts[3]) or parts[4] not in ('1','2','3'):
                return self.reply(400,{'error':'InvalidStage'})
            folder=history.folder(parts[3])
            progress=checkpoints.load(folder)
            if not progress:return self.reply(404,{'error':'暂无存档'})
            stage=progress['stages'][int(parts[4])-1]
            if stage['status']!='completed':return self.reply(404,{'error':'该阶段尚未完成'})
            path=(folder/stage['file']).resolve()
            if not path.is_relative_to(folder.resolve()):return self.reply(403,{'error':'InvalidPath'})
            output=exports.export_document(path)
            return self.reply(200,output.read_text(encoding='utf-8'),'text/html; charset=utf-8',document=True,download=download)
        if self.path.startswith('/api/result/'):
            ident=self.path.removeprefix('/api/result/')
            if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
                return self.reply(400,{'error':'InvalidTaskId'})
            path=history.folder(ident)/'reading.md'
            if not path.is_file():return self.reply(404,{'error':'尚无结果'})
            output=exports.export_document(path)
            return self.reply(200,output.read_text(encoding='utf-8'),'text/html; charset=utf-8',document=True,download=download)
        files={'/':('ui.html','text/html; charset=utf-8'),'/app-v2.js':('app-v2.js','text/javascript; charset=utf-8'),'/management-v2.js':('management-v2.js','text/javascript; charset=utf-8'),'/style-v2.css':('style-v2.css','text/css; charset=utf-8'),'/console.js':('console.js','text/javascript; charset=utf-8'),'/management.js':('management.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        if self.path not in files: return self.reply(404,{'error':'NotFound'})
        name,mime=files[self.path];self.reply(200,(ROOT/name).read_text(encoding='utf-8'),mime)
    def do_POST(self):
        if not self.trusted() or self.headers.get('Origin') not in (ORIGIN,'http://127.0.0.1:8768','http://localhost:8768'):
            return self.reply(403,{'error':'OriginRejected'})
        try:
            if self.path=='/api/upload':
                self.connection.settimeout(90)
                if self.headers.get('Content-Type','').split(';')[0]!='application/pdf':
                    raise ValueError('仅支持 PDF 文件')
                length=int(self.headers.get('Content-Length',0))
                with control.LOCK:
                    result=uploads.save_pdf(self.rfile,length,self.headers.get('X-Filename',''),control.PAPERS)
                return self.reply(201,dict(ok=True,**result))
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<32768: raise ValueError('请求过大')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict): raise ValueError('请求格式错误')
            with control.LOCK:
                if self.path=='/api/settings': control.save_settings(data)
                elif self.path=='/api/tasks': control.create_task(data)
                elif self.path=='/api/convert-code':return self.reply(201,{'ok':True,'id':codejobs.convert(data)})
                elif self.path=='/api/revision':
                    ident=control.create_revision(data)
                    return self.reply(201,{'ok':True,'id':ident})
                elif self.path=='/api/automation-command':return self.reply(201,{'ok':True,'id':automation.create(data)})
                elif self.path=='/api/automation-switch':automation.set_enabled(data.get('enabled'))
                elif self.path=='/api/automation-hold':automation.hold(data.get('id'))
                elif self.path=='/api/command':
                    ident=automation.create(data)
                    return self.reply(201,{'ok':True,'id':ident})
                elif self.path=='/api/history-policy':history.set_policy(data)
                elif self.path=='/api/cleanup-preview':return self.reply(200,history.preview(data.get('ids'),executor.ACTIVE))
                elif self.path=='/api/cleanup-commit':return self.reply(200,history.commit(data.get('token'),data.get('confirm'),executor.ACTIVE))
                elif self.path=='/api/task-delete-preview':return self.reply(200,task_delete.preview(data.get('id'),executor.ACTIVE))
                elif self.path=='/api/task-delete-commit':return self.reply(200,task_delete.commit(data.get('token'),data.get('confirm'),executor.ACTIVE))
                elif self.path=='/api/reading-action': control.update_reading(data)
                elif self.path=='/api/task-action':
                    if data.get('action')=='start':
                        executor.start(data.get('id'))
                        return self.reply(200,{'ok':True})
                    if data.get('action')=='stop':
                        executor.stop(data.get('id'))
                        automation.hold(data.get('id'))
                        return self.reply(200,{'ok':True})
                    control.transition_task(data.get('id'),data.get('action'))
                elif self.path=='/api/test-notification':
                    cfg=control.settings()
                    control.send('通知测试','阅读提醒：'+'、'.join(cfg['reminder_times'])+f"，每次 {cfg['reading_minutes']} 分钟。可在手机面板调整或关闭。",
                        dedupe_key='test-notification:'+str(int(time.time()//30)))
                else: return self.reply(404,{'error':'NotFound'})
            self.reply(200,{'ok':True})
        except ValueError as exc: self.reply(400,{'error':str(exc)[:150]})
        except Exception as exc: self.reply(500,{'error':type(exc).__name__})

if __name__=='__main__':
    # Bind before any state recovery or reminder thread. A duplicate worker must
    # not mark live jobs interrupted or send reminders before discovering port use.
    server=ThreadingHTTPServer(('127.0.0.1',8768),Handler)
    control.init()
    executor.init()
    history.init()
    automation.init()
    codejobs.init()
    threading.Thread(target=reminders,daemon=True).start()
    print('Preview: http://127.0.0.1:8768',flush=True)
    server.serve_forever()
