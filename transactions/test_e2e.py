import time

from django.test import TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from transactions.models import Transaction


@override_settings(ASYNC_BACKEND="thread", PROCESSING_DELAY_SECONDS=1)
class E2ETimedIntegrationTests(TransactionTestCase):
    """
    End-to-end test with a short 1-second delay simulating the 30-second delay
    to verify real background transition from PROCESSING to PROCESSED across threads.
    Uses TransactionTestCase to support multi-threaded database access.
    """

    def setUp(self):
        self.client = APIClient()

    def test_single_transaction_lifecycle_processing_to_processed(self):
        payload = {
            "transaction_id": "txn_lifecycle_001",
            "source_account": "acc_sender_101",
            "destination_account": "acc_receiver_202",
            "amount": 1500,
            "currency": "INR",
        }

        # 1. Send Webhook
        post_res = self.client.post("/v1/webhooks/transactions", payload, format="json")
        self.assertEqual(post_res.status_code, status.HTTP_202_ACCEPTED)

        # 2. Query immediately: status should be PROCESSING, processed_at null
        get_res_1 = self.client.get("/v1/transactions/txn_lifecycle_001")
        self.assertEqual(get_res_1.status_code, status.HTTP_200_OK)
        data_1 = get_res_1.json()[0]
        self.assertEqual(data_1["status"], "PROCESSING")
        self.assertIsNone(data_1["processed_at"])

        # 3. Send duplicate webhook immediately: must return 202 without duplicate row
        dup_res = self.client.post("/v1/webhooks/transactions", payload, format="json")
        self.assertEqual(dup_res.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(Transaction.objects.filter(transaction_id="txn_lifecycle_001").count(), 1)

        # 4. Wait for simulated delay to complete (1s + buffer)
        time.sleep(1.4)

        # 5. Query again: status should now be PROCESSED and processed_at populated
        get_res_2 = self.client.get("/v1/transactions/txn_lifecycle_001")
        self.assertEqual(get_res_2.status_code, status.HTTP_200_OK)
        data_2 = get_res_2.json()[0]
        self.assertEqual(data_2["status"], "PROCESSED")
        self.assertIsNotNone(data_2["processed_at"])
