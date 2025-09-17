"""
Utility functions for calculating cost basis, realized gains, and generating tax forms
"""
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Q, Sum

logger = logging.getLogger(__name__)


def calculate_cost_basis_fifo(wallet, asset_symbol, sell_amount, sell_date):
    """
    Calculate cost basis using FIFO (First In, First Out) method

    Args:
        wallet: Wallet object
        asset_symbol: Symbol of the asset being sold
        sell_amount: Amount of the asset being sold
        sell_date: Date of the sale

    Returns:
        tuple: (cost_basis, realized_profit_loss) or raises ValueError for invalid scenarios
    """
    from ..models import Transaction
    from decimal import Decimal
    import logging
    from django.db.models import Sum

    logger = logging.getLogger(__name__)

    # Get all buy transactions for this asset, ordered by date (oldest first)
    buy_transactions = Transaction.objects.filter(
        wallet=wallet,
        asset_symbol=asset_symbol,
        transaction_type__in=['buy', 'swap'],
        timestamp__lt=sell_date
    ).order_by('timestamp')

    remaining_sell_amount = Decimal(str(sell_amount))
    total_cost_basis = Decimal('0.00')

    # If no buy transactions found, raise an exception - this is an invalid state in real applications
    if not buy_transactions.exists():
        logger.error(f"No buy transactions found for {wallet} {asset_symbol} - cannot calculate cost basis")
        raise ValueError(f"No prior purchase records found for {asset_symbol}. Cannot calculate cost basis.")

    # Process each buy transaction until we've covered the sell amount
    for tx in buy_transactions:
        if remaining_sell_amount <= 0:
            break

        # Check if this buy transaction has already been used for prior sells
        used_in_sells = Transaction.objects.filter(
            wallet=wallet,
            asset_symbol=asset_symbol,
            transaction_type='sell',
            timestamp__gt=tx.timestamp,
            timestamp__lt=sell_date
        ).aggregate(total=Sum('amount', default=0))['total'] or Decimal('0.00')

        # Calculate remaining amount in this buy that can be used
        available_amount = tx.amount - used_in_sells

        if available_amount <= 0:
            # This buy has been completely used in previous sells
            continue

        # Calculate how much of this buy we'll use for the current sell
        use_amount = min(remaining_sell_amount, available_amount)

        # Calculate portion of cost basis from this buy
        cost_basis_portion = (use_amount / tx.amount) * tx.value_usd
        total_cost_basis += cost_basis_portion

        # Reduce remaining sell amount
        remaining_sell_amount -= use_amount

    # If we couldn't find enough buys to cover the sell, this is a problem in a real app
    if remaining_sell_amount > 0:
        logger.error(f"Insufficient buy transactions to cover sell of {sell_amount} {asset_symbol} for {wallet}")
        raise ValueError(f"Insufficient purchase records to cover the sale of {sell_amount} {asset_symbol}. " +
                         f"Missing records for {remaining_sell_amount} {asset_symbol}.")

    # Calculate sell value and profit/loss
    from .blockchain_apis import fetch_price_data
    current_price = fetch_price_data(asset_symbol)

    # Calculate sell value based on covered amount
    sell_value = (sell_amount - remaining_sell_amount) * current_price

    # Calculate realized profit/loss
    realized_profit_loss = sell_value - total_cost_basis

    return total_cost_basis, realized_profit_loss


def calculate_realized_gains(wallet, start_date=None, end_date=None):
    """
    Calculate total realized gains for a wallet within a date range

    Args:
        wallet: Wallet object
        start_date: Optional start date
        end_date: Optional end date

    Returns:
        Decimal: Total realized gains/losses
    """
    from ..models import Transaction

    # Get all sell transactions with calculated profit/loss
    query = Q(wallet=wallet, realized_profit_loss__isnull=False)

    if start_date:
        query &= Q(timestamp__date__gte=start_date)

    if end_date:
        query &= Q(timestamp__date__lte=end_date)

    total_realized_gain = Transaction.objects.filter(query).aggregate(
        total=Sum('realized_profit_loss', default=0)
    )['total'] or Decimal('0.00')

    return total_realized_gain

def generate_tax_summary(wallet, transactions, start_date, end_date):
    """
    Generate a tax summary for a wallet within a date range

    Args:
        wallet: Wallet object
        transactions: QuerySet of transactions
        start_date: Start date
        end_date: End date

    Returns:
        dict: Summary data
    """
    from django.db.models import Sum

    # Filter transactions to sells with realized gain/loss
    sell_transactions = transactions.filter(
        transaction_type='sell',
        realized_profit_loss__isnull=False
    )

    # Calculate totals
    total_proceeds = sell_transactions.aggregate(
        total=Sum('value_usd', default=0)
    )['total'] or Decimal('0.00')

    total_cost_basis = sell_transactions.aggregate(
        total=Sum('cost_basis_usd', default=0)
    )['total'] or Decimal('0.00')

    total_realized_gain_loss = sell_transactions.aggregate(
        total=Sum('realized_profit_loss', default=0)
    )['total'] or Decimal('0.00')

    total_fees = transactions.aggregate(
        total=Sum('fee_usd', default=0)
    )['total'] or Decimal('0.00')

    # Calculate short-term vs long-term gains
    short_term_gain_loss = Decimal('0.00')
    long_term_gain_loss = Decimal('0.00')

    for tx in sell_transactions:
        # Get the buys that were used for this sell (based on FIFO)
        buy_txs = get_buys_for_sell(wallet, tx)

        for buy_tx, amount_used in buy_txs:
            # Calculate holding period
            holding_period = (tx.timestamp.date() - buy_tx.timestamp.date()).days

            # Calculate portion of gain/loss from this buy
            portion_of_total = amount_used / tx.amount
            gain_portion = portion_of_total * tx.realized_profit_loss

            # Add to short-term or long-term based on holding period
            if holding_period <= 365:
                short_term_gain_loss += gain_portion
            else:
                long_term_gain_loss += gain_portion

    return {
        'total_proceeds': total_proceeds,
        'total_cost_basis': total_cost_basis,
        'total_realized_gain_loss': total_realized_gain_loss,
        'short_term_gain_loss': short_term_gain_loss,
        'long_term_gain_loss': long_term_gain_loss,
        'total_fees': total_fees
    }

def get_buys_for_sell(wallet, sell_transaction):
    """
    Get the buy transactions that were used for a sell, based on FIFO

    Args:
        wallet: Wallet object
        sell_transaction: Sell transaction

    Returns:
        list: List of tuples (buy_transaction, amount_used)
    """
    from ..models import Transaction

    asset_symbol = sell_transaction.asset_symbol
    sell_amount = sell_transaction.amount
    sell_date = sell_transaction.timestamp

    # Get all buy transactions for this asset before the sell date
    buy_transactions = Transaction.objects.filter(
        wallet=wallet,
        asset_symbol=asset_symbol,
        transaction_type__in=['buy', 'swap'],
        timestamp__lt=sell_date
    ).order_by('timestamp')

    if not buy_transactions.exists():
        return []

    remaining_sell_amount = Decimal(str(sell_amount))
    buys_used = []

    # Process each buy transaction until we've covered the sell amount
    for buy_tx in buy_transactions:
        if remaining_sell_amount <= 0:
            break

        # Check if this buy transaction has already been used for prior sells
        used_in_prior_sells = Transaction.objects.filter(
            wallet=wallet,
            asset_symbol=asset_symbol,
            transaction_type='sell',
            timestamp__gt=buy_tx.timestamp,
            timestamp__lt=sell_date
        ).aggregate(total=Sum('amount', default=0))['total'] or Decimal('0.00')

        # Calculate remaining amount in this buy that can be used
        available_amount = buy_tx.amount - used_in_prior_sells

        if available_amount <= 0:
            continue

        # Calculate how much of this buy we'll use for the current sell
        use_amount = min(remaining_sell_amount, available_amount)

        # Add to list of buys used
        buys_used.append((buy_tx, use_amount))

        # Reduce remaining sell amount
        remaining_sell_amount -= use_amount

    return buys_used

def generate_form_8949(wallet, tax_year):
    """
    Generate IRS Form 8949 data for a tax year

    Args:
        wallet: Wallet object
        tax_year: Tax year

    Returns:
        dict: Form 8949 data
    """
    from ..models import Transaction

    # Get date range for tax year
    start_date = datetime(tax_year, 1, 1).date()
    end_date = datetime(tax_year, 12, 31).date()

    # Get all sell transactions in the tax year
    sell_transactions = Transaction.objects.filter(
        wallet=wallet,
        transaction_type='sell',
        timestamp__date__gte=start_date,
        timestamp__date__lte=end_date,
        realized_profit_loss__isnull=False
    ).order_by('timestamp')

    short_term_entries = []
    long_term_entries = []

    for sell_tx in sell_transactions:
        # Get the buys that were used for this sell
        buys_used = get_buys_for_sell(wallet, sell_tx)

        for buy_tx, amount_used in buys_used:
            # Calculate holding period
            holding_period = (sell_tx.timestamp.date() - buy_tx.timestamp.date()).days
            is_short_term = holding_period <= 365

            # Calculate portion of total
            portion = amount_used / sell_tx.amount

            # Calculate proceeds and cost basis for this portion
            proceeds = portion * sell_tx.value_usd
            cost_basis = portion * buy_tx.value_usd
            gain_or_loss = proceeds - cost_basis

            # Create entry
            entry = {
                'description': f"{amount_used} {sell_tx.asset_symbol}",
                'date_acquired': buy_tx.timestamp.date(),
                'date_sold': sell_tx.timestamp.date(),
                'proceeds': proceeds,
                'cost_basis': cost_basis,
                'gain_or_loss': gain_or_loss,
                'is_short_term': is_short_term
            }

            # Add to appropriate list
            if is_short_term:
                short_term_entries.append(entry)
            else:
                long_term_entries.append(entry)

    # Calculate totals
    short_term_total = sum(entry['gain_or_loss'] for entry in short_term_entries)
    long_term_total = sum(entry['gain_or_loss'] for entry in long_term_entries)

    return {
        'tax_year': tax_year,
        'short_term_transactions': short_term_entries,
        'long_term_transactions': long_term_entries,
        'short_term_total': short_term_total,
        'long_term_total': long_term_total,
        'total_gain_or_loss': short_term_total + long_term_total
    }