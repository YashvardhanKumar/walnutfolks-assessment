from django.db import models


class TransactionStatus(models.TextChoices):
    PROCESSING = "PROCESSING", "PROCESSING"
    PROCESSED = "PROCESSED", "PROCESSED"
    FAILED = "FAILED", "FAILED"


class Transaction(models.Model):
    transaction_id = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        help_text="Unique external transaction identifier",
    )
    source_account = models.CharField(max_length=128)
    destination_account = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    currency = models.CharField(max_length=10)
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PROCESSING,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"

    def __str__(self):
        return f"{self.transaction_id} ({self.status}) - {self.amount} {self.currency}"
