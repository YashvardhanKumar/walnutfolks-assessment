import logging
import threading
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Transaction, TransactionStatus
from .serializers import TransactionSerializer, WebhookPayloadSerializer
from .tasks import execute_transaction_processing, process_transaction_task

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """
    Health check endpoint: GET / (root path)
    Response format:
    {
        "status": "HEALTHY",
        "current_time": "2024-01-15T10:30:00Z"
    }
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response(
            {
                "status": "HEALTHY",
                "current_time": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            status=status.HTTP_200_OK,
        )


class WebhookTransactionView(APIView):
    """
    Webhook Endpoint: POST /v1/webhooks/transactions
    Accepts transaction webhooks, validates payload, guarantees idempotency,
    dispatches background processing, and immediately returns 202 Accepted.
    """
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = WebhookPayloadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid payload", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        validated_data = serializer.validated_data
        transaction_id = validated_data["transaction_id"]

        is_new_transaction = False
        try:
            with transaction.atomic():
                txn, created = Transaction.objects.get_or_create(
                    transaction_id=transaction_id,
                    defaults={
                        "source_account": validated_data["source_account"],
                        "destination_account": validated_data["destination_account"],
                        "amount": validated_data["amount"],
                        "currency": validated_data["currency"],
                        "status": TransactionStatus.PROCESSING,
                    },
                )
                is_new_transaction = created
        except IntegrityError:
            # Concurrent race condition caught by unique constraint
            txn = Transaction.objects.get(transaction_id=transaction_id)
            is_new_transaction = False

        # Only dispatch background job if this is the first time receiving this transaction
        if is_new_transaction:
            self._dispatch_background_processing(transaction_id)
            message = "Transaction received and queued for processing"
        else:
            logger.info("Duplicate webhook received for transaction_id=%s. Acknowledging idempotently.", transaction_id)
            message = "Webhook acknowledged. Transaction already received"

        return Response(
            {
                "status": "ACCEPTED",
                "message": message,
                "transaction_id": transaction_id,
            },
            status=status.HTTP_202_ACCEPTED,
        )

    def _dispatch_background_processing(self, transaction_id: str):
        """
        Dispatches background processing via Celery, sync (for testing), or fallback daemon thread.
        """
        async_backend = getattr(settings, "ASYNC_BACKEND", "celery")
        if async_backend == "sync":
            execute_transaction_processing(transaction_id)
            return

        if async_backend == "celery":
            try:
                process_transaction_task.delay(transaction_id)
                return
            except Exception as exc:
                logger.warning(
                    "Celery dispatch failed (%s), falling back to background thread for transaction %s",
                    exc,
                    transaction_id,
                )

        # Fallback to background thread
        thread = threading.Thread(
            target=execute_transaction_processing,
            args=(transaction_id,),
            daemon=True,
        )
        thread.start()


class TransactionQueryView(APIView):
    """
    Query Endpoint: GET /v1/transactions/{transaction_id}
    Retrieves transaction status.
    Per specification: returns an array containing the transaction object.
    Supports ?format=object or ?flat=true if the caller prefers a single JSON dictionary.
    """
    authentication_classes = []
    permission_classes = []

    def get(self, request, transaction_id=None):
        if not transaction_id:
            # If no ID specified, list latest 50 transactions
            transactions = Transaction.objects.all()[:50]
            serializer = TransactionSerializer(transactions, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        try:
            txn = Transaction.objects.get(transaction_id=transaction_id)
        except Transaction.DoesNotExist:
            return Response(
                {"error": "Transaction not found", "transaction_id": transaction_id},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = TransactionSerializer(txn)
        return_flat = request.query_params.get("flat") == "true" or request.query_params.get("style") == "object"

        if return_flat:
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Per PDF specification: Response is [{ ... }]
        return Response([serializer.data], status=status.HTTP_200_OK)
