from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_id",
        "source_account",
        "destination_account",
        "amount",
        "currency",
        "status",
        "created_at",
        "processed_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("transaction_id", "source_account", "destination_account")
    readonly_fields = ("created_at",)
