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
            response({"code": 0, "points": "17.0000000000000000"}),
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
        self.assertIn("17 points", output)
        self.session.get.assert_called_with(
            checkin.POINTS_URL, headers=checkin.request_headers("test-cookie"), timeout=checkin.TIMEOUT,
        )

    def test_checkin_balance_avoids_extra_points_request(self):
        self.assertTrue(self.run_checkin()[0])
        self.assertEqual(self.session.get.call_count, 2)

    def test_zero_points_is_displayed(self):
        self.session.post.return_value = response({"code": 1, "repeated": True})
        self.session.get.side_effect = [
            response({"code": 0, "nonce": "test-nonce"}),
            response({"code": 0, "data": {"leftDays": "30"}}),
            response({"code": 0, "points": 0}),
        ]
        result, output = self.run_checkin()
        self.assertTrue(result)
        self.assertIn("0 points", output)

    def test_points_failure_preserves_checkin_result(self):
        for failure in (requests.Timeout("private-value"), response({"code": -2})):
            with self.subTest(failure=type(failure).__name__):
                self.session.post.return_value = response({"code": 1, "repeated": True})
                self.session.get.side_effect = [
                    response({"code": 0, "nonce": "test-nonce"}),
                    response({"code": 0, "data": {"leftDays": "30"}}),
                    failure,
                ]
                result, output = self.run_checkin()
                self.assertTrue(result)
                self.assertIn("积分查询失败", output)
                self.assertNotIn("private-value", output)

    def test_business_rejection_does_not_report_success(self):
        self.session.post.return_value = response({"code": 4, "message": "rejected"})
        self.assertFalse(self.run_checkin()[0])

    def test_turnstile_rejection_reports_required_verification(self):
        self.session.post.return_value = response({"code": 5, "reason": "turnstile"})
        result, output = self.run_checkin()
        self.assertFalse(result)
        self.assertIn("Cloudflare Turnstile", output)
        self.assertEqual(self.session.get.call_count, 1)

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

    def test_turnstile_fallback_uses_fresh_nonce_and_single_solver_task(self):
        self.session.get.side_effect = [
            response({"code": 0, "nonce": "first-nonce", "turnstile": "sitekey"}),
            response({"code": 0, "nonce": "fresh-nonce", "turnstile": "sitekey"}),
            response({"code": 0, "data": {"leftDays": "30"}}),
        ]
        self.session.post.side_effect = [
            response({"code": 5, "reason": "turnstile"}),
            response({"code": 0, "list": [{"balance": "20"}]}),
        ]
        with patch.dict(os.environ, {"TWOCAPTCHA_API_KEY": "private-api-key"}):
            with patch.object(checkin, "solve_turnstile", return_value="private-token") as solve:
                result, output = self.run_checkin()
        self.assertTrue(result)
        solve.assert_called_once()
        self.assertEqual(solve.call_args.args[:3], ("private-api-key", "sitekey", "fresh-nonce"))
        payload = self.session.post.call_args.kwargs["json"]
        self.assertEqual(payload["nonce"], "fresh-nonce")
        self.assertEqual(payload["turnstile"], "private-token")
        self.assertEqual(payload["tsState"], "ok")
        self.assertNotIn("private-token", output)
        self.assertNotIn("private-api-key", output)

    def test_repeated_checkin_avoids_paid_solver(self):
        self.session.post.return_value = response({"code": 1, "repeated": True})
        with patch.dict(os.environ, {"TWOCAPTCHA_API_KEY": "private-api-key"}):
            with patch.object(checkin, "solve_turnstile") as solve:
                self.assertTrue(self.run_checkin()[0])
        solve.assert_not_called()

    def test_missing_sitekey_avoids_paid_solver(self):
        with patch.object(checkin, "solve_turnstile") as solve:
            with self.assertRaises(checkin.CheckinError):
                checkin.submit_checkin(self.session, {}, solver_key="private-api-key")
        solve.assert_not_called()
        self.session.post.assert_not_called()


class SolverTest(unittest.TestCase):
    def setUp(self):
        clock = patch.object(checkin.time, "monotonic", return_value=0)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        sleep = patch.object(checkin.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_solver_sends_only_required_task_data(self):
        with patch.object(checkin.requests, "post", side_effect=[
            response({"errorId": 0, "taskId": 123}),
            response({"errorId": 0, "status": "processing"}),
            response({"errorId": 0, "status": "ready", "solution": {"token": "private-token"}}),
        ]) as post:
            output = io.StringIO()
            with redirect_stdout(output):
                token = checkin.solve_turnstile("private-key", "sitekey", "nonce", 300)
        self.assertEqual(token, "private-token")
        self.assertNotIn("private-token", output.getvalue())
        self.assertEqual(post.call_args_list[0].kwargs["json"], {
            "clientKey": "private-key",
            "task": {
                "type": "TurnstileTaskProxyless", "websiteURL": checkin.REFERER,
                "websiteKey": "sitekey", "action": "checkin", "data": "nonce",
            },
        })
        self.assertEqual(post.call_args_list[1].kwargs["json"], {
            "clientKey": "private-key", "taskId": 123,
        })
        self.assertEqual(post.call_count, 3)

    def test_account_error_does_not_create_more_tasks(self):
        with patch.object(checkin.requests, "post", return_value=response({
            "errorId": 1, "errorCode": "ERROR_ZERO_BALANCE", "errorDescription": "private-key",
        })) as post:
            with self.assertRaisesRegex(checkin.CheckinError, "ERROR_ZERO_BALANCE") as caught:
                checkin.solve_turnstile("private-key", "sitekey", "nonce", 300)
        self.assertNotIn("private-key", str(caught.exception))
        self.assertEqual(post.call_count, 1)

    def test_network_error_is_safe_and_never_retried(self):
        with patch.object(checkin.requests, "post", side_effect=requests.Timeout("private-key")) as post:
            with self.assertRaises(checkin.CheckinError) as caught:
                checkin.solve_turnstile("private-key", "sitekey", "nonce", 300)
        self.assertNotIn("private-key", str(caught.exception))
        self.assertEqual(post.call_count, 1)

    def test_timeout_does_not_create_another_paid_task(self):
        self.clock.side_effect = [0, 0, 181]
        with patch.object(checkin, "solver_request", return_value={"taskId": 123}) as request:
            with self.assertRaisesRegex(checkin.CheckinError, "超时"):
                checkin.solve_turnstile("private-key", "sitekey", "nonce", 300)
        self.assertEqual(request.call_count, 1)

    def test_short_lived_challenge_does_not_create_task(self):
        with patch.object(checkin, "solver_request") as request:
            with self.assertRaises(checkin.CheckinError):
                checkin.solve_turnstile("private-key", "sitekey", "nonce", 5)
        request.assert_not_called()

    def test_malformed_solver_response_is_rejected(self):
        for task_result in (
            {"errorId": 0, "status": "ready", "solution": {}},
            {"errorId": 0, "status": "ready", "solution": {"token": ""}},
            {"errorId": 0, "status": "unknown"},
            {"errorId": 0, "status": "ready", "solution": []},
        ):
            with self.subTest(task_result=task_result):
                with patch.object(checkin.requests, "post", side_effect=[
                    response({"errorId": 0, "taskId": 123}), response(task_result),
                ]):
                    with self.assertRaises(checkin.CheckinError):
                        checkin.solve_turnstile("private-key", "sitekey", "nonce", 300)


if __name__ == "__main__":
    unittest.main()
