import time
from decimal import Decimal
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from .models import Transaction, TransactionStatus
from .tasks import execute_transaction_processing


@override_settings(ASYNC_BACKEND="sync", PROCESSING_DELAY_SECONDS=0)
class TransactionServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.valid_payload = {
            "transaction_id": "txn_test_001",
            "source_account": "acc_user_789",
            "destination_account": "acc_merchant_456",
            "amount": 1500,
            "currency": "INR",
        }

    def test_health_check_endpoint(self):
        """GET / should return 200 with HEALTHY status and current_time."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data.get("status"), "HEALTHY")
        self.assertIn("current_time", data)
        self.assertTrue(data["current_time"].endswith("Z"))

    def test_webhook_returns_202_accepted(self):
        """POST /v1/webhooks/transactions must return 202 Accepted."""
        response = self.client.post(
            "/v1/webhooks/transactions",
            self.valid_payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data.get("status"), "ACCEPTED")
        self.assertEqual(data.get("transaction_id"), "txn_test_001")

        # Verify transaction was persisted with PROCESSING status
        txn = Transaction.objects.get(transaction_id="txn_test_001")
        self.assertEqual(txn.source_account, "acc_user_789")
        self.assertEqual(txn.destination_account, "acc_merchant_456")
        self.assertEqual(txn.amount, Decimal("1500.00"))
        self.assertEqual(txn.currency, "INR")

    def test_response_time_under_500ms(self):
        """Must respond well under 500ms (strict requirement)."""
        start = time.perf_counter()
        response = self.client.post(
            "/v1/webhooks/transactions",
            {
                "transaction_id": "txn_speed_test",
                "source_account": "acc_1",
                "destination_account": "acc_2",
                "amount": 100,
                "currency": "USD",
            },
            format="json",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertLess(elapsed_ms, 500, f"Webhook took {elapsed_ms:.2f}ms, which exceeds 500ms limit")

    def test_duplicate_prevention_idempotency(self):
        """
        Sending the same webhook multiple times should:
        1. Acknowledge gracefully with 202 Accepted every time.
        2. Only create exactly ONE transaction row in the database.
        """
        # First send
        res1 = self.client.post("/v1/webhooks/transactions", self.valid_payload, format="json")
        self.assertEqual(res1.status_code, status.HTTP_202_ACCEPTED)

        # Duplicate send 1
        res2 = self.client.post("/v1/webhooks/transactions", self.valid_payload, format="json")
        self.assertEqual(res2.status_code, status.HTTP_202_ACCEPTED)

        # Duplicate send 2
        res3 = self.client.post("/v1/webhooks/transactions", self.valid_payload, format="json")
        self.assertEqual(res3.status_code, status.HTTP_202_ACCEPTED)

        # Verify only 1 database entry exists
        count = Transaction.objects.filter(transaction_id="txn_test_001").count()
        self.assertEqual(count, 1)

    def test_background_processing_transitions_status(self):
        """
        Test that execute_transaction_processing transitions state to PROCESSED
        and populates processed_at.
        """
        txn = Transaction.objects.create(
            transaction_id="txn_bg_001",
            source_account="acc_user_1",
            destination_account="acc_merchant_1",
            amount=Decimal("150.50"),
            currency="USD",
            status=TransactionStatus.PROCESSING,
        )
        self.assertIsNone(txn.processed_at)

        # Execute processing
        execute_transaction_processing("txn_bg_001")

        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.PROCESSED)
        self.assertIsNotNone(txn.processed_at)

    def test_query_transaction_status_spec_format(self):
        """
        Query endpoint: GET /v1/transactions/{transaction_id}
        Should return an array containing the transaction per specification:
        [{
           "transaction_id": "...",
           "source_account": "...",
           "destination_account": "...",
           "amount": 150.5,
           "currency": "USD",
           "status": "PROCESSED",
           "created_at": "...",
           "processed_at": "..."
        }]
        """
        txn = Transaction.objects.create(
            transaction_id="txn_query_001",
            source_account="acc_user_789",
            destination_account="acc_merchant_456",
            amount=Decimal("150.50"),
            currency="USD",
            status=TransactionStatus.PROCESSED,
        )

        response = self.client.get("/v1/transactions/txn_query_001")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

        item = data[0]
        self.assertEqual(item["transaction_id"], "txn_query_001")
        self.assertEqual(item["source_account"], "acc_user_789")
        self.assertEqual(item["destination_account"], "acc_merchant_456")
        self.assertEqual(item["amount"], 150.5)
        self.assertEqual(item["currency"], "USD")
        self.assertEqual(item["status"], "PROCESSED")
        self.assertIn("created_at", item)

        # Test object format override via ?flat=true
        obj_res = self.client.get("/v1/transactions/txn_query_001?flat=true")
        self.assertEqual(obj_res.status_code, status.HTTP_200_OK)
        self.assertIsInstance(obj_res.json(), dict)
        self.assertEqual(obj_res.json()["transaction_id"], "txn_query_001")

    def test_query_non_existent_transaction(self):
        """Non-existent transaction_id should return 404."""
        response = self.client.get("/v1/transactions/non_existent_id")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_payload_validation(self):
        """Missing required fields or invalid amounts should return 400."""
        invalid_payloads = [
            {},  # Empty
            {"transaction_id": "txn_x"},  # Missing fields
            {
                "transaction_id": "txn_x",
                "source_account": "acc_1",
                "destination_account": "acc_2",
                "amount": -50,  # Negative amount
                "currency": "USD",
            },
        ]
        for payload in invalid_payloads:
            res = self.client.post("/v1/webhooks/transactions", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_multiple_consecutive_webhooks_idempotent(self):
        """
        Verify that multiple webhooks with the same ID do not result in
        multiple rows or errors.
        """
        payload = {
            "transaction_id": "txn_multi_batch",
            "source_account": "acc_batch_1",
            "destination_account": "acc_batch_2",
            "amount": 500,
            "currency": "INR",
        }
        for i in range(5):
            res = self.client.post("/v1/webhooks/transactions", payload, format="json")
            self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

        self.assertEqual(
            Transaction.objects.filter(transaction_id="txn_multi_batch").count(),
            1,
        )
