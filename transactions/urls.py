from django.urls import path
from .views import (
    HealthCheckView,
    TransactionQueryView,
    WebhookTransactionView,
)

urlpatterns = [
    # Health check
    path("", HealthCheckView.as_view(), name="health_check"),
    # Webhooks (support both with and without trailing slash)
    path("v1/webhooks/transactions", WebhookTransactionView.as_view(), name="webhook_transactions"),
    path("v1/webhooks/transactions/", WebhookTransactionView.as_view(), name="webhook_transactions_slash"),
    # Transaction queries (support both with and without trailing slash)
    path("v1/transactions", TransactionQueryView.as_view(), name="transaction_list"),
    path("v1/transactions/", TransactionQueryView.as_view(), name="transaction_list_slash"),
    path("v1/transactions/<str:transaction_id>", TransactionQueryView.as_view(), name="transaction_detail"),
    path("v1/transactions/<str:transaction_id>/", TransactionQueryView.as_view(), name="transaction_detail_slash"),
]
