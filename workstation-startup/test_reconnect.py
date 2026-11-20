"""Simulated outages only; never changes the real network or reads credentials."""
import unittest
from unittest.mock import Mock,patch
import campus_login
from network_watchdog import Recovery
import network_check
import tempfile
from pathlib import Path
from network_watchdog import RepairLauncher,check_interval


class RecoveryTests(unittest.TestCase):
    def test_hourly_healthy_short_outage_interval(self):
        self.assertEqual(check_interval('online'),3600)
        for state in ('retry_wait','cooldown','confirming_outage'):
            self.assertEqual(check_interval(state),20)

    def test_repair_launch_is_limited_across_restarts(self):
        with tempfile.TemporaryDirectory() as folder, patch('network_watchdog.REPAIR_EXE') as exe:
            exe.is_file.return_value=True
            launch=Mock();root=Path(folder)
            self.assertEqual(RepairLauncher(root,launch).run(10000),'assistant_open_requested')
            self.assertEqual(RepairLauncher(root,launch).run(10020),'rate_limited')
            self.assertEqual(launch.call_count,1)
            self.assertEqual(RepairLauncher(root,launch).run(13600),'assistant_open_requested')
            self.assertEqual(launch.call_count,2)

    def test_failed_or_missing_assistant_never_claims_repair(self):
        with tempfile.TemporaryDirectory() as folder, patch('network_watchdog.REPAIR_EXE') as exe:
            exe.is_file.return_value=False;launch=Mock()
            r=RepairLauncher(Path(folder),launch)
            self.assertEqual(r.run(10000),'assistant_missing');launch.assert_not_called()
            exe.is_file.return_value=True;launch.side_effect=OSError()
            self.assertEqual(r.run(10000),'assistant_launch_failed')
            self.assertEqual(r.run(10020),'rate_limited')

    def test_online_never_authenticates(self):
        login=Mock();r=Recovery()
        for t in range(0,120,20):r.step(True,True,t,login)
        login.assert_not_called();self.assertEqual(r.state,'online')

    def test_short_outage_does_not_submit_login(self):
        login=Mock();r=Recovery();r.step(False,True,0,login);r.step(True,True,20,login)
        login.assert_not_called()

    def test_confirmed_outage_recovers_and_next_outage_is_detected(self):
        login=Mock(return_value=0);r=Recovery()
        for t in (0,20):r.step(False,True,t,login)
        self.assertEqual(r.state,'online');self.assertEqual(login.call_count,1)
        for t in (40,60):r.step(False,True,t,login)
        self.assertEqual(login.call_count,2)

    def test_physical_or_campus_network_unavailable_does_not_authenticate(self):
        login=Mock();r=Recovery()
        for t in range(0,100,20):r.step(False,False,t,login)
        login.assert_not_called();self.assertEqual(r.state,'waiting_for_campus_network')
        login.return_value=0;r.step(False,True,120,login);login.assert_called_once()

    def test_three_failures_then_cooldown(self):
        login=Mock(return_value=1);r=Recovery()
        for t in (0,20,40,60,100,181):r.step(False,True,t,login)
        self.assertEqual(login.call_count,3);self.assertEqual(r.state,'cooldown')
        for t in (200,500,1000):r.step(False,True,t,login)
        self.assertEqual(login.call_count,3)
        r.step(False,True,1100,login);self.assertEqual(login.call_count,4)

    def test_retry_delay_starts_after_authentication_finishes(self):
        login=Mock(return_value=1);r=Recovery();r.step(False,True,0,login)
        with patch('network_watchdog.time.monotonic',side_effect=[0,100,100,100]):
            r.step(False,True,20,login)
            r.step(False,True,100,login);self.assertEqual(login.call_count,1)
            r.step(False,True,160,login);self.assertEqual(login.call_count,2)

    def test_authentication_uses_existing_form_and_verifies_network(self):
        account,pwd,agreement,submit=[Mock() for _ in range(4)]
        for locator in (account,pwd,agreement,submit):locator.count.return_value=1
        with patch('keyring.get_password',side_effect=['test-account','test-only-secret']),patch('playwright.sync_api.sync_playwright') as playwright:
            engine=playwright.return_value.__enter__.return_value
            browser=engine.chromium.launch.return_value;page=browser.new_page.return_value
            page.locator.side_effect=[account,pwd,agreement,submit]
            check=Mock(side_effect=[False,False,True])
            self.assertEqual(campus_login.authenticate(check=check),'online')
            submit.click.assert_called_once();agreement.check.assert_called_once();browser.close.assert_called_once()
            self.assertTrue(engine.chromium.launch.call_args.kwargs['headless'])
            self.assertIn('--no-proxy-server',engine.chromium.launch.call_args.kwargs['args'])

    def test_unrecognized_login_form_is_not_submitted(self):
        with patch('keyring.get_password',return_value='test-only'),patch('playwright.sync_api.sync_playwright') as playwright:
            browser=playwright.return_value.__enter__.return_value.chromium.launch.return_value
            page=browser.new_page.return_value;page.locator.return_value.count.return_value=0
            self.assertEqual(campus_login.authenticate(check=lambda:False),'form_unrecognized')
            page.locator.return_value.fill.assert_not_called();page.locator.return_value.click.assert_not_called()

    def test_bad_credentials_or_changed_form_stops_retrying(self):
        for code in (2,3,4):
            r=Recovery();login=Mock(return_value=code)
            for t in (0,20,2000):r.step(False,True,t,login)
            self.assertEqual(login.call_count,1);self.assertEqual(r.state,'authentication_blocked')

    def test_already_online_login_does_not_read_keyring(self):
        self.assertEqual(campus_login.authenticate(check=lambda:True),'already_online')

    def test_portal_redirect_is_not_a_connectivity_success(self):
        opener=Mock();opener.open.side_effect=OSError('offline')
        with patch.object(network_check.urllib.request,'build_opener',return_value=opener):
            self.assertFalse(network_check.is_online())
            self.assertEqual(opener.open.call_count,2)


if __name__=='__main__':unittest.main()
