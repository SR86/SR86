"""Isolated storage and scheduling tests. Never calls a model or deletes real outputs."""
import datetime as dt
from pathlib import Path
import tempfile
import io
import unittest
from unittest.mock import patch
import control
import executor
import history
import automation
import codejobs
import threading
import urllib.request
import console_server
import task_delete

class ManagementTests(unittest.TestCase):
    def test_revision_preserves_code_target_and_long_feedback(self):
        ident=control.create_task({'title':'copy','prompt':'original '*750,'paper':'','kind':'coding','target':'station_copy'})
        folder=executor.RESULTS/ident;folder.mkdir(parents=True);(folder/'reading.md').write_text('old result '*30)
        with control.connect() as db:db.execute("UPDATE tasks SET status='completed' WHERE id=?",(ident,))
        revision=control.create_revision({'id':ident,'feedback':'feedback '*650})
        with control.connect() as db:
            self.assertEqual(db.execute('SELECT target FROM code_targets WHERE task_id=?',(revision,)).fetchone()[0],'station_copy')
            self.assertGreater(len(db.execute('SELECT prompt FROM tasks WHERE id=?',(revision,)).fetchone()[0]),10000)

    def test_legacy_budget_is_preserved_on_migration(self):
        with control.connect() as db:db.execute('INSERT INTO budgets VALUES(1,?,?)',(1000,29))
        at=dt.datetime(2026,11,18,10,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        with patch.object(control,'now',return_value=at):
            self.assertEqual(executor.charge({'usedPercent':50,'resetsAt':3000,'windowId':3000}),29)

    def test_eta_drift_does_not_reset_budget_or_trigger_scheduled_job(self):
        at=dt.datetime(2026,11,18,10,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        q={'resetsAt':2000000000,'usedPercent':10,'windowId':1000,'windowResetAt':2000000000}
        with patch.object(control,'now',return_value=at):
            executor.charge(q)
            self.assertEqual(executor.charge(dict(q,resetsAt=2000000120,usedPercent=25),q),15)
            self.assertEqual(executor.charge(dict(q,resetsAt=2000000240,usedPercent=40),dict(q,resetsAt=2000000120,usedPercent=25)),30)
            self.assertEqual(executor.charge(dict(q,resetsAt=2000018000,usedPercent=0,windowId=2000)),0)
        with patch.object(executor,'quota',return_value=q):
            ident=automation.create({'title':'test','prompt':'test','kind':'general','trigger':'after_reset'})
        automation.set_enabled(True)
        with patch.object(control,'now',return_value=at),patch.object(executor,'start') as start,patch.object(executor,'quota',return_value=dict(q,resetsAt=2000000120)):
            automation.tick();start.assert_not_called()
        with patch.object(control,'now',return_value=at),patch.object(executor,'start') as start,patch.object(executor,'quota',return_value=dict(q,windowId=2000)):
            automation.tick();start.assert_called_once_with(ident)

    def test_invalid_task_transition_is_explicit(self):
        ident,_=self.task('running')
        with self.assertRaises(ValueError):control.transition_task(ident,'cancel')
        with self.assertRaises(ValueError):control.transition_task('absent','queue')
        with control.connect() as db:self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=?',(ident,)).fetchone()[0],'running')

    def test_concurrent_reading_reminders_claim_one_slot(self):
        control.save_settings({'reminders_enabled':True,'reminder_times':['09:00','14:00','19:30']})
        at=dt.datetime(2026,11,18,9,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        entered=threading.Event();release=threading.Event();sent=[]
        def sender(title,body):sent.append(title);entered.set();release.wait(5)
        worker=threading.Thread(target=control.tick,kwargs={'at':at,'sender':sender});worker.start()
        try:
            self.assertTrue(entered.wait(5))
            control.tick(at=at,sender=lambda *args:sent.append('duplicate'))
        finally:release.set();worker.join()
        self.assertEqual(len(sent),1)

    def test_quota_failure_pauses_without_submitting_model(self):
        ident=automation.create({'title':'test','prompt':'test','kind':'general','paper':'','trigger':'manual'})
        with control.connect() as db:task=dict(db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())
        with patch.object(executor,'quota',side_effect=TimeoutError),patch.object(executor.subprocess,'Popen') as model:
            executor.run_stage(task)
            model.assert_not_called()
        with control.connect() as db:row=db.execute('SELECT * FROM runs WHERE task_id=?',(ident,)).fetchone()
        self.assertEqual(row['status'],'paused')
        self.assertIn('保护预算',row['note'])

    def test_progress_updates_preserve_start_time(self):
        ident,_=self.task('queued')
        at=dt.datetime(2026,11,17,19,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        with patch.object(control,'now',return_value=at):executor.status(ident,'running','begin')
        later=at+dt.timedelta(minutes=2)
        with patch.object(control,'now',return_value=later):
            executor.status(ident,'running','progress')
            executor.status(ident,'failed','end')
        with control.connect() as db:row=db.execute('SELECT * FROM runs WHERE task_id=?',(ident,)).fetchone()
        self.assertEqual(row['started'],at.isoformat())
        self.assertEqual(row['finished'],later.isoformat())

    def test_delete_paused_task_only_after_confirmation(self):
        ident,path=self.task('paused');other,other_path=self.task('running')
        with control.connect() as db:
            db.execute('INSERT INTO automation_commands VALUES(?,?,?,?,?,?)',(ident,'immediate','',0,'held','test'))
            db.execute('INSERT OR REPLACE INTO budgets VALUES(1,?,?)',(2000000000,12))
        with self.assertRaises(ValueError):task_delete.preview(other)
        with self.assertRaises(ValueError):task_delete.preview(ident,ident)
        with self.assertRaises(ValueError):task_delete.preview('../escape')
        plan=task_delete.preview(ident)
        with self.assertRaises(ValueError):task_delete.commit(plan['token'],False)
        (path/'reading.md').write_text('changed after preview')
        with self.assertRaises(ValueError):task_delete.commit(plan['token'],True)
        plan=task_delete.preview(ident)
        with control.connect() as db:db.execute("UPDATE tasks SET status='running' WHERE id=?",(ident,))
        with self.assertRaises(ValueError):task_delete.commit(plan['token'],True)
        with control.connect() as db:db.execute("UPDATE tasks SET status='paused' WHERE id=?",(ident,))
        plan=task_delete.preview(ident)
        self.assertEqual(task_delete.commit(plan['token'],True)['removed'],ident)
        self.assertFalse(path.exists());self.assertTrue(other_path.exists());self.assertTrue((control.PAPERS/'paper.pdf').exists())
        with control.connect() as db:
            self.assertIsNone(db.execute('SELECT id FROM tasks WHERE id=?',(ident,)).fetchone())
            self.assertIsNone(db.execute('SELECT task_id FROM automation_commands WHERE task_id=?',(ident,)).fetchone())
            self.assertEqual(db.execute('SELECT spent FROM budgets WHERE id=1').fetchone()[0],12)
    def test_night_budget_separate_and_day_threshold_restored(self):
        at=dt.datetime(2026,11,17,1,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        q={'resetsAt':2000000000,'usedPercent':10,'_period':'night'}
        with patch.object(control,'now',return_value=at):
            executor.charge(q)
            spent=executor.charge(dict(q,usedPercent=80),q)
            self.assertEqual(spent,70)
            self.assertFalse(executor.budget_reached(80,spent))
            self.assertTrue(executor.budget_reached(100,spent))
        with patch.object(control,'now',return_value=at.replace(hour=7)):
            self.assertEqual(executor.charge(dict(q,usedPercent=81,_period='day'),dict(q,usedPercent=80)),0)
            self.assertTrue(executor.budget_reached(85,30))
            self.assertFalse(executor.budget_reached(85,29))
    def test_coding_without_paper_and_real_files_required(self):
        ident=automation.create({'title':'网站','prompt':'创建网站','kind':'coding','paper':'','trigger':'manual','target':'new_site'})
        with control.connect() as db:task=dict(db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())
        attempt=control.PROJECT/'attempt';attempt.mkdir()
        task.update(_output_folder=str(attempt),_previous_notes='',_stage_instruction='当前阶段 1/3：最小实现')
        q={'resetsAt':2000000000,'usedPercent':10};captured=[]
        def fake_process(args,**kwargs):
            self.assertEqual(args[args.index('--sandbox')+1],'workspace-write')
            self.assertIn('windows.sandbox="elevated"',args)
            self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
            project=Path(args[args.index('-C')+1]);self.assertTrue(project.is_relative_to(control.PROJECT))
            (project/'index.html').write_text('<!doctype html><title>Test</title><h1>测试网站</h1>',encoding='utf-8')
            Path(args[args.index('-o')+1]).write_text('实际创建 index.html，检查标题与页面结构。'*25,encoding='utf-8')
            class Process:
                stdin=io.StringIO();stdout=io.StringIO('{"type":"turn.completed"}\n');returncode=0
                def poll(self):return 0
                def wait(self,timeout=None):return 0
            return Process()
        at=dt.datetime(2026,11,17,1,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        with patch.object(executor,'quota',return_value=q),patch.object(executor,'PdfReader') as pdf,patch.object(executor.subprocess,'Popen',side_effect=fake_process),patch.object(control,'now',return_value=at):
            executor.STOP.clear();executor.run_stage(task);pdf.assert_not_called()
        with control.connect() as db:self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=?',(ident,)).fetchone()[0],'running')
        self.assertEqual(codejobs.summary(ident)['preview'],'index.html')
        self.assertTrue(codejobs.archive(ident).startswith(b'PK'))
        with self.assertRaises(ValueError):codejobs.static_file(ident,'../../control.sqlite3')
        self.assertTrue((attempt/'project-snapshot.zip').exists())
        server=console_server.ThreadingHTTPServer(('127.0.0.1',0),console_server.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            req=urllib.request.Request(base+'/site/'+ident+'/index.html',headers={'Host':'127.0.0.1:8768'})
            with opener.open(req,timeout=5) as r:
                self.assertIn('sandbox allow-scripts',r.headers['Content-Security-Policy'])
                self.assertIn('connect-src \'none\'',r.headers['Content-Security-Policy'])
                self.assertIn(b'Test',r.read())
            req=urllib.request.Request(base+'/api/project-zip/'+ident,headers={'Host':'127.0.0.1:8768'})
            with opener.open(req,timeout=5) as r:self.assertTrue(r.read().startswith(b'PK'))
        finally:server.shutdown();server.server_close()
    def test_general_command_without_paper_and_execution(self):
        with patch.object(control,'papers',return_value=[]):
            ident=automation.create({'title':'学习计划','prompt':'制定一周学习计划','trigger':'manual','paper':''})
        with control.connect() as db:task=dict(db.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone())
        self.assertEqual(task['kind'],'general');self.assertEqual(task['paper'],'')
        folder=control.PROJECT/'attempt';folder.mkdir()
        task.update(_output_folder=str(folder),_stage_instruction='生成学习计划',_previous_notes='已完成目标分析')
        prompts=[]
        class Sink(io.StringIO):
            def write(self,text):prompts.append(text);return super().write(text)
        def fake_process(args,**kwargs):
            Path(args[args.index('-o')+1]).write_text('一周学习计划：按天分配任务与检查标准。'*30,encoding='utf-8')
            class Process:
                stdin=Sink();stdout=io.StringIO('{"type":"turn.completed"}\n');returncode=0
                def poll(self):return 0
                def wait(self,timeout=None):return 0
            return Process()
        q={'resetsAt':2000000000,'usedPercent':10}
        at=dt.datetime(2026,11,17,10,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        with patch.object(executor,'quota',return_value=q),patch.object(executor,'PdfReader') as pdf,patch.object(executor.subprocess,'Popen',side_effect=fake_process),patch.object(control,'now',return_value=at):
            executor.STOP.clear();executor.run_stage(task);pdf.assert_not_called()
        self.assertIn('通用文字任务',prompts[0]);self.assertIn('已完成目标分析',prompts[0])
        self.assertTrue((folder/'reading.html').exists())
        with control.connect() as db:self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=?',(ident,)).fetchone()[0],'running')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        self.patches=[patch.object(control,'PROJECT',root),patch.object(control,'DB',root/'test.sqlite3'),
                      patch.object(control,'PAPERS',root/'papers'),patch.object(executor,'RESULTS',root/'results')]
        for p in self.patches:p.start()
        control.PAPERS.mkdir();(control.PAPERS/'paper.pdf').write_bytes(b'paper original')
        control.init();executor.init();history.init();automation.init();history.PREVIEWS.clear()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def task(self,status='completed'):
        ident=control.create_task({'title':'test','prompt':'test reading','paper':'paper.pdf','kind':'paper_reading'})
        with control.connect() as db:db.execute('UPDATE tasks SET status=? WHERE id=?',(status,ident))
        path=executor.RESULTS/ident;path.mkdir(parents=True);(path/'reading.md').write_text('test output')
        return ident,path
    def test_archive_preview_cleanup_and_protection(self):
        done,path=self.task();active,active_path=self.task('running')
        history.archive_completed(active)
        self.assertFalse(path.exists());self.assertTrue(history.folder(done).is_file() is False)
        self.assertTrue((history.folder(done)/'reading.md').exists())
        with self.assertRaises(ValueError):history.preview([active],active)
        with self.assertRaises(ValueError):history.preview(['../escape'],active)
        plan=history.preview([done],active)
        (history.folder(done)/'reading.md').write_text('changed output after preview')
        with self.assertRaises(ValueError):history.commit(plan['token'],True,active)
        plan=history.preview([done],active)
        with self.assertRaises(ValueError):history.commit(plan['token'],False,active)
        self.assertEqual(history.commit(plan['token'],True,active)['removed'],[done])
        self.assertTrue(active_path.exists());self.assertTrue((control.PAPERS/'paper.pdf').exists())
        with control.connect() as db:self.assertIsNotNone(db.execute('SELECT id FROM tasks WHERE id=?',(done,)).fetchone())
    def test_retention_cap_and_disabled_by_default(self):
        ident,path=self.task()
        with (path/'large.bin').open('wb') as f:f.truncate(17*1024*1024)
        history.maintenance();self.assertTrue(history.folder(ident).exists())
        history.set_policy({'enabled':True,'days':30,'max_mb':16,'confirm':True})
        history.maintenance();self.assertFalse(history.folder(ident).exists())
    def test_command_switch_time_quota_trigger_and_hold(self):
        q={'resetsAt':2000000000,'usedPercent':10}
        with patch.object(executor,'quota',return_value=q):
            ident=automation.create({'title':'test','prompt':'read paper','paper':'paper.pdf','trigger':'after_reset'})
        at=dt.datetime(2026,11,17,10,tzinfo=dt.timezone(dt.timedelta(hours=8)))
        with patch.object(control,'now',return_value=at),patch.object(executor,'start') as start,patch.object(executor,'quota',return_value=q):
            automation.tick();start.assert_not_called()
            automation.set_enabled(True);automation.tick();start.assert_not_called()
        with patch.object(control,'now',return_value=at),patch.object(executor,'start') as start,patch.object(executor,'quota',return_value=dict(q,resetsAt=2000018000)):
            automation.tick();start.assert_called_once_with(ident)
        automation.hold(ident)
        self.assertEqual(automation.snapshot()['commands'][0]['state'],'held')
        with self.assertRaises(ValueError):automation.create({'prompt':'read','paper':'paper.pdf','trigger':'at_time','run_at':'invalid'})

if __name__=='__main__':unittest.main()
