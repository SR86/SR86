"""Quota ETA drift, restart and concurrency regressions; never sends a message."""
import concurrent.futures
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch
import executor

spec=importlib.util.spec_from_file_location('quota_store',Path(__file__).resolve().parent.parent/'quota-notifier'/'quota_store.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def window(used,reset):
    return {'bucket':'codex','window':'primary','usedPercent':used,'resetsAt':reset}


class QuotaNotificationTests(unittest.TestCase):
    def test_monitor_check_uses_confirmed_events_and_receipts(self):
        reader=executor.transport()
        state=Path(self.temp.name)/'state.json'
        def response(used,reset):return {'rateLimits':{'primary':{'usedPercent':used,'resetsAt':reset,'windowDurationMins':300}}}
        with patch.object(reader,'STATE',state),patch.object(reader,'store',return_value=self.store),patch.object(reader,'_deliver') as deliver:
            for at,used,reset in [(100,0,1000),(220,0,1120),(500,50,1500),(1001,0,2000),(1121,0,2120)]:
                with patch.object(reader.time,'time',return_value=at),patch.object(reader,'read_limits',return_value=response(used,reset)):
                    reader.check()
            self.assertEqual(deliver.call_count,1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'quota.sqlite3'
        self.store=module.Store(self.path)

    def tearDown(self):self.temp.cleanup()

    def test_idle_100_percent_never_spams_even_when_eta_keeps_moving(self):
        initial=self.store.observe([window(0,18000)],at=0)[0]['windowId']
        for i in range(1,110):
            observed=self.store.observe([window(0,18000+120*i)],at=120*i)[0]
            self.assertEqual(observed['windowId'],initial)
        self.assertEqual(self.store.pending_refreshes(at=13200),[])

    def test_capacity_recovery_and_stable_boundary_required(self):
        initial=self.store.observe([window(40,1000)],at=100)[0]['windowId']
        moved=self.store.observe([window(60,1300)],at=200)[0]
        self.assertEqual(moved['windowId'],initial)
        self.store.observe([window(0,1800)],at=900)
        self.assertEqual(self.store.pending_refreshes(at=900),[])
        recovered=self.store.observe([window(0,2000)],at=1001)[0]
        self.assertGreater(recovered['windowId'],initial)
        self.assertEqual(len(self.store.pending_refreshes(at=1001)),1)
        restarted=module.Store(self.path)
        restarted.observe([window(0,2200)],at=1200)
        self.assertEqual(len(restarted.pending_refreshes(at=1200)),1)

    def test_deadline_passed_without_capacity_recovery_is_not_a_reset(self):
        initial=self.store.observe([window(50,1000)],at=100)[0]['windowId']
        later=self.store.observe([window(65,2000)],at=1100)[0]
        self.assertEqual(later['windowId'],initial)
        self.assertEqual(self.store.pending_refreshes(at=1100),[])

    def test_parallel_senders_and_restarts_deliver_one_time(self):
        calls=[]; lock=threading.Lock()
        def deliver():
            with lock:calls.append(1)
        def send(_):return module.Store(self.path).send_once('same-event',deliver)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(send,range(16)))
        self.assertEqual(len(calls),1)
        self.assertEqual(results.count('accepted'),1)
        self.assertEqual(module.Store(self.path).send_once('same-event',deliver),'suppressed')

    def test_ambiguous_timeout_is_not_replayed(self):
        calls=[]
        def deliver():calls.append(1);raise TimeoutError('response lost after acceptance')
        with self.assertRaises(TimeoutError):self.store.send_once('event',deliver)
        self.assertEqual(module.Store(self.path).send_once('event',deliver),'suppressed')
        self.assertEqual(len(calls),1)

    def test_definite_connection_refusal_has_only_three_attempts(self):
        def deliver():raise urllib.error.URLError(ConnectionRefusedError())
        for _ in range(3):
            with self.assertRaises(urllib.error.URLError):self.store.send_once('event',deliver)
        self.assertEqual(self.store.send_once('event',deliver),'suppressed')


if __name__=='__main__':unittest.main()
