import hashlib
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import requests

import checkin


def response(data):
    result = Mock()
    result.json.return_value = data
    return result


class CheckinTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"COOKIE": "test-cookie", "SERVE": "off"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        config = patch.object(checkin, "load_config", return_value={})
        config.start()
        self.addCleanup(config.stop)
        sleep = patch.object(checkin.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        self.session = Mock()
        self.reset_responses()

    def reset_responses(self):
        self.session.get.side_effect = [
            response({"code": 0, "nonce": "test-nonce", "ttl": 300000}),
            response({"code": 0, "data": {"leftDays": "30.5"}}),
        ]
        self.session.post.return_value = response({
            "code": 0, "message": "Checkin! Got 5 points", "list": [{"balance": "10.5"}],
        })

    def run_checkin(self):
        output = io.StringIO()
        with redirect_stdout(output):
            result = checkin.start(self.session)
        return result, output.getvalue()

    def test_local_config_is_used_when_environment_is_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(checkin.setting("COOKIE", {"COOKIE": "file-cookie"}), "file-cookie")

    def test_environment_overrides_config(self):
        self.assertEqual(checkin.setting("COOKIE", {"COOKIE": "file-cookie"}), "test-cookie")

    def test_success_sends_challenge_proof_and_waits(self):
        result, output = self.run_checkin()
        self.assertTrue(result)
        self.assertIn("30 days left and 10 points", output)
        self.sleep.assert_called_once_with(checkin.CHALLENGE_DELAY)
        self.session.post.assert_called_once_with(
            checkin.CHECKIN_URL,
            headers=checkin.request_headers("test-cookie", content_type=True),
            json={
                "token": "glados.cloud", "nonce": "test-nonce",
                "proof": hashlib.sha256(b"test-nonce.glados-observe-v1").hexdigest(),
            },
            timeout=checkin.TIMEOUT,
        )

    def test_custom_browser_user_agent_is_used_for_every_request(self):
        with patch.dict(os.environ, {"USER_AGENT": "Windows-test-browser"}):
            self.assertTrue(self.run_checkin()[0])
        for call in self.session.get.call_args_list + self.session.post.call_args_list:
            self.assertEqual(call.kwargs["headers"]["user-agent"], "Windows-test-browser")

    def test_local_user_agent_is_used(self):
        with patch.object(checkin, "load_config", return_value={"USER_AGENT": "local-browser"}):
            self.assertTrue(self.run_checkin()[0])
        self.assertEqual(self.session.post.call_args.kwargs["headers"]["user-agent"], "local-browser")

    def test_device_mismatch_fails_without_reading_account_status(self):
        self.session.post.return_value = response({"code": 4, "reason": "device-mismatch"})
        result, output = self.run_checkin()
        self.assertFalse(result)
        self.assertIn("USER_AGENT", output)
        self.assertEqual(self.session.get.call_count, 1)

    def test_expired_session_does_not_submit_checkin(self):
        self.session.get.side_effect = [response({"code": -2, "message": "没有权限"})]
        result, output = self.run_checkin()
        self.assertFalse(result)
        self.assertIn("没有权限", output)
        self.session.post.assert_not_called()

    def test_repeated_checkin_is_success(self):
        self.session.post.return_value = response({
            "code": 1, "message": "Checkin Repeats! Please Try Tomorrow",
        })
        result, output = self.run_checkin()
        self.assertTrue(result)
        self.assertIn("今日已签到", output)

    def test_business_rejection_does_not_report_success(self):
        self.session.post.return_value = response({"code": 4, "message": "rejected"})
        self.assertFalse(self.run_checkin()[0])

    def test_success_with_missing_or_malformed_points_is_supported(self):
        for items in (None, [], {}, "invalid", [None]):
            with self.subTest(items=items):
                self.reset_responses()
                self.session.post.return_value = response({"code": 0, "list": items})
                self.assertTrue(self.run_checkin()[0])

    def test_status_failure_preserves_confirmed_checkin_success(self):
        self.session.get.side_effect = [
            response({"code": 0, "nonce": "test-nonce"}),
            response({"code": -2, "message": "未登录"}),
        ]
        result, output = self.run_checkin()
        self.assertTrue(result)
        self.assertIn("账户信息查询失败", output)

    def test_network_error_does_not_leak_exception_secrets(self):
        self.session.get.side_effect = requests.ConnectionError("secret-cookie-value")
        result, output = self.run_checkin()
        self.assertFalse(result)
        self.assertIn("ConnectionError", output)
        self.assertNotIn("secret-cookie-value", output)

    def test_invalid_challenges_never_submit(self):
        for fields in (
            {"nonce": None}, {"nonce": ""}, {"nonce": "a", "ttl": 100},
            {"nonce": "a", "ttl": float("nan")}, {"nonce": "a", "ttl": True},
            {"nonce": "a", "ttl": "300000"},
        ):
            with self.subTest(fields=fields):
                self.session.get.side_effect = [response({"code": 0, **fields})]
                self.assertFalse(self.run_checkin()[0])
                self.session.post.assert_not_called()

    def test_challenge_expiring_during_wait_never_submits(self):
        with patch.object(checkin.time, "monotonic", side_effect=[0, 301]):
            self.assertFalse(self.run_checkin()[0])
        self.session.post.assert_not_called()

    def test_invalid_json_response_fails(self):
        self.session.get.side_effect = [response([])]
        self.assertFalse(self.run_checkin()[0])
        self.session.post.assert_not_called()

    def test_notification_failure_preserves_signin_result_and_hides_key(self):
        with patch.dict(os.environ, {"SERVE": "on", "SCKEY": "secret-send-key"}):
            with patch.object(requests, "post", side_effect=requests.Timeout("secret-send-key")):
                result, output = self.run_checkin()
        self.assertTrue(result)
        self.assertIn("通知失败", output)
        self.assertNotIn("secret-send-key", output)

    def test_http_failure_never_submits(self):
        failed = response({})
        failed.raise_for_status.side_effect = requests.HTTPError("401")
        self.session.get.side_effect = [failed]
        self.assertFalse(self.run_checkin()[0])
        self.session.post.assert_not_called()

    def test_missing_cookie_never_requests(self):
        with patch.dict(os.environ, {"COOKIE": ""}):
            self.assertFalse(self.run_checkin()[0])
        self.session.get.assert_not_called()
        self.session.post.assert_not_called()

    def test_rejection_cannot_be_overridden_by_success_fields(self):
        for payload in (
            {"code": 0, "reason": "device-mismatch"},
            {"code": 0, "message": "Automated check-in detected"},
            {"code": False}, {"message": "签到成功"},
            {"code": -2, "repeated": True}, {"code": 1, "message": "unknown"},
        ):
            with self.subTest(payload=payload):
                self.assertFalse(checkin.checkin_result(payload))


if __name__ == "__main__":
    unittest.main()
