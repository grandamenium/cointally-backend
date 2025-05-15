from rest_framework import serializers
from .models import Wallet, Transaction, AssetHolding, TaxSummary, PremiumUser


class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ['id', 'address', 'chain', 'first_seen', 'last_updated']


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = [
            'id', 'wallet', 'transaction_hash', 'timestamp',
            'transaction_type', 'asset_symbol', 'amount',
            'price_usd', 'value_usd', 'fee_usd',
            'cost_basis_usd', 'realized_profit_loss'
        ]


class AssetHoldingSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssetHolding
        fields = [
            'id', 'wallet', 'asset_symbol', 'amount',
            'current_price_usd', 'value_usd', 'last_updated'
        ]


class TaxSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxSummary
        fields = [
            'id', 'wallet', 'start_date', 'end_date',
            'total_proceeds', 'total_cost_basis', 'total_realized_gain_loss',
            'short_term_gain_loss', 'long_term_gain_loss',
            'total_fees', 'generated_at'
        ]


class PremiumUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = PremiumUser
        fields = ['id', 'user_id', 'subscription_start', 'subscription_end', 'is_active']


# Custom serializers for API responses

class WalletAnalysisSerializer(serializers.Serializer):
    address = serializers.CharField()
    chain = serializers.CharField()
    total_realized_gain = serializers.FloatField()
    total_transactions = serializers.IntegerField()
    earliest_transaction = serializers.DateTimeField(required=False)
    latest_transaction = serializers.DateTimeField(required=False)
    positive_transactions_percent = serializers.IntegerField()

    # Additional fields
    total_value_usd = serializers.FloatField()
    holdings = AssetHoldingSerializer(many=True, required=False)
    monthly_pnl = serializers.ListField(child=serializers.DictField(), required=False)
    recent_transactions = TransactionSerializer(many=True, required=False)


class Form8949EntrySerializer(serializers.Serializer):
    """Serializer for IRS Form 8949 entries (for premium users)"""
    description = serializers.CharField()  # Asset description
    date_acquired = serializers.DateField()
    date_sold = serializers.DateField()
    proceeds = serializers.DecimalField(max_digits=20, decimal_places=2)
    cost_basis = serializers.DecimalField(max_digits=20, decimal_places=2)
    gain_or_loss = serializers.DecimalField(max_digits=20, decimal_places=2)
    is_short_term = serializers.BooleanField()


class Form8949Serializer(serializers.Serializer):
    """Serializer for complete IRS Form 8949 (for premium users)"""
    tax_year = serializers.IntegerField()
    short_term_transactions = Form8949EntrySerializer(many=True)
    long_term_transactions = Form8949EntrySerializer(many=True)
    short_term_total = serializers.DecimalField(max_digits=20, decimal_places=2)
    long_term_total = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_gain_or_loss = serializers.DecimalField(max_digits=20, decimal_places=2)


class MonthlyReportSerializer(serializers.Serializer):
    """Serializer for monthly reports (for premium users)"""
    month = serializers.DateField()
    total_transactions = serializers.IntegerField()
    total_buys = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_sells = serializers.DecimalField(max_digits=20, decimal_places=2)
    realized_profit_loss = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_fees = serializers.DecimalField(max_digits=20, decimal_places=2)
    top_assets = serializers.ListField(child=serializers.DictField())