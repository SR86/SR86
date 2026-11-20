"""Regression checks without any model calls or changes to real tasks."""
import io
import queue
import unittest
from unittest.mock import patch
import executor
import codejobs
from execution_health import checked_quota, QuotaUnavailable, Diagnostics


class ExecutionHealthTests(unittest.TestCase):
    def test_successful_progress_clears_old_warning_but_retains_history(self):
        d=Diagnostics();d.error('stream disconnected')
        self.assertIsNotNone(d.snapshot()['recent_error'])
        d.observe({'type':'item.completed','item':{'type':'agent_message'}})
        self.assertIsNone(d.snapshot()['recent_error'])
        self.assertTrue(d.snapshot()['errors'])
    def test_status_markdown_is_not_a_website(self):
        self.assertFalse(codejobs.has_implementation({'LOCAL_IMPLEMENTATION_STATUS.md':'hash'}))
        self.assertTrue(codejobs.has_implementation({'index.html':'hash'}))

    def test_registered_runtime_requires_real_windows_package_identity(self):
        reader=executor.transport()
        with patch.object(reader,'current_package_family',return_value=None):
            self.assertNotIn('CODEX_WINDOWS_REGISTERED_CORE',reader.codex_environment({},{}))
        with patch.object(reader,'current_package_family',return_value='OpenAI.Codex_2p2nqsd0c76g0'):
            env=reader.codex_environment({}, {})
            self.assertEqual(env['CODEX_WINDOWS_REGISTERED_CORE'],'1')
            self.assertEqual(env['CODEX_WINDOWS_SANDBOX_PACKAGE_FAMILY'],'OpenAI.Codex_2p2nqsd0c76g0')

    def test_retry_quota_read_only(self):
        calls = []
        def read():
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError('QuotaReadTimeout')
            return {'usedPercent': 8}
        self.assertEqual(checked_quota(read), {'usedPercent': 8})
        self.assertEqual(len(calls), 2)

    def test_unreadable_quota_is_bounded_and_explained(self):
        with patch('execution_health.time.monotonic', return_value=0):
            from unittest.mock import Mock
            read = Mock(side_effect=queue.Empty)
            with self.assertRaisesRegex(QuotaUnavailable, '已暂停以保护预算'):
                checked_quota(read)
            self.assertEqual(read.call_count, 2)

    def test_reader_translates_queue_timeout(self):
        reader = executor.transport()
        class EmptyQueue:
            def get(self, **kwargs): raise queue.Empty
            def put(self, value): pass
        class Process:
            stdin = io.StringIO()
            stdout = io.StringIO()
            def terminate(self): pass
            def wait(self, **kwargs): pass
        with patch.object(reader.subprocess, 'Popen', return_value=Process()), patch.object(reader.queue, 'Queue', EmptyQueue):
            with self.assertRaisesRegex(TimeoutError, 'QuotaReadTimeout'):
                reader.read_limits(timeout=.01)

    def test_existing_local_proxy_is_inherited_without_global_change(self):
        reader = executor.transport()
        original = {'PATH': 'keep'}
        child = reader.codex_environment(original, {'http': 'http://127.0.0.1:7897'})
        self.assertEqual(child['HTTPS_PROXY'], 'http://127.0.0.1:7897')
        self.assertIn('localhost', child['NO_PROXY'])
        self.assertEqual(original, {'PATH': 'keep'})
        explicit = {'HTTPS_PROXY': 'http://localhost:9999'}
        self.assertEqual(reader.codex_environment(explicit, {'http': 'http://127.0.0.1:7897'}), explicit)
        self.assertNotIn('HTTPS_PROXY', reader.codex_environment({}, {'http': 'http://external.invalid:8080'}))
        self.assertNotIn('HTTPS_PROXY', reader.codex_environment({}, {'http': 'http://user:secret@127.0.0.1:7897'}))

    def test_diagnostics_never_copy_secrets(self):
        diagnostics = Diagnostics()
        diagnostics.observe({'type': 'thread.started', 'thread_id': 'private-id'})
        diagnostics.observe({'type': 'item.completed', 'item': {'text': 'private document'}})
        diagnostics.observe({'type': 'turn.failed', 'error': {'message': 'stream disconnected: Authorization=private-token'}})
        data = str(diagnostics.snapshot())
        self.assertNotIn('private', data)
        self.assertTrue(diagnostics.snapshot()['failed'])
        self.assertIn('连接服务失败', diagnostics.failure())

    def test_runtime_provisioning_error_is_explained(self):
        diagnostics = Diagnostics()
        diagnostics.observe({'type':'item.completed','item':{'type':'command_execution','exit_code':1,
            'aggregated_output':'app runtime provisioning service is unavailable; private-path'}})
        self.assertIn('沙箱未就绪', diagnostics.failure())
        self.assertNotIn('private-path', str(diagnostics.snapshot()))


if __name__ == '__main__': unittest.main()
