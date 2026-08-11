import base64
import json
import unittest
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent.agent import (
    _candidate_ids,
    _duplicate_metadata_update_targets,
    _safe_operation_trace,
)
from app.core import encryption, rate_limit
from app.core.config import Settings
from app.core.csrf import _cookie_value
from app.services import agent_job_service, price_job_service
from app.services.transaction_service import _command_fingerprint
from app.services.undo_service import _compensation_order


class IdempotencyFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_order_independent_but_payload_sensitive(self):
        first = _command_fingerprint(
            "buy",
            {"account_id": "a", "quantity": "10", "price": "20"},
        )
        reordered = _command_fingerprint(
            "buy",
            {"price": "20", "quantity": "10", "account_id": "a"},
        )
        changed = _command_fingerprint(
            "buy",
            {"account_id": "a", "quantity": "11", "price": "20"},
        )

        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)


class AgentCompensationOrderingTests(unittest.TestCase):
    def test_candidate_ids_preserve_result_order(self):
        first = uuid.uuid4()
        second = uuid.uuid4()
        self.assertEqual(
            _candidate_ids(
                {
                    "transactions": [
                        {"id": str(first)},
                        {"id": str(second)},
                        {"duplicate": str(first)},
                    ]
                }
            ),
            [first, second],
        )

    def test_candidate_ids_ignore_transaction_references(self):
        original = uuid.uuid4()
        amendment = uuid.uuid4()
        self.assertEqual(
            _candidate_ids(
                {
                    "causation_id": str(original),
                    "reversal_of_id": str(original),
                    "metadata_json": {
                        "amends_transaction_id": str(original),
                        "id": str(original),
                    },
                    "id": str(amendment),
                }
            ),
            [amendment],
        )

    def test_legacy_tool_trace_restores_execution_order(self):
        deposit = uuid.uuid4()
        buy = uuid.uuid4()
        legacy_log = SimpleNamespace(
            event_ids_json=sorted([str(deposit), str(buy)]),
            tool_calls_json=[
                {"tool": "create_cash_transaction", "event_ids": [str(deposit)]},
                {"tool": "create_buy_transaction", "event_ids": [str(buy)]},
            ],
            summary_json={},
        )

        self.assertEqual(_compensation_order(legacy_log), [deposit, buy])

    def test_unknown_legacy_multi_event_order_fails_closed(self):
        legacy_log = SimpleNamespace(
            event_ids_json=[str(uuid.uuid4()), str(uuid.uuid4())],
            tool_calls_json=[],
            summary_json={},
        )
        with self.assertRaisesRegex(
            ValueError,
            "agent_operation_event_order_unknown",
        ):
            _compensation_order(legacy_log)

    def test_duplicate_metadata_targets_are_not_compensatable(self):
        target = uuid.uuid4()
        trace = [
            {
                "id": "first",
                "tool": "update_transaction_metadata",
                "args": {"transaction_id": str(target).upper(), "note": "one"},
                "event_ids": [str(uuid.uuid4())],
            },
            {
                "id": "second",
                "tool": "update_transaction_metadata",
                "args": {"transaction_id": str(target), "note": "two"},
                "event_ids": [str(uuid.uuid4())],
            },
        ]

        self.assertEqual(
            _duplicate_metadata_update_targets(trace),
            {str(target)},
        )
        _, summary = _safe_operation_trace(trace)
        self.assertFalse(summary["compensatable"])


class EnvelopeEncryptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_envelope_round_trip_and_tamper_detection(self):
        settings = SimpleNamespace(
            app_encryption_key=base64.urlsafe_b64encode(b"k" * 32).decode(),
            llm_encryption_key=None,
            encryption_provider="local",
        )
        with patch("app.core.encryption.get_settings", return_value=settings):
            envelope = await encryption.encrypt_secret(
                "private-api-key",
                purpose="llm-provider-key",
            )
            self.assertEqual(
                await encryption.decrypt_secret(
                    envelope,
                    purpose="llm-provider-key",
                ),
                "private-api-key",
            )

            payload = json.loads(
                encryption._unb64(
                    envelope.removeprefix(encryption.ENVELOPE_PREFIX)
                ).decode()
            )
            ciphertext = bytearray(encryption._unb64(payload["ciphertext"]))
            ciphertext[0] ^= 1
            payload["ciphertext"] = encryption._b64(bytes(ciphertext))
            tampered = encryption.ENVELOPE_PREFIX + encryption._b64(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            with self.assertRaisesRegex(RuntimeError, "secret_decryption_failed"):
                await encryption.decrypt_secret(
                    tampered,
                    purpose="llm-provider-key",
                )


class ProductionConfigurationTests(unittest.TestCase):
    @staticmethod
    def _production_values() -> dict:
        return {
            "environment": "production",
            "jwt_secret": "j" * 64,
            "initial_admin_password": "a-unique-admin-password",
            "cors_origins": ["https://wealth.example.com"],
            "redis_url": "rediss://redis.internal:6379/0",
            "celery_broker_url": "amqps://rabbit.internal/vhost",
            "celery_result_backend": "rediss://redis.internal:6379/1",
            "agent_job_backend": "celery",
            "document_job_backend": "celery",
            "price_job_backend": "celery",
            "agent_inline_fallback": False,
            "document_inline_fallback": False,
            "price_inline_fallback": False,
            "document_storage_backend": "oss",
            "document_storage_endpoint": "oss-cn-hangzhou-internal.aliyuncs.com",
            "document_storage_public_endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
            "document_storage_bucket": "wealth-private",
            "document_storage_access_key": "oss-access-key",
            "document_storage_secret_key": "oss-secret-key",
            "document_storage_secure": True,
            "document_storage_kms_key_id": "kms-key-id",
            "document_clamav_required": True,
            "document_clamav_host": "clamav.internal",
            "encryption_provider": "alicloud",
            "alicloud_region_id": "cn-hangzhou",
            "alicloud_kms_key_id": "kms-key-id",
        }

    def test_production_requires_distributed_state(self):
        values = self._production_values()
        values["redis_url"] = None

        with self.assertRaisesRegex(ValueError, "production_redis_url_required"):
            Settings(_env_file=None, **values)

    def test_alibaba_production_topology_is_accepted(self):
        settings = Settings(_env_file=None, **self._production_values())
        self.assertEqual(settings.agent_job_backend, "celery")

    def test_production_oss_credentials_fail_closed(self):
        values = self._production_values()
        values["document_storage_secret_key"] = ""

        with self.assertRaisesRegex(
            ValueError,
            "production_oss_configuration_required",
        ):
            Settings(_env_file=None, **values)

    def test_production_oss_endpoints_require_https(self):
        values = self._production_values()
        values["document_storage_endpoint"] = "http://oss.internal.example.com"
        with self.assertRaisesRegex(
            ValueError,
            "production_oss_private_https_required",
        ):
            Settings(_env_file=None, **values)

        values = self._production_values()
        values["document_storage_public_endpoint"] = (
            "ftp://oss-cn-hangzhou.aliyuncs.com"
        )
        with self.assertRaisesRegex(
            ValueError,
            "production_oss_public_https_required",
        ):
            Settings(_env_file=None, **values)


class LoginRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_fails_closed_when_redis_is_unavailable(self):
        limiter = rate_limit.LoginRateLimiter()
        production = SimpleNamespace(
            environment="production",
            redis_url="rediss://redis.internal:6379/0",
        )
        with (
            patch.object(rate_limit, "settings", production),
            patch.object(
                limiter,
                "_redis_client",
                AsyncMock(return_value=None),
            ),
        ):
            self.assertFalse(await limiter.consume("client:user"))
        self.assertFalse(limiter._attempts)


class CookieParsingTests(unittest.TestCase):
    def test_cookie_name_must_match_exactly(self):
        self.assertIsNone(_cookie_value("not_wp_session=value", "wp_session"))
        self.assertEqual(
            _cookie_value("theme=dark; wp_session=token", "wp_session"),
            "token",
        )


class JobRetrySemanticsTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    @asynccontextmanager
    async def _unavailable_lease(_job_id):
        raise ConnectionError("database_unavailable")
        yield True  # pragma: no cover - keeps this an async context manager

    async def test_agent_prestart_connection_error_remains_retryable(self):
        with (
            patch.object(
                agent_job_service,
                "acquire_job_lease",
                self._unavailable_lease,
            ),
            patch.object(
                agent_job_service,
                "_mark_failed",
                AsyncMock(),
            ) as mark_failed,
        ):
            with self.assertRaises(ConnectionError):
                await agent_job_service.process_agent_job(
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                )

        mark_failed.assert_not_awaited()

    async def test_price_prestart_connection_error_remains_retryable(self):
        with (
            patch.object(
                price_job_service,
                "acquire_job_lease",
                self._unavailable_lease,
            ),
            patch.object(price_job_service, "AsyncSessionLocal") as sessions,
        ):
            with self.assertRaises(ConnectionError):
                await price_job_service.process_price_refresh_job(
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                )

        sessions.assert_not_called()


if __name__ == "__main__":
    unittest.main()
