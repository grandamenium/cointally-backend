import json
import logging
import datetime
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Sum, Count, Q
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import Wallet, Transaction, AssetHolding, TaxSummary, PremiumUser
from .serializers import (
    WalletSerializer, TransactionSerializer, AssetHoldingSerializer,
    TaxSummarySerializer, PremiumUserSerializer, WalletAnalysisSerializer,
    Form8949Serializer, MonthlyReportSerializer
)
from .utils.blockchain_apis import (
    fetch_ethereum_transactions, fetch_solana_transactions,
    fetch_polygon_transactions, fetch_price_data, fetch_multiple_chain_transactions
)
from .utils.tax_calculator import (
    calculate_cost_basis_fifo, calculate_realized_gains,
    generate_tax_summary, generate_form_8949
)

logger = logging.getLogger(__name__)


class WalletViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing wallet data
    """
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer

    @action(detail=False, methods=['post'])
    def analyze(self, request):
        """
        Analyze a wallet address and return tax information.
        This is the main endpoint for the freemium service.
        """
        address = request.data.get('address')
        chain = request.data.get('chain', 'ethereum')  # Default to Ethereum

        if not address:
            return Response(
                {"error": "Wallet address is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Normalize address format
        if chain == 'ethereum' or chain == 'polygon':
            address = address.lower()

        # Check if wallet exists in our database
        try:
            wallet = Wallet.objects.get(address=address, chain=chain)
            # If wallet exists, check if we need to update data
            last_updated = wallet.last_updated
            current_time = timezone.now()

            # If wallet data is older than 1 hour, update it
            # if (current_time - last_updated).total_seconds() > 3600:
            self._fetch_and_process_transactions(wallet)
        except Wallet.DoesNotExist:
            # Create new wallet and fetch transactions
            wallet = Wallet.objects.create(address=address, chain=chain)
            self._fetch_and_process_transactions(wallet)

        # Prepare response data
        transactions = wallet.transactions.all().order_by('-timestamp')
        holdings = wallet.holdings.all()

        # Basic stats
        total_realized_gain = transactions.aggregate(
            total=Sum('realized_profit_loss', default=0)
        )['total'] or 0

        total_transactions = transactions.count()

        earliest_tx = transactions.order_by('timestamp').first()
        latest_tx = transactions.order_by('-timestamp').first()

        earliest_transaction = earliest_tx.timestamp if earliest_tx else timezone.now()
        latest_transaction = latest_tx.timestamp if latest_tx else timezone.now()

        positive_txs = transactions.filter(realized_profit_loss__gt=0).count()
        positive_transactions_percent = (
            int((positive_txs / total_transactions) * 100)
            if total_transactions > 0 else 0
        )

        total_value_usd = holdings.aggregate(
            total=Sum('value_usd', default=0)
        )['total'] or 0

        # Calculate monthly P&L
        monthly_pnl = self._calculate_monthly_pnl(wallet)

        # Get recent transactions (limited to 10)
        recent_transactions = transactions[:10]

        # Prepare response
        response_data = {
            'address': wallet.address,
            'chain': wallet.chain,
            'total_realized_gain': float(total_realized_gain),
            'total_transactions': total_transactions,
            'earliest_transaction': earliest_transaction,
            'latest_transaction': latest_transaction,
            'positive_transactions_percent': positive_transactions_percent,
            'total_value_usd': float(total_value_usd),
            'holdings': AssetHoldingSerializer(holdings, many=True).data,
            'monthly_pnl': monthly_pnl,
            'recent_transactions': TransactionSerializer(recent_transactions, many=True).data
        }

        serializer = WalletAnalysisSerializer(data=response_data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)

    def _fetch_and_process_transactions(self, wallet):
        """Fetch and process transactions for a wallet"""
        try:
            # Fetch transactions from blockchain APIs
            transactions = fetch_multiple_chain_transactions(wallet)

            # Process and store transactions
            self._process_transactions(wallet, transactions)

            # Update holdings
            self._update_holdings(wallet)

            # Update wallet last_updated timestamp
            wallet.last_updated = timezone.now()
            wallet.save()

        except Exception as e:
            logger.error(f"Error fetching transactions for wallet {wallet.address}: {str(e)}")
            raise

    def _process_transactions(self, wallet, transactions):
        """Process and store transactions, calculating cost basis and realized gains"""
        for tx_data in transactions:
            # Check if transaction already exists
            tx_hash = tx_data.get('transaction_hash')
            if not Transaction.objects.filter(wallet=wallet, transaction_hash=tx_hash).exists():
                # Create transaction object
                transaction = Transaction(
                    wallet=wallet,
                    transaction_hash=tx_hash,
                    timestamp=tx_data.get('timestamp'),
                    transaction_type=tx_data.get('transaction_type'),
                    asset_symbol=tx_data.get('asset_symbol'),
                    amount=tx_data.get('amount'),
                    price_usd=tx_data.get('price_usd'),
                    value_usd=tx_data.get('value_usd'),
                    fee_usd=tx_data.get('fee_usd', 0)
                )

                # Calculate cost basis and realized profit/loss if it's a sell
                if transaction.transaction_type == 'sell':
                    cost_basis, realized_pnl = calculate_cost_basis_fifo(
                        wallet, transaction.asset_symbol, transaction.amount, transaction.timestamp
                    )
                    transaction.cost_basis_usd = cost_basis
                    transaction.realized_profit_loss = realized_pnl

                # Save transaction
                transaction.save()

    def _update_holdings(self, wallet):
        """Update current asset holdings for a wallet"""
        # Get unique assets from transactions
        assets = wallet.transactions.values_list('asset_symbol', flat=True).distinct()

        for asset in assets:
            # Calculate total amount of asset held
            buys = wallet.transactions.filter(
                asset_symbol=asset,
                transaction_type__in=['buy', 'swap']
            ).aggregate(total=Sum('amount', default=0))['total'] or 0

            sells = wallet.transactions.filter(
                asset_symbol=asset,
                transaction_type='sell'
            ).aggregate(total=Sum('amount', default=0))['total'] or 0

            amount = buys - sells

            # Skip if amount is zero or negative
            if amount <= 0:
                AssetHolding.objects.filter(wallet=wallet, asset_symbol=asset).delete()
                continue

            # Get current price
            current_price = fetch_price_data(asset)
            value_usd = amount * current_price

            # Update or create holding
            AssetHolding.objects.update_or_create(
                wallet=wallet,
                asset_symbol=asset,
                defaults={
                    'amount': amount,
                    'current_price_usd': current_price,
                    'value_usd': value_usd
                }
            )

    def _calculate_monthly_pnl(self, wallet):
        """Calculate monthly profit and loss for a wallet"""
        # Get all transactions with realized profit/loss
        transactions = wallet.transactions.filter(
            realized_profit_loss__isnull=False
        ).order_by('timestamp')

        if not transactions:
            return []

        # Get date range
        start_date = transactions.first().timestamp.date().replace(day=1)
        end_date = transactions.last().timestamp.date().replace(day=1)

        # Generate monthly intervals
        current_date = start_date
        monthly_pnl = []

        while current_date <= end_date:
            next_month = current_date.replace(day=28) + timezone.timedelta(days=4)
            next_month = next_month.replace(day=1)

            # Get transactions for this month
            month_transactions = transactions.filter(
                timestamp__gte=timezone.make_aware(
                    timezone.datetime.combine(current_date, timezone.datetime.min.time())),
                timestamp__lt=timezone.make_aware(timezone.datetime.combine(next_month, timezone.datetime.min.time()))
            )

            # Calculate total profit/loss for the month
            total_pnl = month_transactions.aggregate(
                total=Sum('realized_profit_loss', default=0)
            )['total'] or 0

            # Format month name
            month_name = current_date.strftime('%b')

            monthly_pnl.append({
                'month': month_name,
                'year': current_date.year,
                'profit': float(total_pnl)
            })

            # Move to next month
            current_date = next_month

        return monthly_pnl


class PremiumFeatureViewSet(viewsets.ViewSet):
    """
    API endpoints for premium features
    """

    def _check_premium_access(self, user_id):
        """Check if user has premium access"""
        try:
            premium_user = PremiumUser.objects.get(user_id=user_id, is_active=True)
            current_date = timezone.now().date()
            return (
                    premium_user.subscription_start <= current_date and
                    premium_user.subscription_end >= current_date
            )
        except PremiumUser.DoesNotExist:
            return False

    @action(detail=False, methods=['post'])
    def form_8949(self, request):
        """Generate IRS Form 8949 (for premium users)"""
        user_id = request.data.get('user_id')
        wallet_address = request.data.get('wallet_address')
        chain = request.data.get('chain', 'ethereum')
        tax_year = request.data.get('tax_year', timezone.now().year - 1)

        # Check premium access
        if not self._check_premium_access(user_id):
            return Response(
                {"error": "This feature requires a premium subscription."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            wallet = Wallet.objects.get(address=wallet_address, chain=chain)
        except Wallet.DoesNotExist:
            return Response(
                {"error": "Wallet not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Generate Form 8949 data
        form_data = generate_form_8949(wallet, tax_year)

        serializer = Form8949Serializer(data=form_data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def monthly_report(self, request):
        """Generate monthly report (for premium users)"""
        user_id = request.data.get('user_id')
        wallet_address = request.data.get('wallet_address')
        chain = request.data.get('chain', 'ethereum')
        year = request.data.get('year', timezone.now().year)
        month = request.data.get('month', timezone.now().month)

        # Check premium access
        if not self._check_premium_access(user_id):
            return Response(
                {"error": "This feature requires a premium subscription."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            wallet = Wallet.objects.get(address=wallet_address, chain=chain)
        except Wallet.DoesNotExist:
            return Response(
                {"error": "Wallet not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get start and end dates for the specified month
        try:
            start_date = datetime.date(year, month, 1)
            if month == 12:
                end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        except ValueError:
            return Response(
                {"error": "Invalid year or month."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get transactions for the month
        transactions = wallet.transactions.filter(
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date
        ).order_by('timestamp')

        if not transactions.exists():
            return Response(
                {"error": f"No transactions found for {start_date.strftime('%B %Y')}."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Calculate monthly stats
        total_transactions = transactions.count()

        total_buys = transactions.filter(
            transaction_type__in=['buy', 'swap']
        ).aggregate(total=Sum('value_usd', default=0))['total'] or Decimal('0.00')

        total_sells = transactions.filter(
            transaction_type='sell'
        ).aggregate(total=Sum('value_usd', default=0))['total'] or Decimal('0.00')

        realized_profit_loss = transactions.filter(
            realized_profit_loss__isnull=False
        ).aggregate(total=Sum('realized_profit_loss', default=0))['total'] or Decimal('0.00')

        total_fees = transactions.aggregate(
            total=Sum('fee_usd', default=0)
        )['total'] or Decimal('0.00')

        # Get top assets by transaction count
        top_assets = []
        assets = transactions.values('asset_symbol').annotate(
            count=Count('id')
        ).order_by('-count')[:5]

        for asset in assets:
            symbol = asset['asset_symbol']
            count = asset['count']

            # Get asset realized profit/loss
            asset_pnl = transactions.filter(
                asset_symbol=symbol,
                realized_profit_loss__isnull=False
            ).aggregate(total=Sum('realized_profit_loss', default=0))['total'] or Decimal('0.00')

            top_assets.append({
                'symbol': symbol,
                'transaction_count': count,
                'realized_profit_loss': float(asset_pnl)
            })

        # Prepare response
        response_data = {
            'month': start_date,
            'total_transactions': total_transactions,
            'total_buys': total_buys,
            'total_sells': total_sells,
            'realized_profit_loss': realized_profit_loss,
            'total_fees': total_fees,
            'top_assets': top_assets
        }

        serializer = MonthlyReportSerializer(data=response_data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def fee_calculator(self, request):
        """Calculate gas and trading fees (for premium users)"""
        user_id = request.data.get('user_id')
        wallet_address = request.data.get('wallet_address')
        chain = request.data.get('chain', 'ethereum')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        # Check premium access
        if not self._check_premium_access(user_id):
            return Response(
                {"error": "This feature requires a premium subscription."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            wallet = Wallet.objects.get(address=wallet_address, chain=chain)
        except Wallet.DoesNotExist:
            return Response(
                {"error": "Wallet not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Parse date ranges
        try:
            if start_date:
                start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
            else:
                start_date = timezone.now().date().replace(month=1, day=1)

            if end_date:
                end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
            else:
                end_date = timezone.now().date()
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get transactions for date range
        transactions = wallet.transactions.filter(
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date
        )

        if not transactions.exists():
            return Response(
                {"error": "No transactions found for the specified date range."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Calculate fee summary
        total_fees = transactions.aggregate(
            total=Sum('fee_usd', default=0)
        )['total'] or Decimal('0.00')

        # Calculate fees by transaction type
        fees_by_type = {}
        for tx_type in Transaction.TransactionType.values:
            type_fees = transactions.filter(
                transaction_type=tx_type
            ).aggregate(total=Sum('fee_usd', default=0))['total'] or Decimal('0.00')

            fees_by_type[tx_type] = float(type_fees)

        # Calculate monthly fee distribution
        monthly_fees = []
        current_date = start_date.replace(day=1)
        end_month = end_date.replace(day=1)

        while current_date <= end_month:
            next_month = (current_date.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

            month_fees = transactions.filter(
                timestamp__gte=datetime.datetime.combine(current_date, datetime.time.min),
                timestamp__lt=datetime.datetime.combine(next_month, datetime.time.min)
            ).aggregate(total=Sum('fee_usd', default=0))['total'] or Decimal('0.00')

            monthly_fees.append({
                'month': current_date.strftime('%b %Y'),
                'fees': float(month_fees)
            })

            current_date = next_month

        response_data = {
            'total_fees': float(total_fees),
            'fees_by_type': fees_by_type,
            'monthly_fees': monthly_fees,
            'start_date': start_date,
            'end_date': end_date
        }

        return Response(response_data)

    @action(detail=False, methods=['post'])
    def multi_wallet_summary(self, request):
        """Generate a summary for multiple wallets (for premium users)"""
        user_id = request.data.get('user_id')
        wallet_addresses = request.data.get('wallet_addresses', [])

        # Check premium access
        if not self._check_premium_access(user_id):
            return Response(
                {"error": "This feature requires a premium subscription."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not wallet_addresses:
            return Response(
                {"error": "No wallet addresses provided."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Fetch wallets
        wallets = Wallet.objects.filter(address__in=wallet_addresses)

        if not wallets.exists():
            return Response(
                {"error": "No matching wallets found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Prepare summary data
        wallet_summaries = []
        total_realized_gain = Decimal('0.00')
        total_portfolio_value = Decimal('0.00')

        for wallet in wallets:
            # Get wallet transactions and holdings
            transactions = wallet.transactions.all()
            holdings = wallet.holdings.all()

            # Calculate wallet-specific stats
            wallet_realized_gain = transactions.aggregate(
                total=Sum('realized_profit_loss', default=0)
            )['total'] or Decimal('0.00')

            wallet_value = holdings.aggregate(
                total=Sum('value_usd', default=0)
            )['total'] or Decimal('0.00')

            # Add to totals
            total_realized_gain += wallet_realized_gain
            total_portfolio_value += wallet_value

            # Add wallet summary
            wallet_summaries.append({
                'address': wallet.address,
                'chain': wallet.chain,
                'realized_gain': float(wallet_realized_gain),
                'portfolio_value': float(wallet_value),
                'transaction_count': transactions.count()
            })

        # Prepare response
        response_data = {
            'wallet_count': wallets.count(),
            'wallet_summaries': wallet_summaries,
            'total_realized_gain': float(total_realized_gain),
            'total_portfolio_value': float(total_portfolio_value)
        }

        return Response(response_data)