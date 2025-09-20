import logging
import datetime
from datetime import datetime
import logging
import mimetypes
import traceback
from decimal import Decimal
from io import StringIO

import pandas as pd
import requests
from django.db.models import Sum, Count, Avg, Max, Min
from django.db.models.functions import TruncMonth, TruncDate
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status, viewsets, generics, serializers
from rest_framework.decorators import action, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import status, viewsets, views
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os
import uuid
from django.db import models
import time
from django.core.cache import cache
from rest_framework.decorators import api_view

from .models import ExchangeCredential, CexTransaction, CsvImport, User

from .models import Wallet, Transaction, AssetHolding, PremiumUser
from .serializers import (
    WalletSerializer, TransactionSerializer, AssetHoldingSerializer,
    WalletAnalysisSerializer,
    Form8949Serializer, MonthlyReportSerializer, UserSerializer, UserLoginSerializer, CexTransactionSerializer,
    ExchangeCredentialSerializer, WalletAddressSerializer, UserWalletAddressesSerializer
)
from .services.csv_service import CsvImportService, ActuallyWorkingBinanceService, CorrectBinanceTransactionProcessor
from .services.exchange_services import ExchangeServiceFactory
from .services.sync_progress_service import SyncProgressService
from .services.tax_calculation_service import TaxCalculationService
from .utils.blockchain_apis import (
    fetch_price_data, fetch_multiple_chain_transactions
)
from .utils.tax_calculator import (
    calculate_cost_basis_fifo, generate_form_8949
)
from crypto_tax_api.services.coinbase_oauth_service import CoinbaseOAuthService
from crypto_tax_api.services.coinbase_cdp_auth import (
    CoinbaseAdvancedClient, CdpKeyEncryption, parse_cdp_key,
    extract_key_meta, process_fill_for_tax, sanitize_log_data
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

        logger.info(f"WALLET_ANALYZE_REQUEST: address={address[:10]}...{address[-6:] if address else None}, chain={chain}")

        if not address:
            logger.warning("WALLET_ANALYZE_ERROR: No address provided")
            return Response(
                {"error": "Wallet address is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Normalize address format
        if chain == 'ethereum' or chain == 'polygon' or chain == 'arbitrum' or chain == 'hyperliquid' or chain == 'bsc':
            address = address.lower()
            logger.info(f"WALLET_ADDRESS_NORMALIZED: {address[:10]}...{address[-6:]} for chain {chain}")

        # Check if wallet exists in our database
        try:
            wallet = Wallet.objects.get(address=address, chain=chain)
            logger.info(f"WALLET_EXISTS: Found existing wallet for {address[:10]}...{address[-6:]}")
            # If wallet exists, check if we need to update data
            last_updated = wallet.last_updated
            current_time = timezone.now()
            tx_count = wallet.transactions.count()

            # If wallet data is older than 1 hour OR no transactions exist, update it
            if (current_time - last_updated).total_seconds() > 3600 or tx_count == 0:
                logger.info(f"WALLET_UPDATE_NEEDED: Last updated {last_updated}, tx_count={tx_count}")
                try:
                    error_txs = self._fetch_and_process_transactions(wallet)
                except ConnectionError as e:
                    return Response(
                        {"error": "Connection Error", "message": str(e), "retry": True},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE
                    )
                except PermissionError as e:
                    return Response(
                        {"error": "Authentication Error", "message": str(e), "retry": False},
                        status=status.HTTP_401_UNAUTHORIZED
                    )
                except ValueError as e:
                    return Response(
                        {"error": "Invalid Address", "message": str(e), "retry": False},
                        status=status.HTTP_400_BAD_REQUEST
                    )
                except RuntimeError as e:
                    return Response(
                        {"error": "Processing Error", "message": str(e), "retry": True},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            else:
                logger.info(f"WALLET_CACHE_HIT: Using cached data, tx_count={tx_count}")
        except Wallet.DoesNotExist:
            logger.info(f"WALLET_NEW: Creating new wallet for {address[:10]}...{address[-6:]}")
            # Create new wallet and fetch transactions
            wallet = Wallet.objects.create(address=address, chain=chain)
            try:
                error_txs = self._fetch_and_process_transactions(wallet)
            except ConnectionError as e:
                return Response(
                    {"error": "Connection Error", "message": str(e), "retry": True},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            except PermissionError as e:
                return Response(
                    {"error": "Authentication Error", "message": str(e), "retry": False},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            except ValueError as e:
                return Response(
                    {"error": "Invalid Address", "message": str(e), "retry": False},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except RuntimeError as e:
                return Response(
                    {"error": "Processing Error", "message": str(e), "retry": True},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Prepare response data
        transactions = wallet.transactions.all().order_by('-timestamp')
        holdings = wallet.holdings.all()

        # Basic stats
        total_realized_gain = transactions.filter(realized_profit_loss__isnull=False).aggregate(
            total=Sum('realized_profit_loss', default=0)
        )['total'] or 0

        total_transactions = transactions.count()

        # Count transactions with tax issues
        tx_with_issues = transactions.filter(
            realized_profit_loss__isnull=True,
            transaction_type='sell'
        ).count()

        earliest_tx = transactions.order_by('timestamp').first()
        latest_tx = transactions.order_by('-timestamp').first()

        earliest_transaction = earliest_tx.timestamp if earliest_tx else timezone.now()
        latest_transaction = latest_tx.timestamp if latest_tx else timezone.now()

        positive_txs = transactions.filter(realized_profit_loss__gt=0).count()
        calculable_txs = transactions.filter(realized_profit_loss__isnull=False).count()
        positive_transactions_percent = (
            int((positive_txs / calculable_txs) * 100)
            if calculable_txs > 0 else 0
        )

        total_value_usd = holdings.aggregate(
            total=Sum('value_usd', default=0)
        )['total'] or 0

        # Calculate monthly P&L
        monthly_pnl = self._calculate_monthly_pnl(wallet)

        # Prepare response - serialize transactions separately to avoid validation issues
        serialized_transactions = []
        for tx in transactions:
            serialized_transactions.append({
                'id': tx.id,
                'wallet': tx.wallet.id,
                'transaction_hash': tx.transaction_hash,
                'timestamp': tx.timestamp,
                'transaction_type': tx.transaction_type,
                'asset_symbol': tx.asset_symbol,
                'amount': str(tx.amount),
                'price_usd': str(tx.price_usd),
                'value_usd': str(tx.value_usd),
                'fee_usd': str(tx.fee_usd) if tx.fee_usd else '0.00',
                'cost_basis_usd': str(tx.cost_basis_usd) if tx.cost_basis_usd else None,
                'realized_profit_loss': str(tx.realized_profit_loss) if tx.realized_profit_loss else None
            })

        response_data = {
            'address': wallet.address,
            'chain': wallet.chain,
            'total_realized_gain': float(total_realized_gain),
            'total_transactions': total_transactions,
            'transactions_with_tax_issues': tx_with_issues,
            'earliest_transaction': earliest_transaction,
            'latest_transaction': latest_transaction,
            'positive_transactions_percent': positive_transactions_percent,
            'total_value_usd': float(total_value_usd),
            'holdings': AssetHoldingSerializer(holdings, many=True).data,
            'monthly_pnl': monthly_pnl,
            'recent_transactions': serialized_transactions
        }

        serializer = WalletAnalysisSerializer(data=response_data)
        if not serializer.is_valid():
            logger.error(f"Serializer validation failed: {serializer.errors}")
            logger.error(f"Response data: {response_data}")
            raise serializers.ValidationError(serializer.errors)

        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def debug(self, request):
        """
        Debug endpoint to test API connectivity and validate addresses
        """
        address = request.data.get('address')
        chain = request.data.get('chain', 'ethereum')

        debug_info = {
            'address_validation': {},
            'api_connectivity': {},
            'configuration': {},
            'timestamp': timezone.now().isoformat()
        }

        # Test address validation
        try:
            from .serializers import WalletAddressSerializer
            serializer = WalletAddressSerializer(data={'address': address, 'chain': chain})
            if serializer.is_valid():
                debug_info['address_validation']['status'] = 'valid'
                debug_info['address_validation']['normalized_address'] = serializer.validated_data['address']
            else:
                debug_info['address_validation']['status'] = 'invalid'
                debug_info['address_validation']['errors'] = serializer.errors
        except Exception as e:
            debug_info['address_validation']['status'] = 'error'
            debug_info['address_validation']['error'] = str(e)

        # Test API configuration
        try:
            from .utils.blockchain_apis import get_alchemy_api_key, ALCHEMY_ENDPOINTS

            if chain in ['ethereum', 'arbitrum', 'polygon', 'bsc']:
                api_key = get_alchemy_api_key()
                debug_info['configuration']['api_key_present'] = bool(api_key)
                debug_info['configuration']['api_key_length'] = len(api_key) if api_key else 0
                debug_info['configuration']['endpoint'] = ALCHEMY_ENDPOINTS.get(chain, 'Not configured')
            elif chain == 'solana':
                api_key = get_alchemy_api_key('ALCHEMY_SOLANA_API_KEY')
                debug_info['configuration']['solana_api_key_present'] = bool(api_key)
                debug_info['configuration']['solana_api_key_length'] = len(api_key) if api_key else 0
                debug_info['configuration']['endpoint'] = ALCHEMY_ENDPOINTS.get(chain, 'Not configured')
        except Exception as e:
            debug_info['configuration']['error'] = str(e)

        # Test basic API connectivity (without making actual blockchain calls)
        try:
            import requests
            test_url = "https://httpbin.org/get"
            response = requests.get(test_url, timeout=5)
            debug_info['api_connectivity']['internet'] = response.status_code == 200
        except Exception as e:
            debug_info['api_connectivity']['internet'] = False
            debug_info['api_connectivity']['internet_error'] = str(e)

        # Database connectivity test
        try:
            from .models import Wallet
            wallet_count = Wallet.objects.count()
            debug_info['api_connectivity']['database'] = True
            debug_info['api_connectivity']['wallet_count'] = wallet_count
        except Exception as e:
            debug_info['api_connectivity']['database'] = False
            debug_info['api_connectivity']['database_error'] = str(e)

        logger.info(f"DEBUG_ENDPOINT: {debug_info}")

        return Response(debug_info)

    def _fetch_and_process_transactions(self, wallet):
        """Fetch and process transactions for a wallet"""
        try:
            logger.info(f"FETCH_TRANSACTIONS_START: wallet={wallet.address[:10]}...{wallet.address[-6:]}, chain={wallet.chain}")

            # Fetch transactions from blockchain APIs
            transactions = fetch_multiple_chain_transactions(wallet)

            logger.info(f"FETCH_TRANSACTIONS_RESULT: Found {len(transactions)} transactions for wallet {wallet.address[:10]}...{wallet.address[-6:]}")

            # Process and store transactions
            self._process_transactions(wallet, transactions)

            # Update holdings
            self._update_holdings(wallet)

            # Update wallet last_updated timestamp
            wallet.last_updated = timezone.now()
            wallet.save()

            logger.info(f"WALLET_PROCESSING_COMPLETE: wallet={wallet.address[:10]}...{wallet.address[-6:]}")

        except ConnectionError as e:
            logger.error(f"FETCH_TRANSACTIONS_CONNECTION_ERROR: wallet={wallet.address[:10]}...{wallet.address[-6:]}, error={str(e)}")
            raise ConnectionError(str(e))
        except PermissionError as e:
            logger.error(f"FETCH_TRANSACTIONS_PERMISSION_ERROR: wallet={wallet.address[:10]}...{wallet.address[-6:]}, error={str(e)}")
            raise PermissionError(str(e))
        except ValueError as e:
            logger.error(f"FETCH_TRANSACTIONS_VALUE_ERROR: wallet={wallet.address[:10]}...{wallet.address[-6:]}, error={str(e)}")
            raise ValueError(str(e))
        except Exception as e:
            logger.error(f"FETCH_TRANSACTIONS_UNEXPECTED_ERROR: wallet={wallet.address[:10]}...{wallet.address[-6:]}, error={str(e)}")
            raise RuntimeError(f"An unexpected error occurred while processing your wallet. Please try again later.")

    def _process_transactions(self, wallet, transactions):
        """Process and store transactions, calculating cost basis and realized gains"""
        error_transactions = []

        for tx_data in transactions:
            tx_hash = tx_data.get('transaction_hash')
            
            # Prepare transaction data
            transaction_data = {
                'timestamp': tx_data.get('timestamp'),
                'transaction_type': tx_data.get('transaction_type'),
                'asset_symbol': tx_data.get('asset_symbol'),
                'amount': tx_data.get('amount'),
                'price_usd': tx_data.get('price_usd'),
                'value_usd': tx_data.get('value_usd'),
                'fee_usd': tx_data.get('fee_usd', 0)
            }

            # Calculate cost basis and realized profit/loss if it's a sell
            if transaction_data['transaction_type'] == 'sell':
                try:
                    cost_basis, realized_pnl = calculate_cost_basis_fifo(
                        wallet, transaction_data['asset_symbol'], transaction_data['amount'], transaction_data['timestamp']
                    )
                    transaction_data['cost_basis_usd'] = cost_basis
                    transaction_data['realized_profit_loss'] = realized_pnl
                except ValueError as e:
                    # Log the error
                    logger.warning(f"Cost basis calculation failed for transaction {tx_hash}: {str(e)}")

                    # Store transaction but mark it for review
                    transaction_data['cost_basis_usd'] = None  # Null cost basis
                    transaction_data['realized_profit_loss'] = None  # Null profit/loss
                    transaction_data['notes'] = str(e)  # Store the error for reference

            # Use update_or_create to prevent duplicates
            transaction, created = Transaction.objects.update_or_create(
                wallet=wallet,
                transaction_hash=tx_hash,
                defaults=transaction_data
            )
            
            # Track error transactions for potential reporting
            if transaction_data.get('notes'):
                        error_transactions.append(transaction)

        # Return list of transactions with errors for potential reporting
        return error_transactions

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
        tax_year = request.data.get('tax_year', timezone.now().year - 1)

        # Check premium access
        # if not self._check_premium_access(user_id):
        #     return Response(
        #         {"error": "This feature requires a premium subscription."},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Generate Form 8949 data
        form_data = TaxCalculationService.generate_form_8949(user, tax_year)

        serializer = Form8949Serializer(data=form_data)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def monthly_report(self, request):
        """Generate monthly report (for premium users)"""
        user_id = request.data.get('user_id')
        year = request.data.get('year', timezone.now().year)
        month = request.data.get('month', timezone.now().month)

        # Check premium access
        # if not self._check_premium_access(user_id):
        #     return Response(
        #         {"error": "This feature requires a premium subscription."},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
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

        # Get DEX transactions
        wallet_addresses = user.wallet_addresses or []
        dex_transactions = Transaction.objects.filter(
            wallet__address__in=wallet_addresses,
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date
        ).order_by('timestamp')

        # Get CEX transactions
        cex_transactions = CexTransaction.objects.filter(
            user=user,
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date
        ).order_by('timestamp')

        # Calculate combined stats
        total_transactions = dex_transactions.count() + cex_transactions.count()

        dex_buys = dex_transactions.filter(
            transaction_type__in=['buy', 'swap']
        ).aggregate(total=Sum('value_usd', default=0))['total'] or Decimal('0.00')

        cex_buys = cex_transactions.filter(
            transaction_type='buy'
        ).aggregate(total=Sum('value_usd', default=0))['total'] or Decimal('0.00')

        total_buys = dex_buys + cex_buys

        dex_sells = dex_transactions.filter(
            transaction_type='sell'
        ).aggregate(total=Sum('value_usd', default=0))['total'] or Decimal('0.00')

        cex_sells = cex_transactions.filter(
            transaction_type='sell'
        ).aggregate(total=Sum('value_usd', default=0))['total'] or Decimal('0.00')

        total_sells = dex_sells + cex_sells

        dex_pnl = dex_transactions.filter(
            realized_profit_loss__isnull=False
        ).aggregate(total=Sum('realized_profit_loss', default=0))['total'] or Decimal('0.00')

        cex_pnl = cex_transactions.filter(
            realized_profit_loss__isnull=False
        ).aggregate(total=Sum('realized_profit_loss', default=0))['total'] or Decimal('0.00')

        realized_profit_loss = dex_pnl + cex_pnl

        dex_fees = dex_transactions.aggregate(
            total=Sum('fee_usd', default=0)
        )['total'] or Decimal('0.00')

        cex_fees = cex_transactions.aggregate(
            total=Sum('fee_usd', default=0)
        )['total'] or Decimal('0.00')

        total_fees = dex_fees + cex_fees

        # Get top assets by transaction count across both DEX and CEX
        combined_assets = {}

        # Count DEX transactions by asset
        dex_assets = dex_transactions.values('asset_symbol').annotate(
            count=Count('id')
        )
        for asset in dex_assets:
            symbol = asset['asset_symbol']
            combined_assets[symbol] = combined_assets.get(symbol, {
                'symbol': symbol,
                'transaction_count': 0,
                'realized_profit_loss': Decimal('0.00')
            })
            combined_assets[symbol]['transaction_count'] += asset['count']

            # Get DEX realized PnL for this asset
            dex_asset_pnl = dex_transactions.filter(
                asset_symbol=symbol,
                realized_profit_loss__isnull=False
            ).aggregate(total=Sum('realized_profit_loss', default=0))['total'] or Decimal('0.00')

            combined_assets[symbol]['realized_profit_loss'] += dex_asset_pnl

        # Count CEX transactions by asset
        cex_assets = cex_transactions.values('asset_symbol').annotate(
            count=Count('id')
        )
        for asset in cex_assets:
            symbol = asset['asset_symbol']
            combined_assets[symbol] = combined_assets.get(symbol, {
                'symbol': symbol,
                'transaction_count': 0,
                'realized_profit_loss': Decimal('0.00')
            })
            combined_assets[symbol]['transaction_count'] += asset['count']

            # Get CEX realized PnL for this asset
            cex_asset_pnl = cex_transactions.filter(
                asset_symbol=symbol,
                realized_profit_loss__isnull=False
            ).aggregate(total=Sum('realized_profit_loss', default=0))['total'] or Decimal('0.00')

            combined_assets[symbol]['realized_profit_loss'] += cex_asset_pnl

        # Convert to list and sort by transaction count
        top_assets = list(combined_assets.values())
        top_assets.sort(key=lambda x: x['transaction_count'], reverse=True)
        top_assets = top_assets[:5]  # Get top 5

        # Prepare response
        response_data = {
            'month': start_date,
            'total_transactions': total_transactions,
            'total_buys': total_buys,
            'total_sells': total_sells,
            'realized_profit_loss': realized_profit_loss,
            'total_fees': total_fees,
            'top_assets': top_assets,
            'dex_transaction_count': dex_transactions.count(),
            'cex_transaction_count': cex_transactions.count(),
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
        # if not self._check_premium_access(user_id):
        #     return Response(
        #         {"error": "This feature requires a premium subscription."},
        #         status=status.HTTP_403_FORBIDDEN
        #     )

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


class UserRegistrationView(generics.CreateAPIView):
    permission_classes = (AllowAny,)
    serializer_class = UserSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'user': UserSerializer(user).data,
            'message': 'User registered successfully',
        }, status=status.HTTP_201_CREATED)


class UserLoginView(TokenObtainPairView):
    serializer_class = UserLoginSerializer


class UserProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class SubscriptionCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        # In a real implementation, this would initiate the Lemon Squeezy checkout
        # For now, we'll simulate a successful subscription
        user = request.user
        user.is_premium = True
        user.premium_until = timezone.now() + datetime.timedelta(days=365)  # 1 year subscription
        user.save()

        return Response({
            'success': True,
            'message': 'Subscription activated successfully',
            'premium_until': user.premium_until
        })


class SubscriptionWebhookView(APIView):
    permission_classes = ()  # No auth for webhooks

    def post(self, request):
        # This would process webhooks from Lemon Squeezy
        # For now, just return a success response
        return Response({'status': 'success'})


class SubscriptionStatusView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        user = request.user
        return Response({
            'is_premium': user.is_premium,
            'premium_until': user.premium_until
        })


class ExchangeCredentialViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing exchange credentials
    """
    serializer_class = ExchangeCredentialSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return ExchangeCredential.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=['post'])
    def upload_cdp_key(self, request):
        """
        Upload a CDP JSON key file for Coinbase Advanced Trade
        """
        import json
        import re

        try:
            # Get the CDP JSON data from request
            cdp_json = request.data.get('cdp_json')
            if not cdp_json:
                return Response({
                    'success': False,
                    'message': 'CDP JSON key is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Parse the CDP JSON
            try:
                cdp_data = json.loads(cdp_json)
            except json.JSONDecodeError:
                return Response({
                    'success': False,
                    'message': 'Invalid JSON format'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Extract key components
            if 'name' not in cdp_data or 'privateKey' not in cdp_data:
                return Response({
                    'success': False,
                    'message': 'Invalid CDP key format: missing name or privateKey'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Parse the key name to extract org_id and key_id
            match = re.match(r'organizations/([^/]+)/apiKeys/([^/]+)', cdp_data['name'])
            if not match:
                return Response({
                    'success': False,
                    'message': 'Invalid key name format'
                }, status=status.HTTP_400_BAD_REQUEST)

            org_id, key_id = match.groups()

            # Create or update the credential
            credential, created = ExchangeCredential.objects.update_or_create(
                user=request.user,
                exchange='coinbase_advanced',
                defaults={
                    'api_key': key_id,  # Store key_id in api_key field
                    'api_passphrase': org_id,  # Store org_id in api_passphrase field
                    'api_secret': cdp_json,  # Store the entire JSON in api_secret field
                    'auth_type': 'cdp',
                    'is_active': True,
                    'is_connected': True
                }
            )

            return Response({
                'success': True,
                'message': 'CDP key uploaded successfully',
                'created': created,
                'credential_id': credential.id
            })

        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error uploading CDP key: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def test_connection(self, request, pk=None):
        """
        Test the connection to the exchange
        """
        credential = self.get_object()

        try:
            # Get exchange service
            service = ExchangeServiceFactory.get_service(credential.exchange, request.user)

            # Test connection
            success, message = service.test_connection()

            return Response({
                'success': success,
                'message': message
            })
        except Exception as e:
            return Response({
                'success': False,
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def sync_transactions(self, request, pk=None):
        """
        Sync transactions from the exchange
        """
        credential = self.get_object()

        try:
            # Get start and end dates from request
            start_date = request.data.get('start_date')
            end_date = request.data.get('end_date')

            # Get exchange service
            service = ExchangeServiceFactory.get_service(credential.exchange, request.user)

            # Initialize progress tracking
            progress_key = f"sync_progress_{credential.id}"
            request.session[progress_key] = 0

            # Sync transactions
            transactions_count = service.sync_transactions(start_date, end_date, progress_callback=lambda p: request.session.update({progress_key: p}))

            # Update last sync time
            credential.last_sync = timezone.now()
            credential.save()

            # Clear progress after completion
            if progress_key in request.session:
                del request.session[progress_key]

            return Response({
                'success': True,
                'transactions_synced': transactions_count
            })
        except Exception as e:
            # Clear progress on error
            if progress_key in request.session:
                del request.session[progress_key]
            return Response({
                'success': False,
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def sync(self, request, pk=None):
        """
        Sync transactions from the exchange

        Can be called with:
        - force_full_sync=True to force a full sync
        - start_date and end_date for a custom date range
        """
        credential = self.get_object()
        force_full_sync = request.data.get('force_full_sync', False)
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        try:
            # Initialize progress tracking
            SyncProgressService.initialize_sync(credential.id)

            # Get exchange service
            service = ExchangeServiceFactory.get_service(credential.exchange, request.user)

            # Define progress callback function
            def update_progress(progress):
                SyncProgressService.update_progress(credential.id, progress)

            # Convert date strings to datetime objects if provided
            if start_date:
                try:
                    start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                except ValueError:
                    return Response({
                        'success': False,
                        'message': 'Invalid start date format. Use YYYY-MM-DD.'
                    }, status=status.HTTP_400_BAD_REQUEST)

            if end_date:
                try:
                    # Set end_date to end of day
                    end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').replace(
                        hour=23, minute=59, second=59, tzinfo=timezone.utc
                    )
                except ValueError:
                    return Response({
                        'success': False,
                        'message': 'Invalid end date format. Use YYYY-MM-DD.'
                    }, status=status.HTTP_400_BAD_REQUEST)

            # In a production environment, we should use a background task
            # For demo purposes, we'll do it synchronously
            transactions_count = service.sync_transactions(
                start_date=start_date,
                end_date=end_date,
                force_full_sync=force_full_sync,
                progress_callback=update_progress
            )

            # Update last sync time
            credential.last_sync = timezone.now()
            credential.save()

            return Response({
                'success': True,
                'transactions_synced': transactions_count
            })
        except Exception as e:
            logger.error(f"Error syncing exchange {credential.exchange}: {str(e)}")
            logger.error(traceback.format_exc())

            # Mark sync as failed
            SyncProgressService.fail_sync(credential.id, str(e))

            return Response({
                'success': False,
                'message': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def sync_progress(self, request, pk=None):
        """
        Get the current sync progress
        """
        credential = self.get_object()

        # Get progress using the SyncProgressService
        progress_data = SyncProgressService.get_progress(credential.id)

        return Response(progress_data)

    @action(detail=False, methods=['post'])
    def bulk_sync_progress(self, request):
        """
        Get sync progress for multiple exchanges in a single request
        to reduce the number of API calls and avoid rate limiting
        """
        exchange_ids = request.data.get('exchange_ids', [])

        if not exchange_ids:
            return Response({}, status=status.HTTP_200_OK)

        # Validate that all exchanges belong to the user
        valid_credentials = ExchangeCredential.objects.filter(
            user=request.user,
            id__in=exchange_ids
        )

        # Map of IDs to credentials to ensure we only access user's credentials
        valid_credential_ids = {str(cred.id): cred for cred in valid_credentials}

        # Get progress for each valid credential
        progress_data = {}
        for exchange_id in exchange_ids:
            exchange_id_str = str(exchange_id)

            # Only process if it's a valid credential
            if exchange_id_str in valid_credential_ids:
                # Get progress data
                progress_data[exchange_id_str] = SyncProgressService.get_progress(exchange_id)
            else:
                # For IDs that don't belong to the user, return an error
                progress_data[exchange_id_str] = {
                    'progress': 0,
                    'status': 'error',
                    'error': 'Exchange not found or no permission',
                    'is_complete': False,
                    'is_failed': True
                }

        return Response(progress_data, status=status.HTTP_200_OK)


class CsvUploadView(views.APIView):
    """
    CORRECTED CSV upload endpoint with proper Binance transaction processing
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Get file and exchange
            csv_file = request.FILES['file']
            exchange = request.data.get('exchange', '').lower().strip()

            if exchange != 'binance':
                return Response({
                    'success': False,
                    'error': 'Only Binance is supported with the corrected importer'
                }, status=400)

            # Save file
            from django.core.files.storage import default_storage
            from django.core.files.base import ContentFile
            from crypto_tax_api.services.csv_service import CorrectBinanceTransactionProcessor
            import uuid

            file_name = csv_file.name
            unique_id = uuid.uuid4().hex
            file_path = f"csv_imports/{request.user.id}/{unique_id}_{file_name}"
            saved_path = default_storage.save(file_path, ContentFile(csv_file.read()))

            # Import using the CORRECTED processor that matches Koinly's logic
            transactions_imported, errors = CorrectBinanceTransactionProcessor.import_binance_transaction_history(
                request.user, exchange, saved_path, file_name
            )

            return Response({
                'success': True,
                'transactions_imported': transactions_imported,
                'file_name': file_name,
                'exchange': exchange.title(),
                'message': f'Successfully imported {transactions_imported} transactions using corrected processor',
                'errors': errors[:5] if errors else [],
                'note': 'Using CORRECTED processor with proper Koinly-like transaction grouping'
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=500)

    def _validate_file(self, csv_file):
        """Validate the uploaded file"""

        # Check file extension
        if not csv_file.name.lower().endswith('.csv'):
            return 'File must be a CSV (.csv extension required)'

        # Check file size (max 50MB)
        max_size = 50 * 1024 * 1024  # 50MB
        if csv_file.size > max_size:
            return f'File size too large. Maximum size is {max_size // (1024 * 1024)}MB'

        # Check if file is empty
        if csv_file.size == 0:
            return 'File is empty'

        # Check MIME type
        mime_type, _ = mimetypes.guess_type(csv_file.name)
        if mime_type and mime_type not in ['text/csv', 'application/csv', 'text/plain']:
            return 'Invalid file type. Please upload a CSV file'

        return None

    def _process_csv_file(self, csv_file, exchange, user):
        """Process the CSV file using the fixed importer"""

        try:
            # Generate unique file path
            file_name = csv_file.name
            unique_id = uuid.uuid4().hex
            file_path = f"csv_imports/{user.id}/{unique_id}_{file_name}"

            # Save file to storage
            saved_path = default_storage.save(file_path, ContentFile(csv_file.read()))

            # Import CSV using the FIXED service
            if exchange == 'binance':
                transactions_imported, errors = CompleteBinanceImportService.import_csv(
                    user, exchange, saved_path, file_name
                )
            else:
                # Use original service for other exchanges
                transactions_imported, errors = CompleteBinanceImportService.import_csv(
                    user, exchange, saved_path, file_name
                )

            # Prepare response
            response_data = {
                'success': True,
                'transactions_imported': transactions_imported,
                'file_name': file_name,
                'exchange': exchange.title(),
                'message': f'Successfully imported {transactions_imported} transactions from {exchange.title()}'
            }

            # Add warnings if any
            if errors:
                response_data['warnings'] = errors[:5]  # Limit to first 5 errors
                response_data['total_errors'] = len(errors)

                if len(errors) > 5:
                    response_data['message'] += f' (with {len(errors)} warnings/errors)'

            # Add processing insights
            if transactions_imported > 0:
                response_data['insights'] = self._generate_processing_insights(
                    user, exchange, transactions_imported
                )

            return response_data

        except ValueError as ve:
            # Validation or processing errors
            return {
                'success': False,
                'error': str(ve),
                'file_name': csv_file.name
            }
        except Exception as e:
            # Unexpected errors
            return {
                'success': False,
                'error': f'Processing failed: {str(e)}',
                'file_name': csv_file.name
            }

    def _generate_processing_insights(self, user, exchange, transactions_imported):
        """Generate insights about the processed transactions"""
        try:
            from .models import CexTransaction
            from django.db.models import Count, Sum

            # Get recent transactions from this import
            recent_transactions = CexTransaction.objects.filter(
                user=user,
                exchange=exchange
            ).values('transaction_type').annotate(
                count=Count('id'),
                total_value=Sum('value_usd')
            ).order_by('-count')

            insights = {
                'total_transactions': transactions_imported,
                'transaction_breakdown': {}
            }

            for tx in recent_transactions:
                tx_type = tx['transaction_type']
                insights['transaction_breakdown'][tx_type] = {
                    'count': tx['count'],
                    'total_value_usd': float(tx['total_value'] or 0)
                }

            # Add FIFO-specific insights
            if exchange == 'binance':
                # Get asset breakdown
                assets = CexTransaction.objects.filter(
                    user=user,
                    exchange=exchange,
                    transaction_type='buy'
                ).values_list('asset_symbol', flat=True).distinct()

                insights['assets_traded'] = list(assets)
                insights['unique_assets'] = len(assets)

                # Calculate total invested vs realized
                total_invested = CexTransaction.objects.filter(
                    user=user,
                    exchange=exchange,
                    transaction_type='buy'
                ).aggregate(total=Sum('value_usd'))['total'] or 0

                total_realized = CexTransaction.objects.filter(
                    user=user,
                    exchange=exchange,
                    transaction_type='sell'
                ).aggregate(total=Sum('realized_profit_loss'))['total'] or 0

                insights['portfolio_summary'] = {
                    'total_invested': float(total_invested),
                    'total_realized_pnl': float(total_realized),
                    'roi_percentage': float((total_realized / total_invested * 100) if total_invested > 0 else 0)
                }

            return insights

        except Exception as e:
            return {'error': f'Could not generate insights: {str(e)}'}


class CsvImportHistoryView(views.APIView):
    """
    API endpoint to get CSV import history
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            imports = CsvImport.objects.filter(
                user=request.user
            ).order_by('-created_at')[:20]  # Last 20 imports

            import_data = []
            for imp in imports:
                import_data.append({
                    'id': imp.id,
                    'exchange': imp.exchange,
                    'file_name': imp.file_name,
                    'status': imp.status,
                    'transactions_imported': imp.transactions_imported,
                    'created_at': imp.created_at.isoformat(),
                    'errors': imp.errors if imp.status == 'failed' else None
                })

            return Response({
                'success': True,
                'imports': import_data
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CombinedTransactionView(views.APIView):
    """
    API endpoint for getting combined transactions (DEX + CEX)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Get combined transactions from DEX wallets and CEX exchanges
        """
        # Get filter parameters
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        asset = request.query_params.get('asset')
        transaction_type = request.query_params.get('type')

        # Base querysets
        wallet_addresses = request.user.wallet_addresses or []
        dex_transactions = Transaction.objects.filter(
            wallet__address__in=wallet_addresses
        )
        cex_transactions = CexTransaction.objects.filter(user=request.user)

        # Apply filters
        if start_date:
            dex_transactions = dex_transactions.filter(timestamp__gte=start_date)
            cex_transactions = cex_transactions.filter(timestamp__gte=start_date)

        if end_date:
            dex_transactions = dex_transactions.filter(timestamp__lte=end_date)
            cex_transactions = cex_transactions.filter(timestamp__lte=end_date)

        if asset:
            dex_transactions = dex_transactions.filter(asset_symbol=asset)
            cex_transactions = cex_transactions.filter(asset_symbol=asset)

        if transaction_type:
            dex_transactions = dex_transactions.filter(transaction_type=transaction_type)
            cex_transactions = cex_transactions.filter(transaction_type=transaction_type)

        # Order by timestamp
        dex_transactions = dex_transactions.order_by('-timestamp')
        cex_transactions = cex_transactions.order_by('-timestamp')

        # Serialize transactions
        combined_data = []

        # Add DEX transactions
        for tx in dex_transactions:  # Limit to 100 for performance
            tx_data = {
                'id': tx.id,
                'transaction_hash': tx.transaction_hash,
                'timestamp': tx.timestamp,
                'transaction_type': tx.transaction_type,
                'asset_symbol': tx.asset_symbol,
                'amount': tx.amount,
                'price_usd': tx.price_usd,
                'value_usd': tx.value_usd,
                'fee_usd': tx.fee_usd,
                'cost_basis_usd': tx.cost_basis_usd,
                'realized_profit_loss': tx.realized_profit_loss,
                'source': 'dex',
                'wallet': tx.wallet.address
            }
            combined_data.append(tx_data)

        # Add CEX transactions
        for tx in cex_transactions:  # Limit to 100 for performance
            tx_data = {
                'id': tx.id,
                'transaction_id': tx.transaction_id,
                'timestamp': tx.timestamp,
                'transaction_type': tx.transaction_type,
                'asset_symbol': tx.asset_symbol,
                'amount': tx.amount,
                'price_usd': tx.price_usd,
                'value_usd': tx.value_usd,
                'fee_usd': tx.fee_usd,
                'cost_basis_usd': tx.cost_basis_usd,
                'realized_profit_loss': tx.realized_profit_loss,
                'source': 'cex',
                'exchange': tx.exchange
            }
            combined_data.append(tx_data)

        # Sort by timestamp (newest first)
        combined_data.sort(key=lambda x: x['timestamp'], reverse=True)

        return Response(combined_data)


class TaxCalculationView(views.APIView):
    """
    API endpoint for calculating taxes across all sources (DEX + CEX)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Calculate taxes for the specified period
        """
        # Get tax year
        tax_year = request.query_params.get('year', datetime.now().year - 1)

        # Calculate start and end dates for the tax year
        start_date = datetime(int(tax_year), 1, 1, tzinfo=timezone.utc)
        end_date = datetime(int(tax_year), 12, 31, 23, 59, 59, tzinfo=timezone.utc)

        # Get all transactions from DEX
        wallet_addresses = request.user.wallet_addresses or []
        dex_transactions = Transaction.objects.filter(
            wallet__in=wallet_addresses,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        )

        # Get all transactions from CEX
        cex_transactions = CexTransaction.objects.filter(
            user=request.user,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        )

        # Calculate DEX summary
        dex_sell_transactions = dex_transactions.filter(
            transaction_type='sell',
            realized_profit_loss__isnull=False
        )

        dex_proceeds = dex_sell_transactions.aggregate(
            total=Sum('value_usd')
        )['total'] or Decimal('0')
        dex_cost_basis = dex_sell_transactions.aggregate(
            total=Sum('cost_basis_usd')
        )['total'] or Decimal('0')
        dex_realized_gain = dex_sell_transactions.aggregate(
            total=Sum('realized_profit_loss')
        )['total'] or Decimal('0')
        dex_fees = dex_transactions.aggregate(
            total=Sum('fee_usd')
        )['total'] or Decimal('0')

        # Calculate CEX summary
        cex_sell_transactions = cex_transactions.filter(
            transaction_type='sell',
            realized_profit_loss__isnull=False
        )

        cex_proceeds = cex_sell_transactions.aggregate(
            total=Sum('value_usd')
        )['total'] or Decimal('0')
        cex_cost_basis = cex_sell_transactions.aggregate(
            total=Sum('cost_basis_usd')
        )['total'] or Decimal('0')
        cex_realized_gain = cex_sell_transactions.aggregate(
            total=Sum('realized_profit_loss')
        )['total'] or Decimal('0')
        cex_fees = cex_transactions.aggregate(
            total=Sum('fee_usd')
        )['total'] or Decimal('0')

        # Get 1 year before end_date for long-term calculation
        long_term_cutoff = datetime(int(tax_year) - 1, 1, 1, tzinfo=timezone.utc)

        # DEX short and long term
        dex_short_term = dex_sell_transactions.filter(
            timestamp__gte=long_term_cutoff
        ).aggregate(total=Sum('realized_profit_loss'))['total'] or Decimal('0')

        dex_long_term = dex_sell_transactions.filter(
            timestamp__lt=long_term_cutoff
        ).aggregate(total=Sum('realized_profit_loss'))['total'] or Decimal('0')

        # CEX short and long term
        cex_short_term = cex_sell_transactions.filter(
            timestamp__gte=long_term_cutoff
        ).aggregate(total=Sum('realized_profit_loss'))['total'] or Decimal('0')

        cex_long_term = cex_sell_transactions.filter(
            timestamp__lt=long_term_cutoff
        ).aggregate(total=Sum('realized_profit_loss'))['total'] or Decimal('0')

        # Count transactions by type
        dex_buys = dex_transactions.filter(transaction_type='buy').count()
        dex_sells = dex_transactions.filter(transaction_type='sell').count()
        dex_swaps = dex_transactions.filter(transaction_type='swap').count()

        cex_buys = cex_transactions.filter(transaction_type='buy').count()
        cex_sells = cex_transactions.filter(transaction_type='sell').count()
        cex_deposits = cex_transactions.filter(transaction_type='deposit').count()
        cex_withdrawals = cex_transactions.filter(transaction_type='withdrawal').count()

        # Prepare tax summary response
        tax_summary = {
            'tax_year': int(tax_year),
            'total_proceeds': dex_proceeds + cex_proceeds,
            'total_cost_basis': dex_cost_basis + cex_cost_basis,
            'total_realized_gain_loss': dex_realized_gain + cex_realized_gain,
            'short_term_gain_loss': dex_short_term + cex_short_term,
            'long_term_gain_loss': dex_long_term + cex_long_term,
            'total_fees': dex_fees + cex_fees,

            # Breakdown by source
            'dex': {
                'proceeds': dex_proceeds,
                'cost_basis': dex_cost_basis,
                'realized_gain_loss': dex_realized_gain,
                'short_term_gain_loss': dex_short_term,
                'long_term_gain_loss': dex_long_term,
                'fees': dex_fees,
                'transaction_counts': {
                    'buy': dex_buys,
                    'sell': dex_sells,
                    'swap': dex_swaps,
                    'total': dex_transactions.count()
                }
            },
            'cex': {
                'proceeds': cex_proceeds,
                'cost_basis': cex_cost_basis,
                'realized_gain_loss': cex_realized_gain,
                'short_term_gain_loss': cex_short_term,
                'long_term_gain_loss': cex_long_term,
                'fees': cex_fees,
                'transaction_counts': {
                    'buy': cex_buys,
                    'sell': cex_sells,
                    'deposit': cex_deposits,
                    'withdrawal': cex_withdrawals,
                    'total': cex_transactions.count()
                }
            },

            # Get top assets by realized gain/loss
            'top_assets': self._get_top_assets_by_pnl(
                request.user, wallet_addresses, start_date, end_date
            )
        }

        return Response(tax_summary)

    def _get_top_assets_by_pnl(self, user, wallet_addresses, start_date, end_date):
        """Get top assets by realized profit/loss across both DEX and CEX"""

        # Get DEX realized PnL by asset
        dex_assets = Transaction.objects.filter(
            wallet__in=wallet_addresses,
            timestamp__gte=start_date,
            timestamp__lte=end_date,
            realized_profit_loss__isnull=False
        ).values('asset_symbol').annotate(
            total_pnl=Sum('realized_profit_loss'),
            transaction_count=Count('id')
        ).order_by('-total_pnl')

        # Get CEX realized PnL by asset
        cex_assets = CexTransaction.objects.filter(
            user=user,
            timestamp__gte=start_date,
            timestamp__lte=end_date,
            realized_profit_loss__isnull=False
        ).values('asset_symbol').annotate(
            total_pnl=Sum('realized_profit_loss'),
            transaction_count=Count('id')
        ).order_by('-total_pnl')

        # Combine the results
        asset_map = {}

        for asset in dex_assets:
            symbol = asset['asset_symbol']
            asset_map[symbol] = {
                'symbol': symbol,
                'realized_pnl': asset['total_pnl'],
                'transaction_count': asset['transaction_count'],
                'source': 'dex'
            }

        for asset in cex_assets:
            symbol = asset['asset_symbol']
            if symbol in asset_map:
                asset_map[symbol]['realized_pnl'] += asset['total_pnl']
                asset_map[symbol]['transaction_count'] += asset['transaction_count']
                asset_map[symbol]['source'] = 'both'
            else:
                asset_map[symbol] = {
                    'symbol': symbol,
                    'realized_pnl': asset['total_pnl'],
                    'transaction_count': asset['transaction_count'],
                    'source': 'cex'
                }

        # Convert to list and sort
        top_assets = list(asset_map.values())
        top_assets.sort(key=lambda x: x['realized_pnl'], reverse=True)

        # Return top 5
        return top_assets[:5]


class WalletHoldingsView(views.APIView):
    """
    API endpoint for getting wallet holdings
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, wallet_id):
        """
        Get holdings for a wallet or all wallets
        """
        wallet_addresses = request.user.wallet_addresses or []

        # If wallet_id is 'all', get holdings for all wallets
        if wallet_id == 'all':
            # Get DEX holdings
            dex_holdings = AssetHolding.objects.filter(
                wallet__address__in=wallet_addresses
            )

            # Get CEX holdings (you'll need to implement a model for this)
            # This is just a placeholder - you'll need to create a model for CEX holdings
            cex_holdings = []

            # Combine holdings
            combined_holdings = []

            # Process DEX holdings
            for holding in dex_holdings:
                combined_holdings.append({
                    'asset_symbol': holding.asset_symbol,
                    'amount': holding.amount,
                    'current_price_usd': holding.current_price_usd,
                    'value_usd': holding.value_usd,
                    'source': 'dex',
                    'wallet': holding.wallet.address
                })

            # Process CEX holdings
            for holding in cex_holdings:
                combined_holdings.append({
                    'asset_symbol': holding.asset_symbol,
                    'amount': holding.amount,
                    'current_price_usd': holding.current_price_usd,
                    'value_usd': holding.value_usd,
                    'source': 'cex',
                    'exchange': holding.exchange
                })

            return Response(combined_holdings)
        else:
            # Get holdings for a specific wallet
            holdings = AssetHolding.objects.filter(wallet=wallet_id)
            serializer = AssetHoldingSerializer(holdings, many=True)
            return Response(serializer.data)


class PortfolioSummaryView(views.APIView):
    """
    Portfolio summary for crypto tax platform - shows CURRENT holdings + tax calculations
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Get current holdings from exchange APIs (NOT from transaction history)
        current_holdings, current_portfolio_value = self._get_current_holdings_from_exchanges(user)

        # Get realized gains from transaction history (for tax purposes)
        realized_gains = self._get_realized_gains_from_transactions(user)

        # Calculate unrealized gains (current value - cost basis from transactions)
        unrealized_gains = self._calculate_unrealized_gains(user, current_holdings)

        # Get monthly P&L from transaction history
        monthly_pnl = self._calculate_monthly_pnl_from_transactions(user)

        return Response({
            'total_portfolio_value': float(current_portfolio_value),
            'total_realized_gains': float(realized_gains),
            'unrealized_gains': float(unrealized_gains),
            'dex_value': 0.0,  # If you have DEX integration
            'cex_value': float(current_portfolio_value),
            'holdings': current_holdings,
            'monthly_pnl': monthly_pnl
        })

    def _get_current_holdings_from_exchanges(self, user):
        """Get CURRENT holdings directly from exchange APIs"""
        all_holdings = []
        total_value = Decimal('0.00')

        # Get all connected exchanges for this user
        exchanges = ExchangeCredential.objects.filter(user=user)

        for exchange_cred in exchanges:
            try:
                # Get exchange service
                service = ExchangeServiceFactory.get_service(exchange_cred.exchange, user)

                if exchange_cred.exchange == 'binance':
                    # Get current Binance balances from API
                    holdings, value = self._get_binance_current_holdings(service, user)
                    all_holdings.extend(holdings)
                    total_value += value

                elif exchange_cred.exchange == 'bybit':
                    holdings, value = self._get_bybit_current_holdings(service, user)
                    all_holdings.extend(holdings)
                    total_value += value

                elif exchange_cred.exchange == 'coinbase':
                    holdings, value = self._get_coinbase_current_holdings(service, user)
                    all_holdings.extend(holdings)
                    total_value += value

                elif exchange_cred.exchange == 'kraken':
                    holdings, value = self._get_kraken_current_holdings(service, user)
                    all_holdings.extend(holdings)
                    total_value += value

                elif exchange_cred.exchange == 'hyperliquid':
                    holdings, value = self._get_hyperliquid_current_holdings(service, user)
                    all_holdings.extend(holdings)
                    total_value += value

            except Exception as e:
                logger.error(f"Error getting holdings from {exchange_cred.exchange}: {str(e)}")
                continue

        return all_holdings, total_value

    def _get_binance_current_holdings(self, service, user):
        """Get current Binance holdings from API (not from transaction history)"""
        holdings = []
        total_value = Decimal('0.00')

        try:
            # Get current Spot account balances
            account_info = service._make_signed_request('/api/v3/account')

            for balance in account_info['balances']:
                free_balance = Decimal(str(balance['free']))
                locked_balance = Decimal(str(balance['locked']))
                total_amount = free_balance + locked_balance

                if total_amount > Decimal('0.00000001'):  # Only non-zero balances
                    asset_symbol = balance['asset']

                    # Get current market price
                    current_price = self._get_current_price_binance(asset_symbol)
                    current_value = total_amount * current_price

                    # Calculate cost basis from transaction history
                    cost_basis = self._calculate_cost_basis_from_transactions(
                        user, 'binance', asset_symbol, total_amount
                    )

                    holdings.append({
                        'exchange': 'binance',
                        'account_type': 'spot',
                        'asset_symbol': asset_symbol,
                        'amount': float(total_amount),
                        'current_price': float(current_price),
                        'value_usd': float(current_value),
                        'cost_basis': float(cost_basis),
                        'unrealized_pnl': float(current_value - cost_basis)
                    })

                    total_value += current_value

            # Optionally, also get Futures and Margin balances if needed
            # futures_holdings = self._get_binance_futures_balances(service, user)
            # margin_holdings = self._get_binance_margin_balances(service, user)

        except Exception as e:
            logger.error(f"Error getting Binance current holdings: {str(e)}")

        return holdings, total_value

    def _get_current_price_binance(self, asset_symbol):
        """Get current price from Binance API"""
        try:
            if asset_symbol in ['USDT', 'USDC', 'BUSD', 'DAI']:
                return Decimal('1.0')

            # Try USDT pair first
            symbol = f"{asset_symbol}USDT"
            response = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")

            if response.status_code == 200:
                price_data = response.json()
                return Decimal(str(price_data['price']))

            # Fallback to other pairs if USDT pair doesn't exist
            for quote in ['BUSD', 'BTC', 'ETH']:
                symbol = f"{asset_symbol}{quote}"
                response = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
                if response.status_code == 200:
                    price_data = response.json()
                    quote_price = self._get_current_price_binance(quote) if quote != 'USDT' else Decimal('1.0')
                    return Decimal(str(price_data['price'])) * quote_price

            logger.warning(f"Could not get current price for {asset_symbol}")
            return Decimal('0.0')

        except Exception as e:
            logger.error(f"Error getting current price for {asset_symbol}: {str(e)}")
            return Decimal('0.0')

    def _calculate_cost_basis_from_transactions(self, user, exchange, asset_symbol, current_amount):
        """Calculate cost basis using FIFO from transaction history"""
        try:
            # Get buy transactions for this asset, sorted by date (FIFO)
            buy_transactions = CexTransaction.objects.filter(
                user=user,
                exchange=exchange,
                asset_symbol=asset_symbol,
                transaction_type__in=['buy', 'deposit']
            ).order_by('timestamp')

            if not buy_transactions.exists():
                return Decimal('0.00')

            remaining_amount = Decimal(str(current_amount))
            total_cost_basis = Decimal('0.00')

            for tx in buy_transactions:
                if remaining_amount <= Decimal('0.00000001'):
                    break

                amount_to_use = min(remaining_amount, tx.amount)
                cost_basis_for_amount = amount_to_use * tx.price_usd
                total_cost_basis += cost_basis_for_amount
                remaining_amount -= amount_to_use

            return total_cost_basis

        except Exception as e:
            logger.error(f"Error calculating cost basis for {asset_symbol}: {str(e)}")
            return Decimal('0.00')

    def _get_realized_gains_from_transactions(self, user):
        """Get total realized gains from all exchanges"""
        try:
            total_realized = CexTransaction.objects.filter(
                user=user,
                realized_profit_loss__isnull=False
            ).aggregate(
                total=Sum('realized_profit_loss', default=0)
            )['total'] or Decimal('0.00')

            return total_realized
        except Exception as e:
            logger.error(f"Error calculating realized gains: {str(e)}")
            return Decimal('0.00')

    def _calculate_unrealized_gains(self, user, current_holdings):
        """Calculate unrealized gains from current holdings"""
        try:
            total_unrealized = Decimal('0.00')

            for holding in current_holdings:
                current_value = Decimal(str(holding['value_usd']))
                cost_basis = Decimal(str(holding['cost_basis']))
                unrealized_gain = current_value - cost_basis
                total_unrealized += unrealized_gain

            return total_unrealized
        except Exception as e:
            logger.error(f"Error calculating unrealized gains: {str(e)}")
            return Decimal('0.00')

    def _calculate_monthly_pnl_from_transactions(self, user):
        """Calculate monthly P&L from transaction history"""
        try:
            # Get all realized transactions
            realized_txs = CexTransaction.objects.filter(
                user=user,
                realized_profit_loss__isnull=False
            ).order_by('timestamp')

            if not realized_txs.exists():
                return []

            # Group by month and calculate P&L
            monthly_data = {}
            for tx in realized_txs:
                month_key = tx.timestamp.strftime('%Y-%m')
                month_name = tx.timestamp.strftime('%b')
                year = tx.timestamp.year

                if month_key not in monthly_data:
                    monthly_data[month_key] = {
                        'month': month_name,
                        'year': year,
                        'profit': 0.0
                    }

                monthly_data[month_key]['profit'] += float(tx.realized_profit_loss)

            return list(monthly_data.values())

        except Exception as e:
            logger.error(f"Error calculating monthly P&L: {str(e)}")
            return []

    def _get_bybit_current_holdings(self, service, user):
        """Get current Bybit holdings from API (not from transaction history)"""
        holdings = []
        total_value = Decimal('0.00')

        try:
            # Get current unified account balances from Bybit
            account_balances = service._make_signed_request('/v5/account/wallet-balance', {
                'accountType': 'UNIFIED'
            })

            # Also get spot account balances
            try:
                spot_balances = service._make_signed_request('/v5/account/wallet-balance', {
                    'accountType': 'SPOT'
                })
            except:
                spot_balances = {'list': []}

            # Process unified account balances
            if 'list' in account_balances and account_balances['list']:
                for account in account_balances['list']:
                    if 'coin' in account:
                        for coin_balance in account['coin']:
                            total_amount = Decimal(str(coin_balance.get('walletBalance', '0')))
                            
                            if total_amount > Decimal('0.00000001'):  # Only non-zero balances
                                asset_symbol = coin_balance['coin']
                                
                                # Get current market price
                                current_price = self._get_current_price_bybit(asset_symbol)
                                current_value = total_amount * current_price
                                
                                # Calculate cost basis from transaction history
                                cost_basis = self._calculate_cost_basis_from_transactions(
                                    user, 'bybit', asset_symbol, total_amount
                                )
                                
                                holdings.append({
                                    'exchange': 'bybit',
                                    'account_type': 'unified',
                                    'asset_symbol': asset_symbol,
                                    'amount': float(total_amount),
                                    'current_price': float(current_price),
                                    'value_usd': float(current_value),
                                    'cost_basis': float(cost_basis),
                                    'unrealized_pnl': float(current_value - cost_basis)
                                })
                                
                                total_value += current_value

            # Process spot account balances if they exist and are different
            if 'list' in spot_balances and spot_balances['list']:
                for account in spot_balances['list']:
                    if 'coin' in account:
                        for coin_balance in account['coin']:
                            total_amount = Decimal(str(coin_balance.get('walletBalance', '0')))
                            
                            if total_amount > Decimal('0.00000001'):
                                asset_symbol = coin_balance['coin']
                                
                                # Check if we already have this asset from unified account
                                existing_holding = next(
                                    (h for h in holdings if h['asset_symbol'] == asset_symbol and h['account_type'] == 'unified'), 
                                    None
                                )
                                
                                if not existing_holding:
                                    # Get current market price
                                    current_price = self._get_current_price_bybit(asset_symbol)
                                    current_value = total_amount * current_price
                                    
                                    # Calculate cost basis from transaction history
                                    cost_basis = self._calculate_cost_basis_from_transactions(
                                        user, 'bybit', asset_symbol, total_amount
                                    )
                                    
                                    holdings.append({
                                        'exchange': 'bybit',
                                        'account_type': 'spot',
                                        'asset_symbol': asset_symbol,
                                        'amount': float(total_amount),
                                        'current_price': float(current_price),
                                        'value_usd': float(current_value),
                                        'cost_basis': float(cost_basis),
                                        'unrealized_pnl': float(current_value - cost_basis)
                                    })
                                    
                                    total_value += current_value

        except Exception as e:
            logger.error(f"Error getting Bybit current holdings: {str(e)}")

        return holdings, total_value

    def _get_current_price_bybit(self, asset_symbol):
        """Get current price from Bybit API"""
        try:
            if asset_symbol.upper() in ['USDT', 'USDC', 'BUSD', 'DAI']:
                return Decimal('1.0')

            # Try USDT pair first
            symbol = f"{asset_symbol}USDT"
            response = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}")

            if response.status_code == 200:
                data = response.json()
                if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                    ticker = data['result']['list'][0]
                    price = ticker.get('lastPrice')
                    if price:
                        return Decimal(str(price))

            # Fallback to other pairs if USDT pair doesn't exist
            for quote in ['BUSD', 'BTC', 'ETH']:
                symbol = f"{asset_symbol}{quote}"
                response = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}")
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                        ticker = data['result']['list'][0]
                        price = ticker.get('lastPrice')
                        if price:
                            quote_price = self._get_current_price_bybit(quote) if quote != 'USDT' else Decimal('1.0')
                            return Decimal(str(price)) * quote_price

            logger.warning(f"Could not get current price for {asset_symbol} from Bybit")
            return Decimal('0.0')

        except Exception as e:
            logger.error(f"Error getting current price for {asset_symbol}: {str(e)}")
            return Decimal('0.0')

    def _get_coinbase_current_holdings(self, service, user):
        """Get current Coinbase holdings from API (not from transaction history)"""
        holdings = []
        total_value = Decimal('0.00')

        try:
            # Get current account balances from Coinbase
            balances = service.get_current_account_balances()

            for asset_symbol, balance_info in balances.items():
                total_amount = Decimal(str(balance_info['total']))

                if total_amount > Decimal('0.00000001'):  # Only non-zero balances
                    # Get current market price
                    current_price = self._get_current_price_coinbase(asset_symbol)
                    current_value = total_amount * current_price

                    # Calculate cost basis from transaction history
                    cost_basis = self._calculate_cost_basis_from_transactions(
                        user, 'coinbase', asset_symbol, total_amount
                    )

                    holdings.append({
                        'exchange': 'coinbase',
                        'account_type': 'spot',
                        'asset_symbol': asset_symbol,
                        'amount': float(total_amount),
                        'current_price': float(current_price),
                        'value_usd': float(current_value),
                        'cost_basis': float(cost_basis),
                        'unrealized_pnl': float(current_value - cost_basis)
                    })

                    total_value += current_value

        except Exception as e:
            logger.error(f"Error getting Coinbase current holdings: {str(e)}")

        return holdings, total_value

    def _get_current_price_coinbase(self, asset_symbol):
        """Get current price from Coinbase API"""
        try:
            if asset_symbol.upper() in ['USD', 'USDC', 'USDT', 'DAI', 'BUSD']:
                return Decimal('1.0')

            # Use Coinbase public API for current prices
            response = requests.get(f"https://api.coinbase.com/v2/exchange-rates?currency={asset_symbol}")

            if response.status_code == 200:
                data = response.json()
                rates = data.get('data', {}).get('rates', {})
                usd_rate = rates.get('USD')

                if usd_rate:
                    return Decimal(str(usd_rate))

            logger.warning(f"Could not get current price for {asset_symbol} from Coinbase")
            return Decimal('0.0')

        except Exception as e:
            logger.error(f"Error getting current price for {asset_symbol}: {str(e)}")
            return Decimal('0.0')

    def _get_kraken_current_holdings(self, service, user):
        """Get current Kraken holdings from API (not from transaction history)"""
        holdings = []
        total_value = Decimal('0.00')

        try:
            # Get current account balances from Kraken
            balances = service.get_current_account_balances()

            for asset_symbol, balance_info in balances.items():
                total_amount = Decimal(str(balance_info['amount']))

                if total_amount > Decimal('0.00000001'):  # Only non-zero balances
                    # Get current market price
                    current_price = self._get_current_price_kraken(asset_symbol)
                    current_value = total_amount * current_price

                    # Calculate cost basis from transaction history
                    cost_basis = self._calculate_cost_basis_from_transactions(
                        user, 'kraken', asset_symbol, total_amount
                    )

                    holdings.append({
                        'exchange': 'kraken',
                        'account_type': 'spot',
                        'asset_symbol': asset_symbol,
                        'amount': float(total_amount),
                        'current_price': float(current_price),
                        'value_usd': float(current_value),
                        'cost_basis': float(cost_basis),
                        'unrealized_pnl': float(current_value - cost_basis)
                    })

                    total_value += current_value

        except Exception as e:
            logger.error(f"Error getting Kraken current holdings: {str(e)}")

        return holdings, total_value

    def _get_current_price_kraken(self, asset_symbol):
        """Get current price from Kraken API"""
        try:
            if asset_symbol.upper() in ['USD', 'USDT', 'USDC', 'DAI', 'BUSD']:
                return Decimal('1.0')

            # Use Kraken public API for current prices
            response = requests.get(f"https://api.kraken.com/0/public/Ticker?pair={asset_symbol.upper()}USD")

            if response.status_code == 200:
                data = response.json()
                if data.get('error') == []:
                    ticker = data['result']['XXRPUSD']
                    price = ticker['c'][0]
                    if price:
                        return Decimal(str(price))

            logger.warning(f"Could not get current price for {asset_symbol} from Kraken")
            return Decimal('0.0')

        except Exception as e:
            logger.error(f"Error getting current price for {asset_symbol}: {str(e)}")
            return Decimal('0.0')

    def _get_hyperliquid_current_holdings(self, service, user):
        """Get current Hyperliquid holdings from API (not from transaction history)"""
        holdings = []
        total_value = Decimal('0.00')

        try:
            # Get current account balances from Hyperliquid
            balances = service.get_current_account_balances()

            for asset_symbol, balance_info in balances.items():
                total_amount = Decimal(str(balance_info['amount']))

                if total_amount > Decimal('0.00000001'):  # Only non-zero balances
                    # Get current market price
                    current_price = self._get_current_price_hyperliquid(asset_symbol)
                    current_value = total_amount * current_price

                    # Calculate cost basis from transaction history
                    cost_basis = self._calculate_cost_basis_from_transactions(
                        user, 'hyperliquid', asset_symbol, total_amount
                    )

                    holdings.append({
                        'exchange': 'hyperliquid',
                        'account_type': 'spot',
                        'asset_symbol': asset_symbol,
                        'amount': float(total_amount),
                        'current_price': float(current_price),
                        'value_usd': float(current_value),
                        'cost_basis': float(cost_basis),
                        'unrealized_pnl': float(current_value - cost_basis)
                    })

                    total_value += current_value

        except Exception as e:
            logger.error(f"Error getting Hyperliquid current holdings: {str(e)}")

        return holdings, total_value

    def _get_current_price_hyperliquid(self, asset_symbol):
        """Get current price from Hyperliquid API"""
        try:
            if asset_symbol.upper() in ['USDT', 'USDC', 'BUSD', 'DAI']:
                return Decimal('1.0')

            # Use Hyperliquid public API for current prices
            response = requests.get(f"https://api.hyperliquid.io/v1/tickers?symbol={asset_symbol.upper()}USDT")

            if response.status_code == 200:
                data = response.json()
                if data.get('retCode') == 0 and data.get('result', {}).get('list'):
                    ticker = data['result']['list'][0]
                    price = ticker.get('lastPrice')
                    if price:
                        return Decimal(str(price))

            logger.warning(f"Could not get current price for {asset_symbol} from Hyperliquid")
            return Decimal('0.0')

        except Exception as e:
            logger.error(f"Error getting current price for {asset_symbol}: {str(e)}")
            return Decimal('0.0')


class UserWalletAddressesView(APIView):
    """
    API endpoint for managing user wallet addresses
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get all wallet addresses for the current user"""
        serializer = UserWalletAddressesSerializer(request.user)
        return Response(serializer.data)

    def post(self, request):
        """Add a new wallet address to the user's list"""
        serializer = WalletAddressSerializer(data=request.data)

        if serializer.is_valid():
            address = serializer.validated_data['address']
            chain = serializer.validated_data['chain']

            # Normalize address format
            if chain in ['ethereum', 'polygon', 'arbitrum', 'bsc']:
                address = address.lower()

            # Check if wallet already exists in our database
            wallet, created = Wallet.objects.get_or_create(
                address=address,
                chain=chain
            )

            # Add to user's wallet_addresses field if not already there
            user = request.user
            wallet_addresses = user.wallet_addresses or []

            if address not in wallet_addresses:
                wallet_addresses.append(address)
                user.wallet_addresses = wallet_addresses
                user.save()

                return Response({
                    'success': True,
                    'message': 'Wallet address added successfully',
                    'wallet': {
                        'address': address,
                        'chain': chain
                    },
                    'wallet_addresses': wallet_addresses
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    'success': False,
                    'message': 'Wallet address already exists',
                    'wallet_addresses': wallet_addresses
                }, status=status.HTTP_400_BAD_REQUEST)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        """Remove a wallet address from the user's list"""
        address = request.data.get('address')

        if not address:
            return Response({
                'success': False,
                'message': 'Address is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Remove from user's wallet_addresses
        user = request.user
        wallet_addresses = user.wallet_addresses or []

        if address in wallet_addresses:
            wallet_addresses.remove(address)
            user.wallet_addresses = wallet_addresses
            user.save()

            return Response({
                'success': True,
                'message': 'Wallet address removed successfully',
                'wallet_addresses': wallet_addresses
            })
        else:
            return Response({
                'success': False,
                'message': 'Wallet address not found',
                'wallet_addresses': wallet_addresses
            }, status=status.HTTP_404_NOT_FOUND)


class TaxReportViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def form_8949(self, request):
        """Generate IRS Form 8949 with enhanced fee handling"""
        user = request.user
        tax_year = request.data.get('tax_year', timezone.now().year - 1)

        try:
            # Use enhanced tax calculation service
            from .services.tax_calculation_service import TaxCalculationService
            form_data = TaxCalculationService.generate_form_8949(user, tax_year)

            # Add fee warnings and recommendations
            form_data['fee_warnings'] = self._generate_fee_warnings(form_data)

            return Response(form_data)

        except Exception as e:
            logger.error(f"Error generating Form 8949: {str(e)}")
            return Response(
                {"error": "Failed to generate Form 8949", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _generate_fee_warnings(self, form_data):
        """Generate warnings about fee handling for user education"""
        warnings = []

        fee_summary = form_data.get('fee_summary', {})
        total_fees = fee_summary.get('total_deductible_fees', 0)

        if total_fees > 1000:
            warnings.append({
                'type': 'significant_fees',
                'message': f"You paid ${total_fees:,.2f} in deductible fees. These have been properly included in your cost basis calculations to minimize your tax liability.",
                'severity': 'info'
            })

        if fee_summary.get('fee_count', 0) == 0:
            warnings.append({
                'type': 'missing_fees',
                'message': "No transaction fees were detected. Ensure all exchange fees, gas fees, and network fees are properly imported.",
                'severity': 'warning'
            })

        return warnings

    @action(detail=False, methods=['post'])
    def form_8949_pdf(self, request):
        """Generate and download PDF version of Form 8949"""
        user = request.user
        tax_year = request.data.get('tax_year', timezone.now().year - 1)

        try:
            # Generate PDF
            pdf_buffer = TaxCalculationService.generate_form_8949_pdf(user, tax_year)

            # Create HTTP response with proper headers
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="form_8949_{tax_year}.pdf"'
            response['Content-Length'] = len(pdf_buffer.getvalue())

            # Important: Add CORS headers if needed
            response['Access-Control-Allow-Origin'] = '*'
            response['Access-Control-Expose-Headers'] = 'Content-Disposition'

            return response

        except Exception as e:
            logger.error(f"Error generating Form 8949 PDF: {str(e)}")
            return Response(
                {"error": "Failed to generate PDF. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PortfolioAnalyticsView(views.APIView):
    """Fixed Portfolio Analytics with correct calculations"""

    def get(self, request):
        try:
            user = request.user
            timeframe = request.query_params.get('timeframe', '1Y')

            # Calculate date range
            end_date = timezone.now()
            if timeframe == '1M':
                start_date = end_date - datetime.timedelta(days=30)
            elif timeframe == '3M':
                start_date = end_date - datetime.timedelta(days=90)
            elif timeframe == '6M':
                start_date = end_date - datetime.timedelta(days=180)
            elif timeframe == '1Y':
                start_date = end_date - datetime.timedelta(days=365)
            else:
                start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)

            # Get portfolio data
            portfolio_data = self._get_correct_portfolio_summary(user, start_date, end_date)
            transaction_analytics = self._get_correct_transaction_analytics(user, start_date, end_date)
            performance_metrics = self._get_correct_performance_metrics(user, start_date, end_date)

            return Response({
                'success': True,
                'portfolio': portfolio_data,
                'transactions': transaction_analytics,
                'performance': performance_metrics,
                'timeframe': timeframe
            })

        except Exception as e:
            logger.error(f"Portfolio analytics error: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _get_correct_portfolio_summary(self, user, start_date, end_date):
        """Get portfolio summary with OPTIMIZED calculations"""
        import asyncio
        import concurrent.futures
        from django.db.models import Q, Prefetch
        
        start_time = time.time()
        logger.info(f"Starting portfolio summary calculation for user {user.id}")
        
        # Get all CEX transactions for calculations with optimized query
        transactions = CexTransaction.objects.filter(
            user=user,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).select_related().order_by('timestamp')
        
        # Calculate current holdings efficiently
        current_holdings = self._calculate_current_holdings_optimized(user)
        logger.info(f"Holdings calculation took {time.time() - start_time:.2f}s")
        
        # Get all unique assets for bulk operations
        unique_assets = list(transactions.values_list('asset_symbol', flat=True).distinct())
        
        # Parallel price fetching for all assets
        price_start = time.time()
        asset_prices = self._fetch_prices_parallel(unique_assets)
        logger.info(f"Price fetching took {time.time() - price_start:.2f}s")
        
        # Calculate current portfolio value efficiently
        current_portfolio_value = sum(
            current_holdings.get(asset, 0) * float(asset_prices.get(asset, 0))
            for asset in current_holdings.keys()
        )
        
        # Bulk aggregate calculations for all metrics at once
        bulk_start = time.time()
        asset_breakdown = self._calculate_asset_breakdown_bulk(transactions, current_holdings, asset_prices)
        summary_metrics = self._calculate_summary_metrics_bulk(transactions)
        logger.info(f"Bulk calculations took {time.time() - bulk_start:.2f}s")
        
        # Calculate derived metrics
        roi_percentage = (
            float(summary_metrics['total_realized_gains']) / float(summary_metrics['total_invested']) * 100
        ) if summary_metrics['total_invested'] > 0 else 0
        
        total_cost_basis = sum([asset['total_invested'] for asset in asset_breakdown])
        unrealized_gains = float(current_portfolio_value) - total_cost_basis
        
        total_time = time.time() - start_time
        logger.info(f"Total portfolio summary calculation took {total_time:.2f}s")
        
        return {
            'total_invested': float(summary_metrics['total_invested']),
            'total_realized_gains': float(summary_metrics['total_realized_gains']),
            'total_fees': float(summary_metrics['total_fees']),
            'total_volume': float(summary_metrics['total_volume']),
            'roi_percentage': roi_percentage,
            'current_portfolio_value': float(current_portfolio_value),
            'unrealized_gains': unrealized_gains,
            'asset_breakdown': asset_breakdown,
            'calculation_time': f"{total_time:.2f}s"  # For debugging
        }
    
    def _calculate_current_holdings_optimized(self, user):
        """OPTIMIZED: Calculate current holdings with single query"""
        # Single query to get all transactions
        all_transactions = CexTransaction.objects.filter(user=user).values(
            'asset_symbol', 'amount', 'transaction_type'
        ).order_by('timestamp')
        
        holdings = {}
        for tx in all_transactions:
            asset = tx['asset_symbol']
            amount = float(tx['amount'] or 0)
            
            if asset not in holdings:
                holdings[asset] = 0
            
            if tx['transaction_type'] == 'buy':
                holdings[asset] += amount
            elif tx['transaction_type'] == 'sell':
                holdings[asset] -= amount
            
            holdings[asset] = max(0, holdings[asset])
        
        return {asset: amount for asset, amount in holdings.items() if amount > 0.00000001}

    def _calculate_current_holdings_from_transactions(self, user):
        """Alias for _calculate_current_holdings_optimized for backward compatibility"""
        return self._calculate_current_holdings_optimized(user)

    def _fetch_prices_parallel(self, asset_list):
        """OPTIMIZED: Fetch all prices in parallel with caching"""
        from crypto_tax_api.utils.blockchain_apis import fetch_price_data
        import concurrent.futures
        
        if not asset_list:
            return {}
        
        # Check cache first
        cached_prices = {}
        assets_to_fetch = []
        
        for asset in asset_list:
            cache_key = f"price_{asset}_60s"  # 60 second cache
            cached_price = cache.get(cache_key)
            if cached_price:
                cached_prices[asset] = float(cached_price)
            else:
                assets_to_fetch.append(asset)
        
        logger.info(f"Using cached prices for {len(cached_prices)} assets, fetching {len(assets_to_fetch)} fresh")
        
        def fetch_single_price(asset):
            try:
                price = fetch_price_data(asset)
                # Cache for 60 seconds
                cache.set(f"price_{asset}_60s", price, 60)
                return asset, float(price)
            except Exception as e:
                logger.error(f"Error fetching price for {asset}: {e}")
                return asset, 1.0  # Fallback
        
        # Fetch only non-cached prices in parallel
        fresh_prices = {}
        if assets_to_fetch:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                future_to_asset = {
                    executor.submit(fetch_single_price, asset): asset 
                    for asset in assets_to_fetch
                }
                
                for future in concurrent.futures.as_completed(future_to_asset, timeout=30):
                    try:
                        asset, price = future.result()
                        fresh_prices[asset] = price
                    except Exception as e:
                        asset = future_to_asset[future]
                        logger.error(f"Price fetch failed for {asset}: {e}")
                        fresh_prices[asset] = 1.0
        
        # Combine cached and fresh prices
        return {**cached_prices, **fresh_prices}
    
    def _calculate_asset_breakdown_bulk(self, transactions, current_holdings, asset_prices):
        """OPTIMIZED: Calculate asset breakdown with bulk aggregations"""
        from django.db.models import Sum, Count, Q
        
        # Single bulk aggregation query for all assets
        asset_aggregations = transactions.values('asset_symbol').annotate(
            total_bought=Sum('amount', filter=Q(transaction_type='buy')),
            total_sold=Sum('amount', filter=Q(transaction_type='sell')),
            total_invested=Sum('value_usd', filter=Q(transaction_type='buy')),
            realized_pnl=Sum('realized_profit_loss', filter=Q(transaction_type='sell')),
            trade_count=Count('id')
        )
        
        asset_breakdown = []
        for asset_data in asset_aggregations:
            asset = asset_data['asset_symbol']
            current_amount = current_holdings.get(asset, 0)
            current_price = asset_prices.get(asset, 0)
            current_value = float(current_amount) * current_price
            
            asset_breakdown.append({
                'asset_symbol': asset,
                'total_bought': float(asset_data['total_bought'] or 0),
                'total_sold': float(asset_data['total_sold'] or 0),
                'current_holdings': float(current_amount),
                'current_price': current_price,
                'current_value': current_value,
                'total_invested': float(asset_data['total_invested'] or 0),
                'realized_pnl': float(asset_data['realized_pnl'] or 0),
                'trade_count': asset_data['trade_count']
            })
        
        # Sort by current value descending
        asset_breakdown.sort(key=lambda x: x['current_value'], reverse=True)
        return asset_breakdown
    
    def _calculate_summary_metrics_bulk(self, transactions):
        """OPTIMIZED: Calculate all summary metrics in single query"""
        from django.db.models import Sum, Q
        
        metrics = transactions.aggregate(
            total_invested=Sum('value_usd', filter=Q(transaction_type='buy')),
            total_realized_gains=Sum('realized_profit_loss', filter=Q(
                transaction_type='sell', 
                realized_profit_loss__isnull=False
            )),
            total_fees=Sum('fee_usd'),
            total_volume=Sum('value_usd')
        )
        
        return {
            'total_invested': metrics['total_invested'] or 0,
            'total_realized_gains': metrics['total_realized_gains'] or 0,
            'total_fees': metrics['total_fees'] or 0,
            'total_volume': metrics['total_volume'] or 0
        }

    def _get_correct_transaction_analytics(self, user, start_date, end_date):
        """Get CORRECT transaction analytics"""

        from .models import CexTransaction

        sell_transactions = CexTransaction.objects.filter(
            user=user,
            transaction_type='sell',
            timestamp__gte=start_date,
            timestamp__lte=end_date,
            realized_profit_loss__isnull=False
        )

        if not sell_transactions.exists():
            return {
                'total_transactions': 0,
                'win_rate': 0,
                'profitable_trades': 0,
                'losing_trades': 0,
                'average_trade_size': 0,
                'largest_gain': 0,
                'largest_loss': 0,
            }

        # Count profitable vs losing trades
        profitable_trades = sell_transactions.filter(realized_profit_loss__gt=0)
        losing_trades = sell_transactions.filter(realized_profit_loss__lt=0)
        breakeven_trades = sell_transactions.filter(realized_profit_loss=0)

        total_sell_count = sell_transactions.count()
        win_rate = (profitable_trades.count() / total_sell_count * 100) if total_sell_count > 0 else 0

        # Get metrics
        avg_trade_size = sell_transactions.aggregate(avg=Avg('value_usd'))['avg'] or 0
        largest_gain = profitable_trades.aggregate(max=Max('realized_profit_loss'))['max'] or 0
        largest_loss = losing_trades.aggregate(min=Min('realized_profit_loss'))['min'] or 0

        return {
            'total_transactions': total_sell_count,
            'win_rate': round(win_rate, 2),
            'profitable_trades': profitable_trades.count(),
            'losing_trades': losing_trades.count(),
            'breakeven_trades': breakeven_trades.count(),
            'average_trade_size': float(avg_trade_size),
            'largest_gain': float(largest_gain),
            'largest_loss': float(largest_loss),
        }

    def _get_correct_performance_metrics(self, user, start_date, end_date):
        """Get CORRECT performance metrics"""

        from .models import CexTransaction

        sell_transactions = CexTransaction.objects.filter(
            user=user,
            transaction_type='sell',
            realized_profit_loss__isnull=False,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).order_by('timestamp')

        if not sell_transactions.exists():
            return {
                'max_drawdown': 0,
                'profit_factor': 0,
                'total_profits': 0,
                'total_losses': 0
            }

        # Separate profits and losses
        profitable_transactions = sell_transactions.filter(realized_profit_loss__gt=0)
        losing_transactions = sell_transactions.filter(realized_profit_loss__lt=0)

        total_profits = profitable_transactions.aggregate(
            sum=Sum('realized_profit_loss')
        )['sum'] or Decimal('0')

        total_losses = abs(losing_transactions.aggregate(
            sum=Sum('realized_profit_loss')
        )['sum'] or Decimal('0'))

        # Calculate profit factor
        profit_factor = float(total_profits) / float(total_losses) if total_losses > 0 else float('inf')

        # Calculate max drawdown
        cumulative_pnl = []
        running_total = Decimal('0')

        for tx in sell_transactions:
            running_total += (tx.realized_profit_loss or Decimal('0'))
            cumulative_pnl.append(float(running_total))

        # Find max drawdown
        peak = 0
        max_drawdown = 0
        for pnl in cumulative_pnl:
            if pnl > peak:
                peak = pnl
            drawdown = peak - pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return {
            'max_drawdown': round(max_drawdown, 2),
            'profit_factor': round(profit_factor, 2) if profit_factor != float('inf') else 999.99,
            'total_profits': float(total_profits),
            'total_losses': float(total_losses),
            'cumulative_pnl': cumulative_pnl[-20:] if cumulative_pnl else []  # Last 20 data points
        }


class TransactionInsightsView(views.APIView):
    """
    Endpoint for detailed transaction insights and patterns
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            user = request.user
            asset_filter = request.query_params.get('asset', 'all')
            timeframe = request.query_params.get('timeframe', '3M')

            insights = self._calculate_trading_insights(user, asset_filter, timeframe)

            return Response({
                'success': True,
                'insights': insights,
                'timeframe': timeframe,
                'asset_filter': asset_filter
            })

        except Exception as e:
            logger.error(f"Transaction insights error for user {user.id}: {str(e)}")
            return Response({
                'success': False,
                'error': f'Failed to calculate insights: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _calculate_trading_insights(self, user, asset_filter, timeframe):
        """Calculate detailed trading insights"""

        # Build base query
        transactions = CexTransaction.objects.filter(user=user)

        # Apply asset filter
        if asset_filter != 'all':
            if asset_filter == 'altcoins':
                transactions = transactions.exclude(asset_symbol__in=['BTC', 'ETH'])
            else:
                transactions = transactions.filter(asset_symbol=asset_filter)

        # Apply timeframe filter
        end_date = timezone.now()
        if timeframe == '1M':
            start_date = end_date - datetime.timedelta(days=30)
        elif timeframe == '3M':
            start_date = end_date - datetime.timedelta(days=90)
        elif timeframe == '6M':
            start_date = end_date - datetime.timedelta(days=180)
        elif timeframe == '1Y':
            start_date = end_date - datetime.timedelta(days=365)
        else:
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)

        transactions = transactions.filter(timestamp__gte=start_date)

        # Trading patterns
        patterns = self._analyze_trading_patterns(transactions)

        # Risk metrics
        risk_metrics = self._calculate_risk_metrics(transactions)

        # Efficiency metrics
        efficiency = self._calculate_efficiency_metrics(transactions)

        # Calculate current portfolio value
        current_holdings = self._calculate_current_holdings_optimized(user)
        current_portfolio_value = self._calculate_current_portfolio_value(current_holdings)
        
        # Asset allocation
        asset_allocation = self._calculate_asset_allocation(current_holdings, current_portfolio_value)

        return {
            'patterns': patterns,
            'risk_metrics': risk_metrics,
            'efficiency': efficiency,
            'current_portfolio': {
                'total_value': current_portfolio_value,
                'holdings_count': len(current_holdings),
                'asset_allocation': asset_allocation,
                'holdings': current_holdings
            },
            'timeframe': timeframe,
            'asset_filter': asset_filter
        }

    def _analyze_trading_patterns(self, transactions):
        """Analyze user trading patterns"""

        try:
            # Time-based patterns - using SQLite compatible syntax
            hourly_activity = transactions.extra(
                select={'hour': "strftime('%%H', timestamp)"}
            ).values('hour').annotate(count=Count('id')).order_by('hour')

            # Day of week patterns - SQLite compatible (0=Sunday, 1=Monday, etc.)
            daily_activity = transactions.extra(
                select={'day': "strftime('%%w', timestamp)"}
            ).values('day').annotate(count=Count('id')).order_by('day')

            # Hold time analysis (for pairs of buy/sell)
            hold_times = self._calculate_hold_times(transactions)

            return {
                'hourly_activity': list(hourly_activity),
                'daily_activity': list(daily_activity),
                'average_hold_time_days': hold_times['average'],
                'median_hold_time_days': hold_times['median']
            }
        except Exception as e:
            # Fallback if SQL queries fail
            logger.error(f"Error in trading patterns analysis: {e}")
            return {
                'hourly_activity': [],
                'daily_activity': [],
                'average_hold_time_days': 0,
                'median_hold_time_days': 0
            }

    def _calculate_hold_times(self, transactions):
        """Calculate hold times for buy/sell pairs"""
        hold_times = []

        # Group by asset
        assets = transactions.values('asset_symbol').distinct()

        for asset_data in assets:
            asset = asset_data['asset_symbol']
            asset_txs = transactions.filter(asset_symbol=asset).order_by('timestamp')

            buys = asset_txs.filter(transaction_type='buy')
            sells = asset_txs.filter(transaction_type='sell')

            # Simple FIFO matching for hold time calculation
            for sell in sells:
                for buy in buys:
                    if buy.timestamp < sell.timestamp:
                        hold_time = (sell.timestamp - buy.timestamp).days
                        hold_times.append(hold_time)
                        break

        if hold_times:
            return {
                'average': sum(hold_times) / len(hold_times),
                'median': sorted(hold_times)[len(hold_times) // 2]
            }

        return {'average': 0, 'median': 0}

    def _calculate_risk_metrics(self, transactions):
        """Calculate risk-related metrics"""
        sell_transactions = transactions.filter(
            transaction_type='sell',
            realized_profit_loss__isnull=False
        )

        if not sell_transactions.exists():
            return {
                'volatility': 0,
                'var_95': 0,
                'maximum_single_loss': 0,
                'consecutive_losses': 0
            }

        # Calculate return volatility
        returns = [float(tx.realized_profit_loss) for tx in sell_transactions]

        if len(returns) > 1:
            import statistics
            volatility = statistics.stdev(returns)
            var_95 = sorted(returns)[int(len(returns) * 0.05)]  # 5th percentile
        else:
            volatility = 0
            var_95 = returns[0] if returns else 0

        # Maximum single loss
        losses = [r for r in returns if r < 0]
        max_loss = min(losses) if losses else 0

        # Consecutive losses
        consecutive = 0
        max_consecutive = 0
        for return_val in returns:
            if return_val < 0:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        return {
            'volatility': round(volatility, 2),
            'var_95': round(var_95, 2),
            'maximum_single_loss': round(max_loss, 2),
            'consecutive_losses': max_consecutive
        }

    def _calculate_efficiency_metrics(self, transactions):
        """Calculate trading efficiency metrics"""

        try:
            # Fee efficiency (returns vs fees paid)
            total_fees = transactions.aggregate(
                fees=Sum('fee_usd')
            )['fees'] or 0

            total_realized = transactions.filter(
                transaction_type='sell',
                realized_profit_loss__isnull=False
            ).aggregate(
                realized=Sum('realized_profit_loss')
            )['realized'] or 0

            fee_efficiency = (float(total_realized) / float(total_fees)) if total_fees > 0 else 0

            # Trade frequency
            if transactions.exists():
                first_tx = transactions.order_by('timestamp').first()
                last_tx = transactions.order_by('timestamp').last()
                days_active = (last_tx.timestamp - first_tx.timestamp).days or 1
                trades_per_day = transactions.count() / days_active
            else:
                trades_per_day = 0

            # Win rate calculation
            sell_txs = transactions.filter(
                transaction_type='sell',
                realized_profit_loss__isnull=False
            )
            
            if sell_txs.exists():
                profitable_trades = sell_txs.filter(realized_profit_loss__gt=0).count()
                win_rate = (profitable_trades / sell_txs.count()) * 100
            else:
                win_rate = 0

            return {
                'fee_efficiency': round(fee_efficiency, 2),
                'trades_per_day': round(trades_per_day, 2),
                'total_fees_paid': float(total_fees),
                'win_rate': round(win_rate, 1),
                'consistency_score': round(min(win_rate / 100, 1.0), 2)  # Normalized consistency
            }
        except Exception as e:
            logger.error(f"Error calculating efficiency metrics: {e}")
            return {
                'fee_efficiency': 0,
                'trades_per_day': 0,
                'total_fees_paid': 0,
                'win_rate': 0,
                'consistency_score': 0
            }
    
    def _calculate_asset_allocation(self, current_holdings, total_portfolio_value):
        """Calculate asset allocation percentages"""
        from crypto_tax_api.utils.blockchain_apis import fetch_price_data
        
        allocation = []
        
        for asset, amount in current_holdings.items():
            try:
                current_price = fetch_price_data(asset)
                asset_value = amount * float(current_price)
                percentage = (asset_value / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
                
                allocation.append({
                    'asset': asset,
                    'amount': amount,
                    'value_usd': asset_value,
                    'percentage': round(percentage, 2)
                })
            except Exception as e:
                logger.error(f"Error calculating allocation for {asset}: {e}")
        
        # Sort by value descending
        allocation.sort(key=lambda x: x['value_usd'], reverse=True)
        return allocation


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coinbase_oauth_authorize(request):
    """
    Generate Coinbase OAuth authorization URL
    """
    try:
        oauth_service = CoinbaseOAuthService()
        
        # Generate a state parameter for CSRF protection
        import secrets
        state = secrets.token_urlsafe(32)
        
        # Store state in session for verification
        request.session['coinbase_oauth_state'] = state
        
        # Generate authorization URL
        auth_url = oauth_service.get_authorization_url(state=state)
        
        return Response({
            'authorization_url': auth_url,
            'state': state
        })
        
    except Exception as e:
        logger.error(f"Error generating Coinbase OAuth URL: {str(e)}")
        return Response(
            {'error': f'Failed to generate authorization URL: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def coinbase_oauth_callback(request):
    """
    Handle Coinbase OAuth callback and exchange code for token
    """
    try:
        # Get authorization code and state from request
        authorization_code = request.data.get('code')
        received_state = request.data.get('state')
        
        if not authorization_code:
            return Response(
                {'error': 'Authorization code is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify state parameter for CSRF protection
        stored_state = request.session.get('coinbase_oauth_state')
        if not stored_state or stored_state != received_state:
            return Response(
                {'error': 'Invalid state parameter'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Clear the state from session
        request.session.pop('coinbase_oauth_state', None)
        
        oauth_service = CoinbaseOAuthService()
        
        # Exchange code for token
        token_data = oauth_service.exchange_code_for_token(authorization_code)
        
        # Store OAuth credentials
        credential = oauth_service.store_oauth_credentials(request.user, token_data)
        
        # Test the connection
        access_token = token_data['access_token']
        success, message = oauth_service.test_connection(access_token)
        
        if success:
            return Response({
                'success': True,
                'message': message,
                'credential_id': credential.id,
                'exchange': 'coinbase',
                'auth_type': 'oauth'
            })
        else:
            # If test fails, remove the credential
            credential.delete()
            return Response(
                {'error': f'Connection test failed: {message}'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Exception as e:
        logger.error(f"Error in Coinbase OAuth callback: {str(e)}")
        return Response(
            {'error': f'OAuth callback failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def coinbase_oauth_revoke(request):
    """
    Revoke Coinbase OAuth token and remove credential
    """
    try:
        oauth_service = CoinbaseOAuthService()
        
        # Get OAuth credentials
        credential_data = oauth_service.get_oauth_credentials(request.user)
        access_token = credential_data['access_token']
        
        # Revoke the token
        revoked = oauth_service.revoke_token(access_token)
        
        # Remove the credential from database
        ExchangeCredential.objects.filter(
            user=request.user,
            exchange='coinbase'
        ).delete()
        
        return Response({
            'success': True,
            'message': 'Coinbase OAuth connection revoked successfully',
            'token_revoked': revoked
        })
        
    except Exception as e:
        logger.error(f"Error revoking Coinbase OAuth: {str(e)}")
        return Response(
            {'error': f'Failed to revoke OAuth: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coinbase_oauth_status(request):
    """
    Check Coinbase OAuth connection status
    """
    try:
        oauth_service = CoinbaseOAuthService()
        
        try:
            credential_data = oauth_service.get_oauth_credentials(request.user)
            is_expired = oauth_service.is_token_expired(credential_data)
            
            return Response({
                'connected': True,
                'auth_type': 'oauth',
                'token_expired': is_expired,
                'expires_at': credential_data.get('expires_at'),
                'scope': credential_data.get('scope')
            })
            
        except ValueError:
            # No OAuth credentials found
            return Response({
                'connected': False,
                'auth_type': None
            })
            
    except Exception as e:
        logger.error(f"Error checking Coinbase OAuth status: {str(e)}")
        return Response(
            {'error': f'Failed to check OAuth status: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# Coinbase CDP Authentication Endpoints
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def coinbase_cdp_key_upload(request):
    """
    Upload and store CDP API key for Coinbase Advanced Trade
    """
    try:
        key_json = request.data.get('key_json')

        if not key_json:
            return Response(
                {'error': 'Missing key_json in request'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Parse and validate CDP key
        try:
            key_data = parse_cdp_key(key_json)
            key_meta = extract_key_meta(key_data)
        except ValueError as e:
            return Response(
                {'error': f'Invalid CDP key format: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Encrypt the private key
        encryption = CdpKeyEncryption()
        encrypted_key = encryption.encrypt(key_data.private_key)

        # Store or update the CDP credential
        credential, created = ExchangeCredential.objects.update_or_create(
            user=request.user,
            exchange='coinbase_advanced',
            defaults={
                'api_key': key_meta.key_id,  # Store key ID as api_key
                'api_secret': encrypted_key,  # Store encrypted private key
                'api_passphrase': key_meta.org_id,  # Store org ID as passphrase
                'is_connected': True,
                'auth_type': 'cdp'
            }
        )

        # Log the action (with sanitized data)
        logger.info(f"CDP key {'updated' if not created else 'added'} for user {request.user.id}")

        return Response({
            'success': True,
            'key_id': key_meta.key_id,
            'org_id': key_meta.org_id,
            'message': 'CDP key successfully uploaded and encrypted'
        })

    except Exception as e:
        logger.error(f"Error uploading CDP key: {str(e)}")
        return Response(
            {'error': f'Failed to upload CDP key: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coinbase_cdp_accounts(request):
    """
    Get Coinbase accounts using CDP authentication
    """
    import asyncio

    try:
        # Get CDP credentials
        credential = ExchangeCredential.objects.filter(
            user=request.user,
            exchange='coinbase_advanced',
            auth_type='cdp'
        ).first()

        if not credential:
            return Response(
                {'error': 'No CDP credentials found. Please upload your CDP key first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create key loader function
        async def load_key():
            from .services.coinbase_cdp_auth import CdpKeyData
            encryption = CdpKeyEncryption()
            decrypted_key = encryption.decrypt(credential.api_secret)

            # Reconstruct the key name from stored metadata
            key_name = f"organizations/{credential.api_passphrase}/apiKeys/{credential.api_key}"

            return CdpKeyData(
                name=key_name,
                private_key=decrypted_key
            )

        # Create client and fetch accounts
        async def fetch_accounts():
            client = CoinbaseAdvancedClient(load_key)
            try:
                accounts_data = await client.get_accounts()
                return accounts_data
            finally:
                await client.close()

        # Run async function
        accounts_data = asyncio.run(fetch_accounts())

        return Response({
            'success': True,
            'accounts': accounts_data.get('accounts', []),
            'has_next': accounts_data.get('has_next', False),
            'cursor': accounts_data.get('cursor')
        })

    except Exception as e:
        logger.error(f"Error fetching CDP accounts: {str(e)}")
        return Response(
            {'error': f'Failed to fetch accounts: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def coinbase_cdp_fills(request):
    """
    Get trading fills (executions) using CDP authentication
    """
    import asyncio

    try:
        # Get CDP credentials
        credential = ExchangeCredential.objects.filter(
            user=request.user,
            exchange='coinbase_advanced',
            auth_type='cdp'
        ).first()

        if not credential:
            return Response(
                {'error': 'No CDP credentials found. Please upload your CDP key first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get query parameters
        product_id = request.GET.get('product_id')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        limit = int(request.GET.get('limit', 100))
        cursor = request.GET.get('cursor')

        # Create key loader function
        async def load_key():
            from .services.coinbase_cdp_auth import CdpKeyData
            encryption = CdpKeyEncryption()
            decrypted_key = encryption.decrypt(credential.api_secret)

            key_name = f"organizations/{credential.api_passphrase}/apiKeys/{credential.api_key}"

            return CdpKeyData(
                name=key_name,
                private_key=decrypted_key
            )

        # Create client and fetch fills
        async def fetch_fills():
            client = CoinbaseAdvancedClient(load_key)
            try:
                fills_data = await client.list_fills(
                    product_id=product_id,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                    cursor=cursor
                )
                return fills_data
            finally:
                await client.close()

        # Run async function
        fills_data = asyncio.run(fetch_fills())

        # Process fills for tax calculations if requested
        process_for_tax = request.GET.get('process_for_tax', 'false').lower() == 'true'
        fills = fills_data.get('fills', [])

        if process_for_tax:
            processed_fills = []
            for fill in fills:
                try:
                    processed = process_fill_for_tax(fill)
                    processed_fills.append(processed)
                except Exception as e:
                    logger.warning(f"Error processing fill {fill.get('entry_id')}: {e}")

            return Response({
                'success': True,
                'fills': fills,
                'processed_fills': processed_fills,
                'cursor': fills_data.get('cursor')
            })

        return Response({
            'success': True,
            'fills': fills,
            'cursor': fills_data.get('cursor')
        })

    except Exception as e:
        logger.error(f"Error fetching CDP fills: {str(e)}")
        return Response(
            {'error': f'Failed to fetch fills: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def coinbase_cdp_sync_transactions(request):
    """
    Sync all transactions using CDP authentication
    """
    import asyncio
    from datetime import datetime, timedelta

    try:
        # Get CDP credentials
        credential = ExchangeCredential.objects.filter(
            user=request.user,
            exchange='coinbase_advanced',
            auth_type='cdp'
        ).first()

        if not credential:
            return Response(
                {'error': 'No CDP credentials found. Please upload your CDP key first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get sync parameters
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        # Default to last 365 days if not specified
        if not start_date:
            start_date = (datetime.now() - timedelta(days=365)).isoformat()
        if not end_date:
            end_date = datetime.now().isoformat()

        # Create key loader function
        async def load_key():
            from .services.coinbase_cdp_auth import CdpKeyData
            encryption = CdpKeyEncryption()
            decrypted_key = encryption.decrypt(credential.api_secret)

            key_name = f"organizations/{credential.api_passphrase}/apiKeys/{credential.api_key}"

            return CdpKeyData(
                name=key_name,
                private_key=decrypted_key
            )

        # Sync transactions
        async def sync_all_transactions():
            client = CoinbaseAdvancedClient(load_key)
            all_fills = []
            cursor = None

            try:
                # Paginate through all fills
                while True:
                    fills_data = await client.list_fills(
                        start_date=start_date,
                        end_date=end_date,
                        limit=100,
                        cursor=cursor
                    )

                    fills = fills_data.get('fills', [])
                    all_fills.extend(fills)

                    # Check for next page
                    cursor = fills_data.get('cursor')
                    if not cursor or not fills:
                        break

                return all_fills

            finally:
                await client.close()

        # Run sync
        all_fills = asyncio.run(sync_all_transactions())

        # Process and store transactions
        processed_count = 0
        error_count = 0

        for fill in all_fills:
            try:
                # Process fill for tax
                tax_data = process_fill_for_tax(fill)

                # Store in database
                CexTransaction.objects.update_or_create(
                    user=request.user,
                    exchange='coinbase_advanced',
                    transaction_id=fill.get('entry_id'),
                    defaults={
                        'timestamp': datetime.fromisoformat(fill.get('trade_time').replace('Z', '+00:00')),
                        'transaction_type': tax_data['type'].lower(),
                        'asset': tax_data['asset'],
                        'amount': Decimal(str(tax_data['quantity'])),
                        'price': Decimal(str(fill.get('price', '0'))),
                        'fee': Decimal(str(tax_data['fee'])),
                        'fee_currency': tax_data['fee_currency'],
                        'raw_data': fill
                    }
                )
                processed_count += 1

            except Exception as e:
                logger.error(f"Error processing fill {fill.get('entry_id')}: {e}")
                error_count += 1

        return Response({
            'success': True,
            'total_fills': len(all_fills),
            'processed': processed_count,
            'errors': error_count,
            'start_date': start_date,
            'end_date': end_date
        })

    except Exception as e:
        logger.error(f"Error syncing CDP transactions: {str(e)}")
        return Response(
            {'error': f'Failed to sync transactions: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def coinbase_cdp_key_delete(request):
    """
    Delete stored CDP key
    """
    try:
        deleted_count = ExchangeCredential.objects.filter(
            user=request.user,
            exchange='coinbase_advanced',
            auth_type='cdp'
        ).delete()[0]

        if deleted_count > 0:
            return Response({
                'success': True,
                'message': 'CDP key deleted successfully'
            })
        else:
            return Response({
                'success': False,
                'message': 'No CDP key found to delete'
            }, status=status.HTTP_404_NOT_FOUND)

    except Exception as e:
        logger.error(f"Error deleting CDP key: {str(e)}")
        return Response(
            {'error': f'Failed to delete CDP key: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )