import logging
import time

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)


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

    # Additional fields for tracking issues
    notes = models.TextField(null=True, blank=True)  # For storing error messages or other notes
    needs_review = models.BooleanField(default=False)  # Flag for transactions that need manual review

    class Meta:
        unique_together = ('wallet', 'transaction_hash')
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


class User(AbstractUser):
    """Extended user model for CryptoTaxPro"""
    wallet_addresses = models.JSONField(default=list, blank=True)
    is_premium = models.BooleanField(default=False)
    premium_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.email


class ExchangeCredential(models.Model):
    """Stores encrypted API credentials for centralized exchanges"""
    EXCHANGE_CHOICES = [
        ('binance', 'Binance'),
        ('coinbase', 'Coinbase'),
        ('bybit', 'Bybit'),
        ('kraken', 'Kraken'),
        ('kucoin', 'KuCoin'),
        ('ftx', 'FTX'),
        ('gemini', 'Gemini'),
        ('hyperliquid', 'Hyperliquid'),
    ]
    PLATFORM_TYPE_CHOICES = [
        ('cex', 'Centralized Exchange'),
        ('dex_hybrid', 'DEX/Hybrid Platform'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='exchange_credentials')
    exchange = models.CharField(max_length=50, choices=EXCHANGE_CHOICES)
    api_key = models.TextField()  # Encrypted
    api_secret = models.TextField()  # Encrypted
    api_passphrase = models.TextField(null=True, blank=True)  # Encrypted, optional
    is_active = models.BooleanField(default=True)
    last_sync = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_sync_timestamp = models.BigIntegerField(null=True, blank=True)  # Store timestamp in milliseconds
    platform_type = models.CharField(
        max_length=20,
        choices=PLATFORM_TYPE_CHOICES,
        default='cex'
    )
    api_permissions = models.JSONField(default=dict, blank=True)  # Store granted permissions
    rate_limit_info = models.JSONField(default=dict, blank=True)  # Store rate limit data
    last_error = models.TextField(null=True, blank=True)  # Store last sync error
    sync_status = models.CharField(
        max_length=20,
        choices=[
            ('idle', 'Idle'),
            ('syncing', 'Syncing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='idle'
    )

    class Meta:
        unique_together = ('user', 'exchange')

    def save(self, *args, **kwargs):
        """Enhanced encryption with key rotation support"""
        if not self.pk:  # Only encrypt on first save
            encryption_key = settings.ENCRYPTION_KEY
            fernet = Fernet(encryption_key)

            # Validate API credentials before encryption
            self._validate_credentials()

            # Encrypt with timestamp for key rotation (new format)
            timestamp = str(int(time.time()))

            self.api_key = fernet.encrypt(
                f"{timestamp}:{self.api_key}".encode()
            ).decode()

            self.api_secret = fernet.encrypt(
                f"{timestamp}:{self.api_secret}".encode()
            ).decode()

            if self.api_passphrase:
                self.api_passphrase = fernet.encrypt(
                    f"{timestamp}:{self.api_passphrase}".encode()
                ).decode()

        super().save(*args, **kwargs)

    def _validate_credentials(self):
        """Validate API credentials format before saving"""
        if not self.api_key or len(self.api_key) < 10:
            raise ValidationError("API key appears to be invalid")

        if not self.api_secret or len(self.api_secret) < 10:
            raise ValidationError("API secret appears to be invalid")

        # Exchange-specific validation
        if self.exchange == 'coinbase' and not self.api_passphrase:
            raise ValidationError("Coinbase requires an API passphrase")

    def get_decrypted_credentials(self):
        """Enhanced decryption with timestamp validation and backward compatibility"""
        encryption_key = settings.ENCRYPTION_KEY
        fernet = Fernet(encryption_key)

        try:
            # Decrypt API key
            decrypted_key_data = fernet.decrypt(self.api_key.encode()).decode()

            # Check if this is new format (with timestamp) or old format
            if ':' in decrypted_key_data and decrypted_key_data.split(':', 1)[0].isdigit():
                # New format with timestamp
                timestamp_key, decrypted_key = decrypted_key_data.split(':', 1)
                new_format = True
            else:
                # Old format without timestamp
                decrypted_key = decrypted_key_data
                timestamp_key = None
                new_format = False

            # Decrypt API secret
            decrypted_secret_data = fernet.decrypt(self.api_secret.encode()).decode()

            if new_format:
                # Expect new format for secret too
                if ':' in decrypted_secret_data and decrypted_secret_data.split(':', 1)[0].isdigit():
                    timestamp_secret, decrypted_secret = decrypted_secret_data.split(':', 1)

                    # Validate timestamps match (basic integrity check)
                    if timestamp_key != timestamp_secret:
                        raise ValueError("Credential integrity check failed")
                else:
                    # Mixed format - this shouldn't happen but handle gracefully
                    logger.warning(f"Mixed encryption formats detected for exchange {self.id}")
                    decrypted_secret = decrypted_secret_data
            else:
                # Old format
                decrypted_secret = decrypted_secret_data

            # Handle passphrase (if exists)
            decrypted_passphrase = None
            if self.api_passphrase:
                decrypted_passphrase_data = fernet.decrypt(self.api_passphrase.encode()).decode()

                if new_format and ':' in decrypted_passphrase_data and decrypted_passphrase_data.split(':', 1)[
                    0].isdigit():
                    # New format
                    _, decrypted_passphrase = decrypted_passphrase_data.split(':', 1)
                else:
                    # Old format
                    decrypted_passphrase = decrypted_passphrase_data

            # Log if we're using old format (for migration tracking)
            if not new_format:
                logger.info(
                    f"Using legacy encryption format for exchange {self.id}. Consider re-saving credentials for enhanced security.")

            return {
                'api_key': decrypted_key,
                'api_secret': decrypted_secret,
                'api_passphrase': decrypted_passphrase
            }

        except Exception as e:
            logger.error(f"Error decrypting credentials for exchange {self.id}: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            raise ValueError("Failed to decrypt API credentials")

    def migrate_to_enhanced_encryption(self):
        """Migrate existing credentials to enhanced encryption format"""
        if self.pk:  # Only for existing records
            try:
                # Get current decrypted credentials
                current_creds = self.get_decrypted_credentials()

                # Re-encrypt with new format
                encryption_key = settings.ENCRYPTION_KEY
                fernet = Fernet(encryption_key)
                timestamp = str(int(time.time()))

                self.api_key = fernet.encrypt(
                    f"{timestamp}:{current_creds['api_key']}".encode()
                ).decode()

                self.api_secret = fernet.encrypt(
                    f"{timestamp}:{current_creds['api_secret']}".encode()
                ).decode()

                if current_creds['api_passphrase']:
                    self.api_passphrase = fernet.encrypt(
                        f"{timestamp}:{current_creds['api_passphrase']}".encode()
                    ).decode()

                # Save without triggering the save method's encryption logic
                super().save(update_fields=['api_key', 'api_secret', 'api_passphrase'])

                logger.info(f"Successfully migrated credentials for exchange {self.id} to enhanced format")

            except Exception as e:
                logger.error(f"Failed to migrate credentials for exchange {self.id}: {e}")
                raise


class CexTransaction(models.Model):
    """Represents a transaction from a centralized exchange"""

    class TransactionType(models.TextChoices):
        BUY = 'buy', 'Buy'
        SELL = 'sell', 'Sell'
        DEPOSIT = 'deposit', 'Deposit'
        WITHDRAWAL = 'withdrawal', 'Withdrawal'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cex_transactions')
    exchange = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=255)
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    timestamp = models.DateTimeField()
    asset_symbol = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=30, decimal_places=18)
    price_usd = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    value_usd = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    fee_amount = models.DecimalField(max_digits=30, decimal_places=18, default=0)
    fee_asset = models.CharField(max_length=50, null=True, blank=True)
    fee_usd = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    # For FIFO calculation
    cost_basis_usd = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    realized_profit_loss = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    # Source tracking
    source_file = models.CharField(max_length=255, null=True, blank=True)  # For CSV imports
    remaining_amount = models.DecimalField(max_digits=30, decimal_places=18, null=True, blank=True)

    class Meta:
        unique_together = ('user', 'exchange', 'transaction_id')
        indexes = [
            models.Index(fields=['user', 'exchange', 'asset_symbol']),
            models.Index(fields=['user', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.exchange}: {self.transaction_type} {self.amount} {self.asset_symbol} at {self.timestamp}"


class CsvImport(models.Model):
    """Tracks CSV file imports"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='csv_imports')
    exchange = models.CharField(max_length=50)
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=512)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    transactions_imported = models.IntegerField(default=0)
    errors = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.exchange} import: {self.file_name} ({self.status})"


class TransactionFee(models.Model):
    """Comprehensive fee tracking for tax calculations"""

    FEE_TYPE_CHOICES = [

        ('trading_fee', 'Trading Fee'),

        ('gas_fee', 'Gas Fee'),

        ('network_fee', 'Network Fee'),

        ('withdrawal_fee', 'Withdrawal Fee'),

        ('deposit_fee', 'Deposit Fee'),

        ('conversion_fee', 'Conversion Fee'),

        ('slippage_loss', 'Slippage Loss'),

        ('bridge_fee', 'Bridge Fee'),

        ('maker_fee', 'Maker Fee'),

        ('taker_fee', 'Taker Fee'),

        ('funding_fee', 'Funding Fee'),

        ('liquidation_fee', 'Liquidation Fee'),

        ('borrowing_fee', 'Interest/Borrowing Fee'),

        ('staking_fee', 'Staking Fee'),

        ('unstaking_fee', 'Unstaking Fee'),

        ('other_fee', 'Other Fee'),

    ]

    # Link to the main transaction

    transaction = models.ForeignKey('Transaction', on_delete=models.CASCADE, related_name='fees', null=True, blank=True)

    cex_transaction = models.ForeignKey('CexTransaction', on_delete=models.CASCADE, related_name='fees', null=True,
                                        blank=True)

    fee_type = models.CharField(max_length=20, choices=FEE_TYPE_CHOICES)

    fee_amount = models.DecimalField(max_digits=30, decimal_places=18)

    fee_asset = models.CharField(max_length=50)

    fee_usd_value = models.DecimalField(max_digits=20, decimal_places=8)

    is_tax_deductible = models.BooleanField(default=True)

    # For complex fee structures

    fee_description = models.TextField(null=True, blank=True)

    timestamp = models.DateTimeField()

    class Meta:
        indexes = [

            models.Index(fields=['fee_type', 'timestamp']),

            models.Index(fields=['is_tax_deductible']),

        ]

    def str(self):
        return f"{self.fee_type}: {self.fee_amount} {self.fee_asset} (${self.fee_usd_value})"
