from django.db import models


class Wallet(models.Model):
    """Represents a cryptocurrency wallet address"""
    address = models.CharField(max_length=255, unique=True)
    chain = models.CharField(max_length=50)  # ethereum, solana, etc.
    first_seen = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.chain}:{self.address}"


class Transaction(models.Model):
    """Represents a cryptocurrency transaction"""

    class TransactionType(models.TextChoices):
        BUY = 'buy', 'Buy'
        SELL = 'sell', 'Sell'
        SWAP = 'swap', 'Swap'
        TRANSFER = 'transfer', 'Transfer'

    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    transaction_hash = models.CharField(max_length=255)
    timestamp = models.DateTimeField()
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    asset_symbol = models.CharField(max_length=50)  # BTC, ETH, etc.
    amount = models.DecimalField(max_digits=30, decimal_places=18)
    price_usd = models.DecimalField(max_digits=20, decimal_places=8)
    value_usd = models.DecimalField(max_digits=20, decimal_places=2)
    fee_usd = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    # For FIFO calculation
    cost_basis_usd = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    realized_profit_loss = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['wallet', 'timestamp']),
            models.Index(fields=['wallet', 'asset_symbol']),
        ]

    def __str__(self):
        return f"{self.transaction_type} {self.amount} {self.asset_symbol} at {self.timestamp}"


class AssetHolding(models.Model):
    """Represents current holdings of an asset in a wallet"""
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='holdings')
    asset_symbol = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=30, decimal_places=18)
    current_price_usd = models.DecimalField(max_digits=20, decimal_places=8)
    value_usd = models.DecimalField(max_digits=20, decimal_places=2)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        pass

    def __str__(self):
        return f"{self.wallet} holds {self.amount} {self.asset_symbol}"


class TaxSummary(models.Model):
    """Represents a summary of tax calculations for a wallet within a time period"""
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='tax_summaries')
    start_date = models.DateField()
    end_date = models.DateField()
    total_proceeds = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_cost_basis = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_realized_gain_loss = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    short_term_gain_loss = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    long_term_gain_loss = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_fees = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('wallet', 'start_date', 'end_date')

    def __str__(self):
        return f"Tax summary for {self.wallet} from {self.start_date} to {self.end_date}"


class PremiumUser(models.Model):
    """Represents a premium user with access to premium features"""
    user_id = models.CharField(max_length=255, unique=True)  # Could be email, wallet address, or other identifier
    subscription_start = models.DateField()
    subscription_end = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Premium user: {self.user_id}"