from django.contrib.auth import get_user_model, authenticate
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Wallet, Transaction, AssetHolding, TaxSummary, PremiumUser, CsvImport, CexTransaction, \
    ExchangeCredential

User = get_user_model()


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
    transactions_with_tax_issues = serializers.IntegerField(required=False, default=0)
    earliest_transaction = serializers.DateTimeField(required=False)
    latest_transaction = serializers.DateTimeField(required=False)
    positive_transactions_percent = serializers.IntegerField()

    # Additional fields
    total_value_usd = serializers.FloatField()
    holdings = AssetHoldingSerializer(many=True, required=False)
    monthly_pnl = serializers.ListField(child=serializers.DictField(), required=False)
    recent_transactions = serializers.ListField(child=serializers.DictField(), required=False)


class Form8949EntrySerializer(serializers.Serializer):
    """Serializer for individual Form 8949 entry"""
    description = serializers.CharField(max_length=255)
    date_acquired = serializers.DateField()
    date_sold = serializers.DateField()
    proceeds = serializers.DecimalField(max_digits=20, decimal_places=2)
    cost_basis = serializers.DecimalField(max_digits=20, decimal_places=2)
    gain_or_loss = serializers.DecimalField(max_digits=20, decimal_places=2)
    is_short_term = serializers.BooleanField()
    source = serializers.CharField(max_length=10)  # 'DEX' or 'CEX'
    transaction_id = serializers.CharField(max_length=255, required=False)


class Form8949Serializer(serializers.Serializer):
    """Serializer for complete IRS Form 8949"""
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


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    wallet_addresses = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'wallet_addresses', 'is_premium', 'premium_until')
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user

    def get_wallet_addresses(self, obj):
        # Transform simple address list into objects with address and chain
        addresses = []
        for address in obj.wallet_addresses:
            wallet = Wallet.objects.get(address=address)
            addresses.append({"address": address, "chain": wallet.chain})
        return addresses


class UserLoginSerializer(TokenObtainPairSerializer):
    username_field = 'email'

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        if email and password:
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                raise serializers.ValidationError('Invalid email or password')
            user = authenticate(request=self.context.get('request'), username=user.username, password=password)

            if not user:
                raise serializers.ValidationError('Invalid email or password')

            if not user.is_active:
                raise serializers.ValidationError('User account is disabled')

        else:
            raise serializers.ValidationError('Email and password are required')

        refresh = self.get_token(user)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'username': user.username,
            'email': user.email,
            'is_premium': user.is_premium,
        }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['username'] = user.username
        token['email'] = user.email
        token['is_premium'] = user.is_premium
        return token


class ExchangeCredentialSerializer(serializers.ModelSerializer):
    """Serializer for exchange credentials"""

    # Don't return sensitive data
    api_key = serializers.CharField(write_only=True)
    api_secret = serializers.CharField(write_only=True)
    api_passphrase = serializers.CharField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = ExchangeCredential
        fields = ['id', 'exchange', 'api_key', 'api_secret', 'api_passphrase',
                  'is_active', 'last_sync', 'created_at', 'updated_at']
        read_only_fields = ['id', 'last_sync', 'created_at', 'updated_at']

    def create(self, validated_data):
        # The API key, secret, and passphrase will be encrypted in the model's save method
        return super().create(validated_data)


class CexTransactionSerializer(serializers.ModelSerializer):
    """Serializer for CEX transactions"""

    class Meta:
        model = CexTransaction
        fields = [
            'id', 'exchange', 'transaction_id', 'transaction_type',
            'timestamp', 'asset_symbol', 'amount', 'price_usd',
            'value_usd', 'fee_amount', 'fee_asset', 'fee_usd',
            'cost_basis_usd', 'realized_profit_loss', 'source_file'
        ]
        read_only_fields = ['id']


class CsvImportSerializer(serializers.ModelSerializer):
    """Serializer for CSV imports"""

    class Meta:
        model = CsvImport
        fields = [
            'id', 'exchange', 'file_name', 'status',
            'transactions_imported', 'errors', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class CombinedTransactionSerializer(serializers.Serializer):
    """Serializer for combined transactions (DEX + CEX)"""

    # Common fields for both DEX and CEX transactions
    id = serializers.CharField()
    timestamp = serializers.DateTimeField()
    transaction_type = serializers.CharField()
    asset_symbol = serializers.CharField()
    amount = serializers.DecimalField(max_digits=30, decimal_places=18)
    price_usd = serializers.DecimalField(max_digits=20, decimal_places=8, allow_null=True)
    value_usd = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    fee_usd = serializers.DecimalField(max_digits=20, decimal_places=2, default=0)
    cost_basis_usd = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    realized_profit_loss = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)

    # Source type identifier
    source = serializers.CharField()  # 'dex' or 'cex'

    # DEX-specific fields
    transaction_hash = serializers.CharField(required=False, allow_null=True)
    wallet = serializers.CharField(required=False, allow_null=True)

    # CEX-specific fields
    exchange = serializers.CharField(required=False, allow_null=True)
    transaction_id = serializers.CharField(required=False, allow_null=True)
    fee_amount = serializers.DecimalField(max_digits=30, decimal_places=18, required=False, allow_null=True)
    fee_asset = serializers.CharField(required=False, allow_null=True)


class WalletAddressSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=255)
    chain = serializers.CharField(max_length=50)

    def validate_address(self, value):
        """
        Validate wallet address format based on blockchain standards
        """
        import re

        # Get the chain from the request data
        chain = self.initial_data.get('chain', 'ethereum').lower()

        if chain in ['ethereum', 'arbitrum', 'polygon', 'bsc', 'base']:
            # Ethereum-compatible address validation (42 characters, starts with 0x)
            eth_pattern = r'^0x[a-fA-F0-9]{40}$'
            if not re.match(eth_pattern, value):
                raise serializers.ValidationError(
                    f"Invalid {chain.title()} address format. Expected 42 characters starting with '0x' followed by 40 hexadecimal characters."
                )

            # Additional checksum validation for Ethereum addresses
            try:
                from web3 import Web3
                if not Web3.is_checksum_address(value):
                    # Try to convert to checksum address
                    value = Web3.to_checksum_address(value.lower())
            except:
                # If Web3 validation fails, we still accept the basic format
                pass

        elif chain == 'solana':
            # Solana address validation (base58 encoded, 32-44 characters)
            solana_pattern = r'^[1-9A-HJ-NP-Za-km-z]{32,44}$'
            if not re.match(solana_pattern, value):
                raise serializers.ValidationError(
                    "Invalid Solana address format. Expected 32-44 base58 characters (excluding 0, O, I, l)."
                )
        else:
            # Basic length validation for unknown chains
            if len(value) < 10:
                raise serializers.ValidationError("Address seems too short to be valid")

        return value


class UserWalletAddressesSerializer(serializers.ModelSerializer):
    wallet_addresses = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['wallet_addresses']

    def get_wallet_addresses(self, obj):
        # Transform simple address list into objects with address and chain
        addresses = []
        for address in obj.wallet_addresses:
            wallet = Wallet.objects.get(address=address)
            addresses.append({"address": address, "chain": wallet.chain})
        return addresses

