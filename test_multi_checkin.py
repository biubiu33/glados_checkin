import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import checkin
import logging_config
import multi_checkin


COOKIE = "gld:sess=test-session; gld:sess.sig=test-signature"


class ConfigCompatibilityTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_local_account_array_dispatches_to_multi_engine(self):
        accounts = [{"cookie": COOKIE, "origin": "glados.cloud"}]
        with patch.object(checkin, "load_config", return_value={"GLADOS_COOKIES": accounts}):
            with patch.object(multi_checkin, "main", return_value=True) as main:
                self.assertTrue(checkin.start(Mock()))
        self.assertEqual(json.loads(main.call_args.args[0]["GLADOS_COOKIES"]), accounts)

    def test_legacy_config_provides_account_and_serverchan_alias(self):
        config = {
            "COOKIE": COOKIE, "USER_AGENT": "custom-browser", "SERVE": "on", "SCKEY": "test-send-key",
            "GLADOS_EXCHANGE_PLAN": "plan100", "TWOCAPTCHA_API_KEY": "test-solver-key",
        }
        with patch.object(checkin, "load_config", return_value=config):
            with patch.object(multi_checkin, "main", return_value=True) as main:
                self.assertTrue(checkin.start(Mock()))
        supplied = main.call_args.args[0]
        self.assertEqual(supplied["SERVERCHAN_SENDKEY"], "test-send-key")
        self.assertEqual(supplied["TWOCAPTCHA_API_KEY"], "test-solver-key")
        self.assertEqual(json.loads(supplied["GLADOS_COOKIES"])[0]["user-agent"], "custom-browser")

    def test_environment_accounts_override_local_config(self):
        accounts = json.dumps([{"cookie": COOKIE, "name": "environment"}])
        with patch.dict(os.environ, {"GLADOS_COOKIES": accounts}):
            with patch.object(checkin, "load_config", return_value={"GLADOS_COOKIES": []}):
                with patch.object(multi_checkin, "main", return_value=True) as main:
                    self.assertTrue(checkin.start(Mock()))
        self.assertEqual(main.call_args.args[0]["GLADOS_COOKIES"], accounts)

    def test_single_account_keeps_existing_engine(self):
        with patch.object(checkin, "load_config", return_value={"COOKIE": COOKIE}):
            with patch.object(checkin, "submit_checkin", return_value={"code": 0}):
                with patch.object(checkin, "report_result", return_value=True):
                    with patch.object(multi_checkin, "main") as main:
                        self.assertTrue(checkin.start(Mock()))
        main.assert_not_called()

    def test_multi_failure_propagates_to_existing_entry(self):
        with patch.dict(os.environ, {"GLADOS_COOKIES": json.dumps([{"cookie": COOKIE}])}):
            with patch.object(checkin, "load_config", return_value={}):
                with patch.object(multi_checkin, "main", return_value=False):
                    self.assertFalse(checkin.start(Mock()))


class MultiCoreTest(unittest.TestCase):
    def test_duplicate_cookies_are_deduplicated(self):
        accounts = multi_checkin.Accounts.parse(json.dumps([{"cookie": COOKIE}, {"cookie": COOKIE}]))
        self.assertEqual(len(accounts), 1)

    def test_unknown_account_field_is_rejected(self):
        with self.assertRaises(ValueError):
            multi_checkin.Accounts.parse(json.dumps([{"cookie": COOKIE, "typo": "value"}]))

    def test_rejection_flags_cannot_be_overridden_by_repeated(self):
        for payload in (
            {"code": -2, "repeated": True},
            {"code": 5, "reason": "turnstile", "repeated": True},
            {"code": False},
            {"code": 0, "message": "Automated check-in detected"},
        ):
            with self.subTest(payload=payload):
                result = multi_checkin.parse_checkin(payload, "glados.cloud", Mock())
                self.assertIs(result.code, multi_checkin.CheckinStatus.FAILURE)

    def test_user_agent_recovers_from_login_platform(self):
        with multi_checkin.API("glados.cloud", COOKIE) as api:
            with patch.object(api, "_checkin_attempt", side_effect=[
                {"code": 4, "reason": "device-mismatch", "loginDevice": "macOS"},
                {"code": 0, "points": 10},
            ]) as attempt:
                result = api.checkin()
        self.assertIs(result.code, multi_checkin.CheckinStatus.SUCCESS)
        self.assertEqual(attempt.call_args.args[0], multi_checkin.PLATFORM_UA["macOS"])

    def test_custom_user_agent_is_used_as_configured(self):
        with multi_checkin.API("glados.cloud", COOKIE, user_agent="custom-browser") as api:
            with patch.object(api, "_checkin_attempt", return_value={
                "code": 4, "reason": "device-mismatch", "loginDevice": "Windows",
            }) as attempt:
                self.assertIs(api.checkin().code, multi_checkin.CheckinStatus.FAILURE)
        attempt.assert_called_once_with("custom-browser")

    def test_multi_solver_uses_detected_origin(self):
        rejected = Mock()
        rejected.json.return_value = {"code": 5, "reason": "turnstile"}
        with multi_checkin.API("glados.network", COOKIE, solver_key="test-solver-key") as api:
            with patch.object(api, "_checkin_challenge", return_value=("nonce", "proof")):
                with patch.object(api, "request", return_value=rejected):
                    with patch.object(checkin, "submit_checkin", return_value={"code": 0}) as submit:
                        self.assertEqual(api._checkin_attempt("browser")["code"], 0)
        self.assertEqual(submit.call_args.args[1]["origin"], "https://glados.network")
        self.assertEqual(submit.call_args.kwargs["solver_key"], "test-solver-key")

    def test_exchange_request_avoids_automatic_retry(self):
        response = Mock()
        response.json.return_value = {"code": 0}
        with multi_checkin.API("glados.cloud", COOKIE) as api:
            with patch.object(api, "request", return_value=response) as request:
                self.assertIn("兑换成功", api.exchange("plan100"))
        self.assertFalse(request.call_args.kwargs["retry"])

    def test_main_reports_business_failure_to_caller(self):
        account = multi_checkin.CookieEntry.build(1, COOKIE)
        report = multi_checkin.Report(multi_checkin.Accounts([account]))
        env = {"GLADOS_COOKIES": json.dumps([{"cookie": COOKIE}])}
        with patch.object(multi_checkin, "init_logger"):
            with patch.object(multi_checkin.CheckinRunner, "run", return_value=report):
                with patch.object(multi_checkin.PushService, "send"):
                    self.assertFalse(multi_checkin.main(env))

    def test_log_redaction_masks_session_and_bearer(self):
        text = logging_config.redact(COOKIE + " Bearer private-token")
        self.assertNotIn("test-session", text)
        self.assertNotIn("test-signature", text)
        self.assertNotIn("private-token", text)

    def test_push_exception_hides_send_key(self):
        backend = multi_checkin.ServerChanBackend("private-send-key")
        with patch("serverchan_sdk.sc_send", side_effect=RuntimeError("private-send-key")):
            with self.assertLogs(multi_checkin.logger, level="ERROR") as logs:
                self.assertFalse(backend.send(multi_checkin.Report.failed("test")))
        self.assertNotIn("private-send-key", "".join(logs.output))

    def test_legacy_solver_submits_domain_specific_token(self):
        session = Mock()
        session.get.return_value.json.return_value = {"code": 0, "nonce": "nonce"}
        session.post.return_value.json.return_value = {"code": 0}
        with patch.object(checkin.time, "sleep"):
            with redirect_stdout(io.StringIO()):
                checkin.submit_checkin(session, {"origin": "https://glados.network"})
        self.assertEqual(session.post.call_args.args[0], "https://glados.network/api/user/checkin")
        self.assertEqual(session.post.call_args.kwargs["json"]["token"], "glados.network")


if __name__ == "__main__":
    unittest.main()
