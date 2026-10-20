from decimal import Decimal

from rest_framework import serializers

from .models import Transaction


class WebhookPayloadSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(max_length=128, required=True, allow_blank=False)
    source_account = serializers.CharField(max_length=128, required=True, allow_blank=False)
    destination_account = serializers.CharField(max_length=128, required=True, allow_blank=False)
    amount = serializers.DecimalField(
        max_digits=16, decimal_places=2, min_value=Decimal("0.01"), required=True
    )
    currency = serializers.CharField(max_length=10, required=True, allow_blank=False)

    def validate_currency(self, value):
        return value.strip().upper()


class TransactionSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    processed_at = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            "transaction_id",
            "source_account",
            "destination_account",
            "amount",
            "currency",
            "status",
            "created_at",
            "processed_at",
        ]

    def get_amount(self, obj):
        # Format as float for numeric representation in JSON (e.g. 150.5 or 1500)
        try:
            val = float(obj.amount)
            return int(val) if val.is_integer() else round(val, 2)
        except (ValueError, TypeError):
            return obj.amount

    def get_created_at(self, obj):
        if obj.created_at:
            return obj.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return None

    def get_processed_at(self, obj):
        if obj.processed_at:
            return obj.processed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        return None
