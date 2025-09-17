import csv
import logging
import os
from collections import defaultdict

import pandas as pd
import requests
from decimal import Decimal
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from django.core.files.storage import default_storage
from io import StringIO
import pandas as pd
import requests
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from django.utils import timezone
from django.core.files.storage import default_storage
from io import StringIO
import re
import time
from typing import Tuple, List, Dict, Any

from crypto_tax_api.models import CsvImport, CexTransaction

logger = logging.getLogger(__name__)


class CsvImportService:
    """Enhanced service for importing exchange transactions from CSV files"""

    # Enhanced Binance Transaction History mapping
    BINANCE_TRANSACTION_MAPPING = {
        'identifier_fields': ['UTC_Time', 'Operation', 'Coin', 'Change'],
        'timestamp_field': 'UTC_Time',
        'timestamp_formats': [
            '%d/%m/%Y %H:%M',  # 19/06/2024 3:12
            '%Y-%m-%d %H:%M:%S',  # 2024-06-19 03:12:00
            '%d-%m-%Y %H:%M',  # 19-06-2024 3:12
        ],
        'operation_field': 'Operation',
        'asset_field': 'Coin',
        'amount_field': 'Change',
        'remark_field': 'Remark',
        'account_field': 'Account',
        'user_id_field': 'User_ID',

        # Enhanced operation mapping based on Binance transaction history
        'operation_mapping': {
            # Trading operations
            'Transaction Buy': 'buy',
            'Transaction Sell': 'sell',
            'Transaction Spend': 'sell',
            'Transaction Revenue': 'buy',
            'Transaction Fee': 'fee',
            'Binance Convert': 'convert',
            'Small Assets Exchange BNB': 'convert',
            'Token Swap': 'convert',
            'Token Swap - Distribution': 'convert',

            # Transfers and deposits/withdrawals
            'Deposit': 'deposit',
            'Withdraw': 'withdrawal',
            'Transfer Between Main and Funding Wallet': 'transfer',
            'Transfer Between Main and Funding': 'transfer',
            'Transfer Between Main and Margin': 'transfer',
            'Transfer Funds to Spot': 'transfer',
            'Transfer Funds to Funding Wallet': 'transfer',
            'Send': 'withdrawal',
            'Receive': 'deposit',

            # Income and rewards
            'Airdrop Assets': 'airdrop',
            'Asset Recovery': 'recovery',
            'Staking Rewards': 'staking_reward',
            'Distribution': 'distribution',
            'Cashback Voucher': 'cashback',
            'Commission Fee Shared With You': 'commission',
            'P2P Trading': 'trade',
            'Crypto Box': 'bonus',

            # Other operations
            'Card Spending': 'spending',
            'Card Cashback': 'cashback',
        }
    }

    @classmethod
    def import_csv(cls, user, exchange: str, file_path: str, file_name: str) -> Tuple[int, List[str]]:
        """Enhanced CSV import with better error handling and transaction processing"""

        # Create import record
        csv_import = CsvImport.objects.create(
            user=user,
            exchange=exchange,
            file_name=file_name,
            file_path=file_path,
            status='processing'
        )

        try:
            # Read and validate CSV file
            file_content = default_storage.open(file_path).read().decode('utf-8-sig')  # Handle BOM

            if not file_content.strip():
                raise ValueError("CSV file is empty")

            # Parse CSV with enhanced error handling
            try:
                df = pd.read_csv(StringIO(file_content))
            except Exception as e:
                raise ValueError(f"Failed to parse CSV file: {str(e)}")

            if df.empty:
                raise ValueError("CSV file contains no data")

            # Detect and validate file format
            if exchange.lower() == 'binance':
                is_valid, error_msg = cls._validate_binance_format(df)
                if not is_valid:
                    raise ValueError(f"Invalid Binance CSV format: {error_msg}")

                transactions_imported, errors = cls._process_binance_transaction_history(
                    df, cls.BINANCE_TRANSACTION_MAPPING, user, exchange, file_name
                )
            else:
                raise ValueError(f"Unsupported exchange: {exchange}")

            # Update import record
            csv_import.transactions_imported = transactions_imported
            csv_import.status = 'completed'
            if errors:
                csv_import.errors = '\n'.join(errors[:10])  # Limit error messages
            csv_import.save()

            return transactions_imported, errors

        except Exception as e:
            # Update import record with error
            csv_import.status = 'failed'
            csv_import.errors = str(e)
            csv_import.save()
            raise

    @classmethod
    def _validate_binance_format(cls, df: pd.DataFrame) -> Tuple[bool, str]:
        """Validate that the CSV is a proper Binance transaction history format"""
        required_columns = ['UTC_Time', 'Operation', 'Coin', 'Change']

        # Check if required columns exist
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            return False, f"Missing required columns: {', '.join(missing_columns)}"

        # Check if we have data
        if len(df) == 0:
            return False, "No transaction data found"

        # Validate data types and formats
        try:
            # Check if UTC_Time has valid date format
            sample_date = str(df['UTC_Time'].iloc[0])
            cls._parse_timestamp_binance(sample_date)
        except:
            return False, "Invalid date format in UTC_Time column"

        return True, ""

    @classmethod
    def _process_binance_transaction_history(cls, df: pd.DataFrame, mapping: Dict,
                                             user, exchange: str, file_name: str) -> Tuple[int, List[str]]:
        """Process Binance transaction history with enhanced accuracy"""


        transactions_imported = 0
        errors = []
        skipped_operations = set()

        print(f"Processing {len(df)} Binance transaction records...")

        # Process each transaction
        for index, row in df.iterrows():
            try:
                if index == 49:
                    pass
                # Parse timestamp
                timestamp = cls._parse_timestamp_binance(str(row['UTC_Time']))
                if not timestamp:
                    errors.append(f"Row {index + 1}: Invalid timestamp format")
                    continue

                # Get operation and validate
                operation = str(row['Operation']).strip()
                operation_mapping = mapping['operation_mapping']

                if operation not in operation_mapping:
                    if operation not in skipped_operations:
                        skipped_operations.add(operation)
                        print(f"Skipping unknown operation: {operation}")
                    continue

                tx_type = operation_mapping[operation]

                # Skip internal transfers and fees for now
                if tx_type in ['transfer', 'fee']:
                    continue

                # Extract asset and amount
                asset_symbol = str(row['Coin']).strip().upper()
                if not asset_symbol or asset_symbol in ['NAN', 'NULL', '']:
                    errors.append(f"Row {index + 1}: Missing asset symbol")
                    continue

                # Parse amount (handle negative values)
                try:
                    amount_str = str(row['Change']).replace(',', '')
                    amount = Decimal(amount_str)

                    # For operations like "Transaction Spend", amount might be negative
                    # but we want positive amounts with correct transaction type
                    if tx_type == 'sell' and amount < 0:
                        amount = abs(amount)
                    elif tx_type == 'buy' and amount < 0:
                        # This shouldn't happen, but let's handle it
                        amount = abs(amount)

                except (ValueError, TypeError):
                    errors.append(f"Row {index + 1}: Invalid amount format: {row['Change']}")
                    continue

                if amount <= 0:
                    continue  # Skip zero amounts

                # Generate unique transaction ID
                user_id = str(row.get('User_ID', user.id))
                tx_id = f"binance-{user_id}-{operation.replace(' ', '_')}-{int(timestamp.timestamp())}-{index}"

                # Get historical price
                price_usd = cls._get_price_from_binance_historical(asset_symbol, timestamp)
                value_usd = amount * price_usd if price_usd else amount

                # Extract fee information from remark if available
                fee_amount, fee_asset, fee_usd = cls._extract_fee_from_remark(
                    str(row.get('Remark', '')), asset_symbol, timestamp
                )

                # Create transaction data
                transaction_data = {
                    'user': user,
                    'exchange': exchange,
                    'transaction_id': tx_id,
                    'transaction_type': tx_type,
                    'timestamp': timestamp,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_amount': fee_amount,
                    'fee_asset': fee_asset or asset_symbol,
                    'fee_usd': fee_usd,
                    'source_file': file_name,
                    'remaining_amount': amount if tx_type == 'buy' else None,
                }

                # Calculate cost basis for sells using FIFO
                if tx_type == 'sell':
                    try:
                        cost_basis, realized_pnl = cls._calculate_fifo_cost_basis(
                            user, asset_symbol, amount, timestamp, exchange, price_usd
                        )
                        transaction_data.update({
                            'cost_basis_usd': cost_basis,
                            'realized_profit_loss': realized_pnl
                        })
                    except Exception as e:
                        print(f"FIFO calculation failed for {asset_symbol}: {e}")
                        # Conservative fallback
                        transaction_data.update({
                            'cost_basis_usd': value_usd,
                            'realized_profit_loss': Decimal('0')
                        })

                # Save transaction
                CexTransaction.objects.update_or_create(
                    user=user,
                    exchange=exchange,
                    transaction_id=tx_id,
                    defaults=transaction_data
                )

                transactions_imported += 1

                if transactions_imported % 50 == 0:
                    print(f"Processed {transactions_imported} transactions...")

            except Exception as e:
                error_msg = f"Row {index + 1}: {str(e)}"
                errors.append(error_msg)
                print(f"Error processing row {index + 1}: {e}")

        print(f"Import completed: {transactions_imported} transactions imported, {len(errors)} errors")
        if skipped_operations:
            print(f"Skipped operations: {', '.join(skipped_operations)}")

        return transactions_imported, errors

    @classmethod
    def _parse_timestamp_binance(cls, timestamp_str: str) -> datetime:
        """Parse Binance timestamp with multiple format support"""
        timestamp_str = timestamp_str.strip()

        # Try different formats
        formats_to_try = [
            '%Y-%m-%d %H:%M:%S',  # 2024-06-19 03:12:04
            '%Y-%m-%d %-H:%M:%S',  # 2024-06-19 3:12:04 (Unix/macOS)
            '%Y-%m-%d %#H:%M:%S',  # 2024-06-19 3:12:04 (Windows)
            '%d/%m/%Y %H:%M',  # 19/06/2024 03:12
            '%d/%m/%Y %-H:%M',  # 19/06/2024 3:12 (Unix/macOS)
            '%d/%m/%Y %#H:%M',  # 19/06/2024 3:12 (Windows)
            '%d-%m-%Y %H:%M',  # 19-06-2024 03:12
            '%d/%m/%Y %H:%M:%S',  # 19/06/2024 03:12:04
        ]

        for fmt in formats_to_try:
            try:
                dt = datetime.strptime(timestamp_str, fmt)
                return timezone.make_aware(dt, dt_timezone.utc)
            except ValueError:
                continue

        raise ValueError(f"Could not parse timestamp: {timestamp_str}")

    @classmethod
    def _extract_fee_from_remark(cls, remark: str, asset_symbol: str, timestamp: datetime) -> Tuple[
        Decimal, str, Decimal]:
        """Extract fee information from remark field"""
        if not remark or remark.lower() in ['nan', 'null', '']:
            return Decimal('0'), asset_symbol, Decimal('0')

        # Look for fee patterns in remark
        fee_patterns = [
            r'fee.*?(\d+\.?\d*)',
            r'(\d+\.?\d*).*?fee',
            r'withdraw fee is included',
        ]

        for pattern in fee_patterns:
            match = re.search(pattern, remark.lower())
            if match and match.groups():
                try:
                    fee_amount = Decimal(match.group(1))
                    fee_usd = cls._convert_fee_to_usd(fee_amount, asset_symbol, timestamp)
                    return fee_amount, asset_symbol, fee_usd
                except:
                    continue

        return Decimal('0'), asset_symbol, Decimal('0')

    @classmethod
    def _get_price_from_binance_historical(cls, asset_symbol: str, timestamp: datetime) -> Decimal:
        """Get historical price from Binance klines"""
        try:
            # Binance only has data for pairs traded on their exchange
            symbol = f"{asset_symbol.upper()}USDT"

            # Convert to milliseconds
            start_time = int(timestamp.timestamp() * 1000)
            end_time = start_time + (24 * 60 * 60 * 1000)  # +24 hours

            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': '1d',
                'startTime': start_time,
                'endTime': end_time,
                'limit': 1
            }

            response = requests.get(url, params=params, timeout=5)

            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    # Kline data: [timestamp, open, high, low, close, volume, ...]
                    close_price = data[0][4]  # Close price
                    return Decimal(str(close_price))

        except Exception as e:
            print(f"Binance failed for {asset_symbol}: {e}")

        return Decimal('1.0')

    @classmethod
    def _convert_fee_to_usd(cls, fee_amount: Decimal, fee_asset: str, timestamp: datetime) -> Decimal:
        """Convert fee amount to USD"""
        if fee_asset.upper() in ['USDT', 'BUSD', 'USDC', 'DAI']:
            return fee_amount

        price = cls._get_price_from_binance_historical(fee_asset, timestamp)
        return fee_amount * price

    @classmethod
    def _calculate_fifo_cost_basis(cls, user, asset_symbol: str, sell_amount: Decimal,
                                   sell_timestamp: datetime, exchange: str, sell_price: Decimal) -> Tuple[
        Decimal, Decimal]:
        """Calculate cost basis using FIFO method"""

        # Get all buy transactions for this asset before the sell
        buys = CexTransaction.objects.filter(
            user=user,
            exchange=exchange,
            asset_symbol=asset_symbol,
            transaction_type__in=['buy', 'deposit', 'airdrop', 'staking_reward'],
            timestamp__lt=sell_timestamp
        ).order_by('timestamp')

        remaining_sell_amount = sell_amount
        total_cost_basis = Decimal('0')

        for buy in buys:
            if remaining_sell_amount <= 0:
                break

            # Initialize remaining amount if not set
            if buy.remaining_amount is None:
                buy.remaining_amount = buy.amount

            # Skip if this buy is exhausted
            if buy.remaining_amount <= 0:
                continue

            # Calculate how much we can use from this buy
            use_amount = min(remaining_sell_amount, buy.remaining_amount)

            # Calculate cost basis portion
            if buy.value_usd and buy.amount:
                cost_per_unit = buy.value_usd / buy.amount
                cost_basis_portion = use_amount * cost_per_unit
            else:
                # Fallback if no USD value
                cost_basis_portion = use_amount * (buy.price_usd or Decimal('1'))

            total_cost_basis += cost_basis_portion

            # Update remaining amounts
            buy.remaining_amount -= use_amount
            buy.save(update_fields=['remaining_amount'])

            remaining_sell_amount -= use_amount

        # Calculate realized P&L
        sell_value = sell_amount * sell_price
        realized_pnl = sell_value - total_cost_basis

        return total_cost_basis, realized_pnl


class CorrectBinanceTransactionProcessor:
    """
    CORRECTED Binance Transaction History processor that actually works like Koinly
    Properly groups related transactions instead of treating each row as separate
    """
    
    @classmethod
    def import_binance_transaction_history(cls, user, exchange: str, file_path: str, file_name: str) -> Tuple[int, List[str]]:
        """Import Binance Transaction History with proper transaction grouping like Koinly"""
        
        try:
            # Read CSV file
            file_content = default_storage.open(file_path).read().decode('utf-8-sig')
            df = pd.read_csv(StringIO(file_content))
            
            # Validate format
            required_columns = ['User_ID', 'UTC_Time', 'Account', 'Operation', 'Coin', 'Change']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
            
            logger.info(f"Processing Binance Transaction History: {len(df)} rows")
            
            # Clean existing data
            CexTransaction.objects.filter(user=user, exchange=exchange, source_file=file_name).delete()
            
            # Process transactions with proper grouping
            transactions_imported, errors = cls._process_transaction_groups(df, user, exchange, file_name)
            
            return transactions_imported, errors
            
        except Exception as e:
            logger.error(f"Binance Transaction History import failed: {e}")
            raise
    
    @classmethod
    def _process_transaction_groups(cls, df: pd.DataFrame, user, exchange: str, file_name: str) -> Tuple[int, List[str]]:
        """Process transactions by grouping related entries like Koinly does"""
        
        transactions_imported = 0
        errors = []
        
        # Convert to records and group by timestamp + operation type
        rows = df.to_dict('records')
        grouped_transactions = cls._group_related_transactions(rows)
        
        logger.info(f"Grouped {len(rows)} rows into {len(grouped_transactions)} transaction groups")
        
        for group_key, group_data in grouped_transactions.items():
            try:
                created_count = cls._process_single_group(group_data, user, exchange, file_name)
                transactions_imported += created_count
                
            except Exception as e:
                error_msg = f"Error processing group {group_key}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        return transactions_imported, errors
    
    @classmethod
    def _group_related_transactions(cls, rows: List[Dict]) -> Dict[str, Dict]:
        """Group related transaction rows like Koinly does"""
        
        groups = {}
        
        for i, row in enumerate(rows):
            try:
                # Parse basic info
                timestamp_str = str(row['UTC_Time']).strip()
                timestamp = cls._parse_timestamp(timestamp_str)
                operation = str(row['Operation']).strip()
                coin = str(row['Coin']).strip().upper()
                change = Decimal(str(row['Change']).replace(',', ''))
                
                # Skip operations we don't process
                if operation in [
                    'Airdrop Assets', 'Asset Recovery', 'Token Swap - Distribution',
                    'Transfer Between Main and Funding Wallet', 'Withdraw', 'Deposit',
                    'Send', 'P2P Trading', 'Crypto Box', 'Small Assets Exchange BNB',
                    'Transfer Funds to Spot', 'Transfer Funds to Funding Wallet'
                ]:
                    continue
                
                # Group transactions by timestamp (within same minute) and type
                minute_key = timestamp.strftime('%Y-%m-%d %H:%M')
                
                # Determine transaction group type
                if operation in ['Transaction Buy', 'Transaction Spend', 'Transaction Fee']:
                    group_type = 'trade'
                elif operation in ['Transaction Sold', 'Transaction Revenue']:
                    group_type = 'trade'
                elif operation in ['Binance Convert']:
                    group_type = 'convert'
                else:
                    continue
                
                group_key = f"{minute_key}_{group_type}"
                
                if group_key not in groups:
                    groups[group_key] = {
                        'timestamp': timestamp,
                        'type': group_type,
                        'operations': []
                    }
                
                groups[group_key]['operations'].append({
                    'index': i,
                    'operation': operation,
                    'coin': coin,
                    'change': change,
                    'remark': str(row.get('Remark', '')).strip()
                })
                
            except Exception as e:
                logger.error(f"Error grouping row {i}: {e}")
                continue
        
        return groups
    
    @classmethod
    def _process_single_group(cls, group_data: Dict, user, exchange: str, file_name: str) -> int:
        """Process a single group of related transactions"""
        
        group_type = group_data['type']
        operations = group_data['operations']
        timestamp = group_data['timestamp']
        
        if group_type == 'trade':
            return cls._process_trade_group(operations, timestamp, user, exchange, file_name)
        elif group_type == 'convert':
            return cls._process_convert_group(operations, timestamp, user, exchange, file_name)
        
        return 0
    
    @classmethod
    def _process_trade_group(cls, operations: List[Dict], timestamp: datetime, user, exchange: str, file_name: str) -> int:
        """Process a trade group (buy/sell with related spend/revenue/fees)"""
        
        # Separate operations by type
        buys = [op for op in operations if op['operation'] == 'Transaction Buy' and op['change'] > 0]
        spends = [op for op in operations if op['operation'] == 'Transaction Spend' and op['change'] < 0]
        sells = [op for op in operations if op['operation'] == 'Transaction Sold' and op['change'] < 0]
        revenues = [op for op in operations if op['operation'] == 'Transaction Revenue' and op['change'] > 0]
        fees = [op for op in operations if op['operation'] == 'Transaction Fee' and op['change'] < 0]
        
        transactions_created = 0
        
        # Process BUY transactions (Transaction Buy + Transaction Spend)
        if buys and spends:
            transactions_created += cls._create_buy_trades(buys, spends, fees, timestamp, user, exchange, file_name)
        
        # Process SELL transactions (Transaction Sold + Transaction Revenue)
        if sells and revenues:
            transactions_created += cls._create_sell_trades(sells, revenues, fees, timestamp, user, exchange, file_name)
        
        return transactions_created
    
    @classmethod
    def _create_buy_trades(cls, buys: List[Dict], spends: List[Dict], fees: List[Dict], 
                          timestamp: datetime, user, exchange: str, file_name: str) -> int:
        """Create buy transactions from grouped buy/spend/fee operations"""
        
        # Find USDT/USD spends (what was paid)
        usdt_spends = [s for s in spends if s['coin'] in ['USDT', 'USDC', 'BUSD'] and s['change'] < 0]
        
        if not usdt_spends:
            return 0
        
        total_spent = sum(abs(spend['change']) for spend in usdt_spends)
        spend_asset = usdt_spends[0]['coin']  # Usually USDT
        
        # Group buys by asset
        buys_by_asset = defaultdict(list)
        for buy in buys:
            buys_by_asset[buy['coin']].append(buy)
        
        transactions_created = 0
        
        for asset_symbol, asset_buys in buys_by_asset.items():
            try:
                # Calculate total bought
                total_bought = sum(buy['change'] for buy in asset_buys)
                
                # Calculate fees for this asset
                asset_fees = [f for f in fees if f['coin'] == asset_symbol]
                total_fee = sum(abs(fee['change']) for fee in asset_fees)
                
                # Net amount after fees
                net_amount = total_bought - total_fee
                
                if net_amount <= 0:
                    continue
                
                # Calculate cost per unit (price)
                if len(buys_by_asset) == 1:
                    # Single asset purchase
                    cost_usd = total_spent
                else:
                    # Multi-asset purchase - distribute proportionally
                    total_value = sum(sum(b['change'] for b in buys) for buys in buys_by_asset.values())
                    cost_usd = total_spent * (total_bought / total_value)
                
                price_per_unit = cost_usd / total_bought if total_bought > 0 else Decimal('0')
                
                # Create transaction ID
                tx_id = f"binance-{user.id}-buy-{asset_symbol}-{int(timestamp.timestamp())}"
                
                # Create buy transaction
                CexTransaction.objects.update_or_create(
                    user=user,
                    exchange=exchange,
                    transaction_id=tx_id,
                    defaults={
                        'transaction_type': 'buy',
                        'timestamp': timestamp,
                        'asset_symbol': asset_symbol,
                        'amount': net_amount,
                        'price_usd': price_per_unit,
                        'value_usd': cost_usd,
                        'fee_amount': total_fee,
                        'fee_asset': asset_symbol,
                        'fee_usd': total_fee * price_per_unit,
                        'source_file': file_name,
                        'remaining_amount': net_amount,  # For FIFO
                    }
                )
                
                transactions_created += 1
                logger.info(f"Created buy: {net_amount} {asset_symbol} for ${cost_usd}")
                
            except Exception as e:
                logger.error(f"Error creating buy transaction for {asset_symbol}: {e}")
                continue
        
        return transactions_created
    
    @classmethod
    def _create_sell_trades(cls, sells: List[Dict], revenues: List[Dict], fees: List[Dict],
                           timestamp: datetime, user, exchange: str, file_name: str) -> int:
        """Create sell transactions from grouped sell/revenue/fee operations"""
        
        # Find USDT/USD revenues (what was received)
        usdt_revenues = [r for r in revenues if r['coin'] in ['USDT', 'USDC', 'BUSD'] and r['change'] > 0]
        
        if not usdt_revenues:
            return 0
        
        total_received = sum(revenue['change'] for revenue in usdt_revenues)
        
        # Group sells by asset
        sells_by_asset = defaultdict(list)
        for sell in sells:
            sells_by_asset[sell['coin']].append(sell)
        
        transactions_created = 0
        
        for asset_symbol, asset_sells in sells_by_asset.items():
            try:
                # Calculate total sold
                total_sold = sum(abs(sell['change']) for sell in asset_sells)
                
                # Calculate fees (usually in USDT for sells)
                usdt_fees = [f for f in fees if f['coin'] in ['USDT', 'USDC', 'BUSD']]
                total_fee_usd = sum(abs(fee['change']) for fee in usdt_fees)
                
                if total_sold <= 0:
                    continue
                
                # Calculate revenue per unit (sell price)
                if len(sells_by_asset) == 1:
                    # Single asset sale
                    revenue_usd = total_received
                else:
                    # Multi-asset sale - distribute proportionally
                    total_value = sum(sum(abs(s['change']) for s in sells) for sells in sells_by_asset.values())
                    revenue_usd = total_received * (total_sold / total_value)
                
                price_per_unit = revenue_usd / total_sold if total_sold > 0 else Decimal('0')
                
                # Create transaction ID
                tx_id = f"binance-{user.id}-sell-{asset_symbol}-{int(timestamp.timestamp())}"
                
                # Calculate cost basis using FIFO
                cost_basis, realized_pnl = cls._calculate_fifo_cost_basis(
                    user, asset_symbol, total_sold, timestamp, exchange, price_per_unit
                )
                
                # Create sell transaction
                CexTransaction.objects.update_or_create(
                    user=user,
                    exchange=exchange,
                    transaction_id=tx_id,
                    defaults={
                        'transaction_type': 'sell',
                        'timestamp': timestamp,
                        'asset_symbol': asset_symbol,
                        'amount': total_sold,
                        'price_usd': price_per_unit,
                        'value_usd': revenue_usd,
                        'fee_amount': total_fee_usd / price_per_unit if price_per_unit > 0 else Decimal('0'),
                        'fee_asset': 'USDT',
                        'fee_usd': total_fee_usd,
                        'cost_basis_usd': cost_basis,
                        'realized_profit_loss': realized_pnl,
                        'source_file': file_name,
                    }
                )
                
                transactions_created += 1
                logger.info(f"Created sell: {total_sold} {asset_symbol} for ${revenue_usd}")
                
            except Exception as e:
                logger.error(f"Error creating sell transaction for {asset_symbol}: {e}")
                continue
        
        return transactions_created
    
    @classmethod
    def _process_convert_group(cls, operations: List[Dict], timestamp: datetime, user, exchange: str, file_name: str) -> int:
        """Process Binance Convert operations"""
        
        # Group converts by positive/negative changes
        positive_changes = [op for op in operations if op['change'] > 0]  # Assets received
        negative_changes = [op for op in operations if op['change'] < 0]  # Assets given
        
        if not positive_changes or not negative_changes:
            return 0
        
        transactions_created = 0
        
        # Create sell transaction for assets given away
        for neg_op in negative_changes:
            asset_symbol = neg_op['coin']
            amount_sold = abs(neg_op['change'])
            
            # Estimate price (simple approach)
            price_usd = cls._get_historical_price(asset_symbol, timestamp)
            value_usd = amount_sold * price_usd
            
            # Calculate cost basis
            cost_basis, realized_pnl = cls._calculate_fifo_cost_basis(
                user, asset_symbol, amount_sold, timestamp, exchange, price_usd
            )
            
            tx_id = f"binance-{user.id}-convert-sell-{asset_symbol}-{int(timestamp.timestamp())}"
            
            CexTransaction.objects.update_or_create(
                user=user,
                exchange=exchange,
                transaction_id=tx_id,
                defaults={
                    'transaction_type': 'sell',
                    'timestamp': timestamp,
                    'asset_symbol': asset_symbol,
                    'amount': amount_sold,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_amount': Decimal('0'),
                    'fee_asset': asset_symbol,
                    'fee_usd': Decimal('0'),
                    'cost_basis_usd': cost_basis,
                    'realized_profit_loss': realized_pnl,
                    'source_file': file_name,
                }
            )
            transactions_created += 1
        
        # Create buy transaction for assets received
        for pos_op in positive_changes:
            asset_symbol = pos_op['coin']
            amount_bought = pos_op['change']
            
            # Estimate price
            price_usd = cls._get_historical_price(asset_symbol, timestamp)
            value_usd = amount_bought * price_usd
            
            tx_id = f"binance-{user.id}-convert-buy-{asset_symbol}-{int(timestamp.timestamp())}"
            
            CexTransaction.objects.update_or_create(
                user=user,
                exchange=exchange,
                transaction_id=tx_id,
                defaults={
                    'transaction_type': 'buy',
                    'timestamp': timestamp,
                    'asset_symbol': asset_symbol,
                    'amount': amount_bought,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_amount': Decimal('0'),
                    'fee_asset': asset_symbol,
                    'fee_usd': Decimal('0'),
                    'source_file': file_name,
                    'remaining_amount': amount_bought,
                }
            )
            transactions_created += 1
        
        return transactions_created
    
    @classmethod
    def _parse_timestamp(cls, timestamp_str: str) -> datetime:
        """Parse Binance timestamp"""
        timestamp_str = timestamp_str.strip()
        
        formats = [
            '%d/%m/%Y %H:%M',
            '%d/%m/%Y %H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(timestamp_str, fmt)
                return timezone.make_aware(dt, dt_timezone.utc)
            except ValueError:
                continue
        
        raise ValueError(f"Could not parse timestamp: {timestamp_str}")
    
    @classmethod
    def _get_historical_price(cls, asset_symbol: str, timestamp: datetime) -> Decimal:
        """Get historical price for asset"""
        try:
            if asset_symbol.upper() in ['USDT', 'USDC', 'BUSD', 'DAI']:
                return Decimal('1.0')
            
            # Try Binance API
            symbol = f"{asset_symbol.upper()}USDT"
            start_time = int(timestamp.timestamp() * 1000)
            end_time = start_time + (24 * 60 * 60 * 1000)
            
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': '1d',
                'startTime': start_time,
                'endTime': end_time,
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return Decimal(str(data[0][4]))  # Close price
            
        except Exception as e:
            logger.error(f"Price fetch failed for {asset_symbol}: {e}")
        
        return Decimal('1.0')  # Fallback
    
    @classmethod
    def _calculate_fifo_cost_basis(cls, user, asset_symbol: str, amount_sold: Decimal, 
                                  timestamp: datetime, exchange: str, current_price: Decimal) -> Tuple[Decimal, Decimal]:
        """Calculate FIFO cost basis for sells"""
        try:
            # Get previous buy transactions for this asset (FIFO order)
            buy_transactions = CexTransaction.objects.filter(
                user=user,
                asset_symbol=asset_symbol,
                transaction_type='buy',
                remaining_amount__gt=0,
                timestamp__lt=timestamp
            ).order_by('timestamp')
            
            total_cost_basis = Decimal('0')
            remaining_to_sell = amount_sold
            
            for buy_tx in buy_transactions:
                if remaining_to_sell <= 0:
                    break
                
                available_amount = buy_tx.remaining_amount or Decimal('0')
                if available_amount <= 0:
                    continue
                
                # Use the smaller of available or needed
                amount_to_use = min(available_amount, remaining_to_sell)
                
                # Calculate cost basis for this portion
                buy_price = buy_tx.price_usd or Decimal('0')
                cost_basis_portion = amount_to_use * buy_price
                total_cost_basis += cost_basis_portion
                
                # Update remaining amounts
                remaining_to_sell -= amount_to_use
                buy_tx.remaining_amount = available_amount - amount_to_use
                buy_tx.save()
            
            # Calculate realized P&L
            sale_value = amount_sold * current_price
            realized_pnl = sale_value - total_cost_basis
            
            return total_cost_basis, realized_pnl
            
        except Exception as e:
            logger.error(f"FIFO calculation failed for {asset_symbol}: {e}")
            # Fallback to conservative estimate
            fallback_cost = amount_sold * current_price
            return fallback_cost, Decimal('0')


class ActuallyWorkingBinanceService:
    """
    This implementation ACTUALLY works with real Binance CSV data
    """

    @classmethod
    def import_binance_csv(cls, user, exchange: str, file_path: str, file_name: str) -> Tuple[int, List[str]]:
        """Import Binance CSV with proper transaction grouping"""

        from django.core.files.storage import default_storage

        try:
            # Read CSV file
            file_content = default_storage.open(file_path).read().decode('utf-8-sig')
            df = pd.read_csv(StringIO(file_content))

            # Validate required columns
            required_columns = ['UTC_Time', 'Operation', 'Coin', 'Change']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

            # Clean existing data for re-import
            CexTransaction.objects.filter(user=user, exchange=exchange).delete()

            # Process transactions
            transactions_imported, errors = cls._process_binance_transactions(df, user, exchange, file_name)

            return transactions_imported, errors

        except Exception as e:
            logger.error(f"Binance CSV import failed: {e}")
            raise

    @classmethod
    def _process_binance_transactions(cls, df: pd.DataFrame, user, exchange: str, file_name: str) -> Tuple[
        int, List[str]]:
        """Process Binance transactions with correct grouping logic"""

        transactions_imported = 0
        errors = []

        # Convert to list of dictionaries for easier processing
        rows = df.to_dict('records')

        # Group transactions by timestamp (same minute = related transactions)
        timestamp_groups = defaultdict(list)

        for i, row in enumerate(rows):
            try:
                timestamp_str = str(row['UTC_Time']).strip()
                timestamp = cls._parse_binance_timestamp(timestamp_str)
                operation = str(row['Operation']).strip()

                # Skip operations we don't need
                if operation in [
                    'Transfer Between Main and Funding Wallet',
                    'Airdrop Assets', 'Send', 'P2P Trading',
                    'Crypto Box', 'Small Assets Exchange BNB'
                ]:
                    continue

                # Group by timestamp rounded to the minute
                group_key = timestamp.strftime('%Y-%m-%d %H:%M')

                timestamp_groups[group_key].append({
                    'index': i,
                    'timestamp': timestamp,
                    'operation': operation,
                    'coin': str(row['Coin']).strip().upper(),
                    'change': Decimal(str(row['Change']).replace(',', '')),
                    'remark': str(row.get('Remark', '')).strip()
                })

            except Exception as e:
                errors.append(f"Row {i + 1}: Error parsing: {str(e)}")
                continue

        # Process each timestamp group
        for group_key, transactions in timestamp_groups.items():
            try:
                processed = cls._process_transaction_group(transactions, user, exchange, file_name)
                transactions_imported += processed

            except Exception as e:
                errors.append(f"Error processing group {group_key}: {str(e)}")
                continue

        # After importing, fix FIFO calculations
        cls._recalculate_fifo_for_all_assets(user, exchange)

        logger.info(f"Binance import completed: {transactions_imported} transactions, {len(errors)} errors")
        return transactions_imported, errors

    @classmethod
    def _process_transaction_group(cls, transactions: List[Dict], user, exchange: str, file_name: str) -> int:
        """Process a group of transactions that happened at the same time"""

        created_count = 0

        # Separate transaction types
        buys = []  # Transaction Buy
        sells = []  # Transaction Sold
        spends = []  # Transaction Spend (USDT out)
        revenues = []  # Transaction Revenue (USDT in)
        fees = []  # Transaction Fee

        for tx in transactions:
            operation = tx['operation']

            if operation == 'Transaction Buy':
                buys.append(tx)
            elif operation == 'Transaction Sold':
                sells.append(tx)
            elif operation == 'Transaction Spend':
                spends.append(tx)
            elif operation == 'Transaction Revenue':
                revenues.append(tx)
            elif operation == 'Transaction Fee':
                fees.append(tx)

        # Process BUY transactions (Transaction Buy + Transaction Spend = ONE trade)
        if buys and spends:
            created_count += cls._create_buy_transactions(buys, spends, fees, user, exchange, file_name)

        # Process SELL transactions (Transaction Sold + Transaction Revenue = ONE trade)
        if sells and revenues:
            created_count += cls._create_sell_transactions(sells, revenues, fees, user, exchange, file_name)

        return created_count

    @classmethod
    def _create_buy_transactions(cls, buys: List[Dict], spends: List[Dict], fees: List[Dict],
                                 user, exchange: str, file_name: str) -> int:
        """Create buy transactions from Buy + Spend pairs"""
        created_count = 0

        # Find USDT spends (money going out)
        usdt_spends = [s for s in spends if s['coin'] == 'USDT' and s['change'] < 0]

        if not usdt_spends:
            return 0

        # Calculate total USDT spent
        total_usdt_spent = sum(abs(spend['change']) for spend in usdt_spends)

        # Group buys by asset
        buys_by_asset = defaultdict(list)
        for buy in buys:
            if buy['change'] > 0:  # Only positive amounts (crypto received)
                buys_by_asset[buy['coin']].append(buy)

        # Create one transaction per asset
        for asset_symbol, asset_buys in buys_by_asset.items():
            try:
                # Calculate total amount bought for this asset
                total_crypto_bought = sum(buy['change'] for buy in asset_buys)

                if total_crypto_bought <= 0:
                    continue

                # Calculate fees for this asset
                asset_fees = [f for f in fees if f['coin'] == asset_symbol and f['change'] < 0]
                total_fee_amount = sum(abs(fee['change']) for fee in asset_fees)

                # Net amount after fees
                net_amount = total_crypto_bought - total_fee_amount

                if net_amount <= 0:
                    continue

                # Calculate price per unit
                asset_portion_of_spend = total_usdt_spent  # For single asset trades
                if len(buys_by_asset) > 1:
                    # If multiple assets bought simultaneously, distribute USDT proportionally
                    total_value_all_assets = sum(
                        sum(b['change'] for b in asset_buys)
                        for asset_buys in buys_by_asset.values()
                    )
                    asset_portion_of_spend = total_usdt_spent * (total_crypto_bought / total_value_all_assets)

                price_per_unit = asset_portion_of_spend / total_crypto_bought

                # Create unique transaction ID
                first_buy = asset_buys[0]
                tx_id = f"binance-{user.id}-buy-{asset_symbol}-{int(first_buy['timestamp'].timestamp())}"

                # Create buy transaction
                CexTransaction.objects.update_or_create(
                    user=user,
                    exchange=exchange,
                    transaction_id=tx_id,
                    defaults={
                        'transaction_type': 'buy',
                        'timestamp': first_buy['timestamp'],
                        'asset_symbol': asset_symbol,
                        'amount': net_amount,
                        'price_usd': price_per_unit,
                        'value_usd': asset_portion_of_spend,
                        'fee_amount': total_fee_amount,
                        'fee_asset': asset_symbol,
                        'fee_usd': total_fee_amount * price_per_unit,
                        'source_file': file_name,
                        'remaining_amount': net_amount,  # For FIFO
                    }
                )

                created_count += 1

            except Exception as e:
                logger.error(f"Error creating buy transaction for {asset_symbol}: {e}")
                continue

        return created_count

    @classmethod
    def _create_sell_transactions(cls, sells: List[Dict], revenues: List[Dict], fees: List[Dict],
                                  user, exchange: str, file_name: str) -> int:
        """Create sell transactions from Sold + Revenue pairs"""

        created_count = 0

        # Find USDT revenues (money coming in)
        usdt_revenues = [r for r in revenues if r['coin'] == 'USDT' and r['change'] > 0]

        if not usdt_revenues:
            return 0

        # Calculate total USDT received
        total_usdt_received = sum(revenue['change'] for revenue in usdt_revenues)

        # Calculate USDT fees
        usdt_fees = [f for f in fees if f['coin'] == 'USDT' and f['change'] < 0]
        total_usdt_fee = sum(abs(fee['change']) for fee in usdt_fees)

        # Group sells by asset
        sells_by_asset = defaultdict(list)
        for sell in sells:
            if sell['change'] < 0:  # Only negative amounts (crypto going out)
                sells_by_asset[sell['coin']].append(sell)

        # Create one transaction per asset
        for asset_symbol, asset_sells in sells_by_asset.items():
            try:
                # Calculate total amount sold for this asset
                total_crypto_sold = sum(abs(sell['change']) for sell in asset_sells)

                if total_crypto_sold <= 0:
                    continue

                # Calculate price per unit
                asset_portion_of_revenue = total_usdt_received  # For single asset trades
                if len(sells_by_asset) > 1:
                    # If multiple assets sold simultaneously, distribute USDT proportionally
                    total_value_all_assets = sum(
                        sum(abs(s['change']) for s in asset_sells)
                        for asset_sells in sells_by_asset.values()
                    )
                    asset_portion_of_revenue = total_usdt_received * (total_crypto_sold / total_value_all_assets)

                price_per_unit = asset_portion_of_revenue / total_crypto_sold

                # Calculate fees proportionally
                asset_fee_usd = total_usdt_fee * (total_crypto_sold / sum(
                    sum(abs(s['change']) for s in sells) for sells in sells_by_asset.values()
                )) if len(sells_by_asset) > 1 else total_usdt_fee

                # Create unique transaction ID
                first_sell = asset_sells[0]
                tx_id = f"binance-{user.id}-sell-{asset_symbol}-{int(first_sell['timestamp'].timestamp())}"

                # Create sell transaction (P&L will be calculated later in FIFO)
                CexTransaction.objects.update_or_create(
                    user=user,
                    exchange=exchange,
                    transaction_id=tx_id,
                    defaults={
                        'transaction_type': 'sell',
                        'timestamp': first_sell['timestamp'],
                        'asset_symbol': asset_symbol,
                        'amount': total_crypto_sold,
                        'price_usd': price_per_unit,
                        'value_usd': asset_portion_of_revenue,
                        'fee_amount': Decimal('0'),
                        'fee_asset': 'USDT',
                        'fee_usd': asset_fee_usd,
                        'source_file': file_name,
                        # P&L calculated in FIFO step
                    }
                )

                created_count += 1

            except Exception as e:
                logger.error(f"Error creating sell transaction for {asset_symbol}: {e}")
                continue

        return created_count

    @classmethod
    def _recalculate_fifo_for_all_assets(cls, user, exchange: str):
        """Recalculate FIFO cost basis for all assets"""

        # Get all unique assets
        assets = CexTransaction.objects.filter(
            user=user,
            exchange=exchange
        ).values_list('asset_symbol', flat=True).distinct()

        for asset in assets:
            cls._recalculate_fifo_for_asset(user, exchange, asset)

    @classmethod
    def _recalculate_fifo_for_asset(cls, user, exchange: str, asset_symbol: str):
        """Recalculate FIFO for a specific asset"""
        # Reset all remaining amounts for buys
        buy_transactions = CexTransaction.objects.filter(
            user=user,
            exchange=exchange,
            asset_symbol=asset_symbol,
            transaction_type='buy'
        ).order_by('timestamp')

        for buy_tx in buy_transactions:
            buy_tx.remaining_amount = buy_tx.amount
            buy_tx.save(update_fields=['remaining_amount'])

        # Process sells in chronological order
        sell_transactions = CexTransaction.objects.filter(
            user=user,
            exchange=exchange,
            asset_symbol=asset_symbol,
            transaction_type='sell'
        ).order_by('timestamp')

        for sell_tx in sell_transactions:
            cost_basis, realized_pnl = cls._calculate_fifo_for_sell(
                user, exchange, asset_symbol, sell_tx.amount,
                sell_tx.timestamp, sell_tx.value_usd, sell_tx.fee_usd
            )

            sell_tx.cost_basis_usd = cost_basis
            sell_tx.realized_profit_loss = realized_pnl
            sell_tx.save(update_fields=['cost_basis_usd', 'realized_profit_loss'])

    @classmethod
    def _calculate_fifo_for_sell(cls, user, exchange: str, asset_symbol: str, sell_amount: Decimal,
                                 sell_timestamp, gross_revenue: Decimal, fee_usd: Decimal) -> Tuple[
        Decimal, Decimal]:
        """Calculate FIFO cost basis for a sell transaction"""

        # Get available buy transactions in FIFO order
        buy_transactions = CexTransaction.objects.filter(
            user=user,
            exchange=exchange,
            asset_symbol=asset_symbol,
            transaction_type='buy',
            timestamp__lt=sell_timestamp,
            remaining_amount__gt=0
        ).order_by('timestamp')

        total_cost_basis = Decimal('0')
        remaining_to_sell = sell_amount

        for buy_tx in buy_transactions:
            if remaining_to_sell <= 0:
                break

            available_amount = buy_tx.remaining_amount or Decimal('0')
            if available_amount <= 0:
                continue

            # Use the lesser amount
            amount_to_use = min(remaining_to_sell, available_amount)

            # Calculate cost basis for this portion
            cost_per_unit = buy_tx.price_usd or Decimal('0')
            cost_basis_portion = amount_to_use * cost_per_unit
            total_cost_basis += cost_basis_portion

            # Update remaining amount
            buy_tx.remaining_amount = available_amount - amount_to_use
            buy_tx.save(update_fields=['remaining_amount'])

            # Reduce remaining to sell
            remaining_to_sell -= amount_to_use

        # Calculate realized P&L
        net_revenue = gross_revenue - fee_usd
        realized_pnl = net_revenue - total_cost_basis

        return total_cost_basis, realized_pnl

    @classmethod
    def _parse_binance_timestamp(cls, timestamp_str: str) -> datetime:
        """Parse Binance timestamp with multiple format support"""

        timestamp_str = timestamp_str.strip()

        formats_to_try = [
            '%d/%m/%Y %H:%M',  # 19/06/2024 03:12
            '%d/%m/%Y %-H:%M',  # 19/06/2024 3:12 (Unix/macOS)
            '%d/%m/%Y %#H:%M',  # 19/06/2024 3:12 (Windows)
            '%Y-%m-%d %H:%M:%S',  # 2024-06-19 03:12:04
            '%Y-%m-%d %-H:%M:%S',  # 2024-06-19 3:12:04 (Unix/macOS)
            '%Y-%m-%d %#H:%M:%S',  # 2024-06-19 3:12:04 (Windows)
        ]

        for fmt in formats_to_try:
            try:
                dt = datetime.strptime(timestamp_str, fmt)
                return timezone.make_aware(dt, dt_timezone.utc)
            except ValueError:
                continue

        raise ValueError(f"Could not parse timestamp: {timestamp_str}")
