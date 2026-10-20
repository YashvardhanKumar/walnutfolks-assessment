import logging
import time

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .models import Transaction, TransactionStatus

logger = logging.getLogger(__name__)


def execute_transaction_processing(transaction_id: str):
    """
    Executes the transaction processing workflow:
    1. Simulates external API calls with a configurable delay (spec requires 30s).
    2. Atomically updates transaction status from PROCESSING to PROCESSED.
    3. Updates processed_at timestamp in persistent storage.
    """
    delay = getattr(settings, "PROCESSING_DELAY_SECONDS", 30)
    logger.info(
        "Starting processing for transaction %s (simulating external API delay: %ds)",
        transaction_id,
        delay,
    )
    if delay > 0:
        time.sleep(delay)

    with transaction.atomic():
        try:
            if connection.vendor == "sqlite":
                txn = Transaction.objects.get(transaction_id=transaction_id)
            else:
                txn = Transaction.objects.select_for_update().get(transaction_id=transaction_id)
        except Transaction.DoesNotExist:
            logger.error("Transaction %s not found during background processing", transaction_id)
            return

        # Ensure idempotency: only update if still in PROCESSING state
        if txn.status == TransactionStatus.PROCESSING:
            txn.status = TransactionStatus.PROCESSED
            txn.processed_at = timezone.now()
            txn.save(update_fields=["status", "processed_at"])
            logger.info("Transaction %s marked PROCESSED at %s", transaction_id, txn.processed_at)
        else:
            logger.info(
                "Transaction %s already in state %s, ignoring duplicate processing",
                transaction_id,
                txn.status,
            )


@shared_task(name="transactions.tasks.process_transaction_task", bind=True, max_retries=3)
def process_transaction_task(self, transaction_id: str):
    try:
        execute_transaction_processing(transaction_id)
    except Exception as exc:
        logger.exception("Error processing transaction %s: %s", transaction_id, exc)
        raise self.retry(exc=exc, countdown=5)
