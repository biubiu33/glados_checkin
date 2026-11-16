import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import browser_checkin
import checkin


class BrowserCheckinTest(unittest.TestCase):
    def setUp(self):
        engine = patch.object(browser_checkin, "sync_playwright")
        self.engine = engine.start()
        self.addCleanup(engine.stop)
        self.browser = self.engine.return_value.__enter__.return_value.chromium.launch.return_value
        self.context = self.browser.new_context.return_value
        self.context.request.get.return_value.json.return_value = {"code": 0}
        self.page = self.context.new_page.return_value
        pending = self.page.expect_response.return_value.__enter__.return_value
        pending.value.request.post_data_json = {"tsState": "off"}
        pending.value.json.return_value = {"code": 0, "list": [{"balance": "89"}]}

    def test_uses_normal_website_button_and_session(self):
        result = browser_checkin.submit_browser("gld:sess=abc==; gld:sess.sig=signature;", "test-browser")
        self.assertEqual(result["code"], 0)
        self.engine.return_value.__enter__.return_value.chromium.launch.assert_called_once_with(headless=False)
        self.context.add_cookies.assert_called_once_with([
            {"name": "gld:sess", "value": "abc==", "url": "https://glados.cloud"},
            {"name": "gld:sess.sig", "value": "signature", "url": "https://glados.cloud"},
        ])
        self.page.get_by_role.assert_called_once_with("button", name="Checkin", exact=True)
        self.browser.close.assert_called_once()

    def test_invalid_cookie_fails_before_browser_launch(self):
        with self.assertRaises(checkin.CheckinError):
            browser_checkin.submit_browser("invalid-cookie", "test-browser")
        self.engine.assert_not_called()

    def test_verification_diagnostics_hide_token(self):
        pending = self.page.expect_response.return_value.__enter__.return_value
        pending.value.request.post_data_json = {"tsState": "ok", "turnstile": "private-token"}
        output = io.StringIO()
        with redirect_stdout(output):
            browser_checkin.submit_browser("gld:sess=test", "test-browser")
        self.assertIn("状态=ok", output.getvalue())
        self.assertIn("令牌=True", output.getvalue())
        self.assertNotIn("private-token", output.getvalue())

    def test_expired_session_closes_browser_without_checkin(self):
        self.context.request.get.return_value.json.return_value = {"code": -2}
        with self.assertRaises(checkin.CheckinError):
            browser_checkin.submit_browser("gld:sess=test", "test-browser")
        self.context.new_page.assert_not_called()
        self.browser.close.assert_called_once()

    def test_waits_only_for_checkin_post_response(self):
        browser_checkin.submit_browser("gld:sess=test", "test-browser")
        predicate = self.page.expect_response.call_args.args[0]
        response = MagicMock(url=checkin.CHECKIN_URL)
        response.request.method = "POST"
        self.assertTrue(predicate(response))
        response.request.method = "GET"
        self.assertFalse(predicate(response))
        response.url = checkin.CHECKIN_URL + "/challenge"
        self.assertFalse(predicate(response))

    @patch.dict(os.environ, {"COOKIE": "gld:sess=test", "SERVE": "off"}, clear=True)
    @patch.object(checkin, "load_config", return_value={})
    def test_turnstile_rejection_remains_failure(self, config):
        self.page.expect_response.return_value.__enter__.return_value.value.json.return_value = {
            "code": 5, "reason": "turnstile",
        }
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertFalse(browser_checkin.start_browser())
        self.assertIn("Cloudflare Turnstile", output.getvalue())

    def test_browser_error_closes_browser(self):
        self.page.goto.side_effect = browser_checkin.BrowserError("private-value")
        with self.assertRaises(browser_checkin.BrowserError):
            browser_checkin.submit_browser("gld:sess=test", "test-browser")
        self.browser.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
