# tax_calculation_service.py
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Q
from django.utils import timezone

from crypto_tax_api.models import Transaction, CexTransaction, TransactionFee

logger = logging.getLogger(__name__)


class TaxCalculationService:
    """Service for calculating taxes across all sources (DEX + CEX)"""

    # @classmethod
    # def generate_form_8949(cls, user, tax_year):
    #     """Generate IRS Form 8949 data for a user"""
    #     from django.utils import timezone
    #     from datetime import datetime, timedelta, timezone as ts_c
    #     from decimal import Decimal
    #
    #     # Determine date range for tax year
    #     start_date = datetime(int(tax_year), 1, 1, tzinfo=ts_c.utc)
    #     end_date = datetime(int(tax_year), 12, 31, 23, 59, 59, tzinfo=ts_c.utc)
    #
    #     # Get all wallets for the user
    #     wallet_addresses = user.wallet_addresses or []
    #
    #     # Get DEX sell transactions with realized P&L
    #     dex_sells = Transaction.objects.filter(
    #         wallet__address__in=wallet_addresses,
    #         transaction_type='sell',
    #         timestamp__gte=start_date,
    #         timestamp__lte=end_date,
    #         realized_profit_loss__isnull=False
    #     ).order_by('timestamp')
    #
    #     # Get CEX sell transactions with realized P&L
    #     cex_sells = CexTransaction.objects.filter(
    #         user=user,
    #         transaction_type='sell',
    #         timestamp__gte=start_date,
    #         timestamp__lte=end_date,
    #         realized_profit_loss__isnull=False
    #     ).order_by('timestamp')
    #
    #     short_term_transactions = []
    #     long_term_transactions = []
    #
    #     # Process DEX transactions
    #     for tx in dex_sells:
    #         acquisition_date = cls._get_acquisition_date_dex(tx, user)
    #         if acquisition_date:
    #             holding_period = (tx.timestamp.date() - acquisition_date).days
    #             is_short_term = holding_period <= 365
    #
    #             transaction_data = {
    #                 'description': f"{tx.asset_symbol} ({tx.transaction_hash[:8]}...)",
    #                 'date_acquired': acquisition_date,
    #                 'date_sold': tx.timestamp.date(),
    #                 'proceeds': tx.value_usd or Decimal('0'),
    #                 'cost_basis': tx.cost_basis_usd or Decimal('0'),
    #                 'gain_or_loss': tx.realized_profit_loss or Decimal('0'),
    #                 'is_short_term': is_short_term,
    #                 'source': 'DEX',
    #                 'transaction_id': tx.transaction_hash
    #             }
    #
    #             if is_short_term:
    #                 short_term_transactions.append(transaction_data)
    #             else:
    #                 long_term_transactions.append(transaction_data)
    #
    #     # Process CEX transactions
    #     for tx in cex_sells:
    #         acquisition_date = cls._get_acquisition_date_cex(tx, user)
    #         if acquisition_date:
    #             holding_period = (tx.timestamp.date() - acquisition_date).days
    #             is_short_term = holding_period <= 365
    #
    #             transaction_data = {
    #                 'description': f"{tx.asset_symbol} ({tx.exchange})",
    #                 'date_acquired': acquisition_date,
    #                 'date_sold': tx.timestamp.date(),
    #                 'proceeds': tx.value_usd or Decimal('0'),
    #                 'cost_basis': tx.cost_basis_usd or Decimal('0'),
    #                 'gain_or_loss': tx.realized_profit_loss or Decimal('0'),
    #                 'is_short_term': is_short_term,
    #                 'source': 'CEX',
    #                 'transaction_id': tx.transaction_id
    #             }
    #
    #             if is_short_term:
    #                 short_term_transactions.append(transaction_data)
    #             else:
    #                 long_term_transactions.append(transaction_data)
    #
    #     # Calculate totals
    #     short_term_total = sum(tx['gain_or_loss'] for tx in short_term_transactions)
    #     long_term_total = sum(tx['gain_or_loss'] for tx in long_term_transactions)
    #     total_gain_or_loss = short_term_total + long_term_total
    #
    #     return {
    #         'tax_year': tax_year,
    #         'short_term_transactions': short_term_transactions,
    #         'long_term_transactions': long_term_transactions,
    #         'short_term_total': short_term_total,
    #         'long_term_total': long_term_total,
    #         'total_gain_or_loss': total_gain_or_loss
    #     }

    @staticmethod
    def generate_form_8949(user, tax_year):
        """Generate Form 8949 with proper fee treatment for IRS compliance"""

        # Date range for tax year
        start_date = datetime(tax_year, 1, 1).date()
        end_date = datetime(tax_year, 12, 31).date()

        short_term_entries = []
        long_term_entries = []

        # Process CEX transactions
        cex_sells = CexTransaction.objects.filter(
            user=user,
            transaction_type='sell',
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date,
            realized_profit_loss__isnull=False
        ).order_by('timestamp').prefetch_related('fees')

        for sell_tx in cex_sells:
            try:
                entries = TaxCalculationService._process_cex_sell_for_8949(sell_tx)
                for entry in entries:
                    if entry['is_short_term']:
                        short_term_entries.append(entry)
                    else:
                        long_term_entries.append(entry)
            except Exception as e:
                logger.error(f"Error processing CEX sell {sell_tx.id}: {e}")

        # Calculate totals
        short_term_total = sum(entry['gain_or_loss'] for entry in short_term_entries)
        long_term_total = sum(entry['gain_or_loss'] for entry in long_term_entries)

        return {
            'tax_year': tax_year,
            'short_term_transactions': short_term_entries,
            'long_term_transactions': long_term_entries,
            'short_term_total': short_term_total,
            'long_term_total': long_term_total,
            'total_gain_or_loss': short_term_total + long_term_total,
            'fee_summary': TaxCalculationService._generate_fee_summary(user, start_date, end_date)
        }

    @staticmethod
    def _process_cex_sell_for_8949(sell_tx):
        """Process CEX sell transaction for Form 8949"""

        # Calculate holding period (simplified - assumes 1 year for now)
        holding_period_days = 365  # You would calculate this from actual buy dates
        is_short_term = holding_period_days <= 365

        # Get selling fees
        selling_fees = sell_tx.fees.filter(is_tax_deductible=True).aggregate(
            total=Sum('fee_usd_value')
        )['total'] or Decimal('0.00')

        # Net proceeds after fees
        net_proceeds = sell_tx.value_usd - selling_fees

        return [{
            'description': f"{sell_tx.amount} {sell_tx.asset_symbol}",
            'date_acquired': sell_tx.timestamp.date() - timedelta(days=holding_period_days),
            'date_sold': sell_tx.timestamp.date(),
            'proceeds': float(net_proceeds),
            'cost_basis': float(sell_tx.cost_basis_usd or 0),
            'gain_or_loss': float(sell_tx.realized_profit_loss or 0),
            'is_short_term': is_short_term,
            'source': 'CEX',
            'transaction_id': sell_tx.transaction_id,
            'fees_included_in_basis': float(selling_fees)
        }]

    @staticmethod
    def _generate_fee_summary(user, start_date, end_date):
        """Generate comprehensive fee summary for tax reporting"""

        # Get all fees for the period
        all_fees = TransactionFee.objects.filter(
            Q(cex_transaction__user=user),
            timestamp__date__gte=start_date,
            timestamp__date__lte=end_date,
            is_tax_deductible=True
        ).values('fee_type').annotate(
            total_usd=Sum('fee_usd_value'),
            count=Count('id')
        )

        total_deductible_fees = sum(fee['total_usd'] for fee in all_fees)

        return {
            'total_deductible_fees': float(total_deductible_fees),
            'fees_by_type': {fee['fee_type']: float(fee['total_usd']) for fee in all_fees},
            'fee_count': sum(fee['count'] for fee in all_fees)
        }

    @classmethod
    def _get_acquisition_date_dex(cls, sell_tx, user):
        """Get acquisition date for DEX transaction using FIFO"""
        wallet_addresses = user.wallet_addresses or []

        # Get buy transactions for this asset before the sell date
        buy_txs = Transaction.objects.filter(
            wallet__address__in=wallet_addresses,
            asset_symbol=sell_tx.asset_symbol,
            transaction_type='buy',
            timestamp__lt=sell_tx.timestamp
        ).order_by('timestamp')

        if buy_txs.exists():
            # Find the specific buy transaction(s) that contributed to this sell
            # This is a simplified FIFO implementation
            remaining_sell_amount = sell_tx.amount

            for buy_tx in buy_txs:
                if remaining_sell_amount <= 0:
                    break

                # In a full implementation, you'd track remaining amounts
                # For now, return the first buy transaction date
                return buy_tx.timestamp.date()

        # If no buy found, estimate (this shouldn't happen in a proper system)
        return (sell_tx.timestamp - timedelta(days=365)).date()

    @classmethod
    def generate_form_8949_pdf(cls, user, tax_year):
        """Generate PDF version of Form 8949"""
        from reportlab.lib.pagesizes import letter
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from io import BytesIO

        # Get form data
        form_data = cls.generate_form_8949(user, tax_year)

        # Create PDF buffer
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)

        # Container for the 'Flowable' objects
        elements = []
        styles = getSampleStyleSheet()

        # Title
        title = Paragraph(f"<b>IRS Form 8949 - {tax_year}</b><br/>Sales and Other Dispositions of Capital Assets",
                          styles['Title'])
        elements.append(title)
        elements.append(Spacer(1, 20))

        # Taxpayer info (you'd fill this from user data)
        taxpayer_info = Paragraph(
            f"<b>Taxpayer:</b> {user.username}<br/><b>Generated:</b> {timezone.now().strftime('%Y-%m-%d')}",
            styles['Normal'])
        elements.append(taxpayer_info)
        elements.append(Spacer(1, 20))

        # Short-term transactions
        if form_data['short_term_transactions']:
            elements.append(
                Paragraph("<b>Part I - Short-Term Capital Gains and Losses (Assets held one year or less)</b>",
                          styles['Heading2']))
            elements.append(Spacer(1, 10))

            # Create table data
            table_data = [
                ['Description', 'Date Acquired', 'Date Sold', 'Proceeds', 'Cost Basis', 'Gain/Loss']
            ]

            for tx in form_data['short_term_transactions']:
                table_data.append([
                    tx['description'],
                    tx['date_acquired'].strftime('%m/%d/%Y'),
                    tx['date_sold'].strftime('%m/%d/%Y'),
                    f"${tx['proceeds']:,.2f}",
                    f"${tx['cost_basis']:,.2f}",
                    f"${tx['gain_or_loss']:,.2f}"
                ])

            # Add total row
            table_data.append([
                'TOTAL', '', '', '', '', f"${form_data['short_term_total']:,.2f}"
            ])

            # Create table
            table = Table(table_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))

        # Long-term transactions
        if form_data['long_term_transactions']:
            elements.append(
                Paragraph("<b>Part II - Long-Term Capital Gains and Losses (Assets held more than one year)</b>",
                          styles['Heading2']))
            elements.append(Spacer(1, 10))

            # Create table data
            table_data = [
                ['Description', 'Date Acquired', 'Date Sold', 'Proceeds', 'Cost Basis', 'Gain/Loss']
            ]

            for tx in form_data['long_term_transactions']:
                table_data.append([
                    tx['description'],
                    tx['date_acquired'].strftime('%m/%d/%Y'),
                    tx['date_sold'].strftime('%m/%d/%Y'),
                    f"${tx['proceeds']:,.2f}",
                    f"${tx['cost_basis']:,.2f}",
                    f"${tx['gain_or_loss']:,.2f}"
                ])

            # Add total row
            table_data.append([
                'TOTAL', '', '', '', '', f"${form_data['long_term_total']:,.2f}"
            ])

            # Create table
            table = Table(table_data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTSIZE', (0, 1), (-1, -1), 8),
            ]))

            elements.append(table)
            elements.append(Spacer(1, 20))

        # Summary
        summary = Paragraph(
            f"<b>SUMMARY</b><br/>Short-term total: ${form_data['short_term_total']:,.2f}<br/>Long-term total: ${form_data['long_term_total']:,.2f}<br/><b>Net Capital Gain/Loss: ${form_data['total_gain_or_loss']:,.2f}</b>",
            styles['Normal'])
        elements.append(summary)

        # Build PDF
        doc.build(elements)
        buffer.seek(0)

        return buffer

    @classmethod
    def _get_acquisition_date_cex(cls, sell_tx, user):
        """Get acquisition date for CEX transaction using FIFO"""
        # Get buy transactions for this asset before the sell date
        buy_txs = CexTransaction.objects.filter(
            user=user,
            exchange=sell_tx.exchange,
            asset_symbol=sell_tx.asset_symbol,
            transaction_type__in=['buy', 'deposit'],
            timestamp__lt=sell_tx.timestamp
        ).order_by('timestamp')

        if buy_txs.exists():
            # Find the specific buy transaction(s) that contributed to this sell
            # This is a simplified FIFO implementation
            remaining_sell_amount = sell_tx.amount

            for buy_tx in buy_txs:
                if remaining_sell_amount <= 0:
                    break

                # Check if this buy transaction has remaining amount
                if hasattr(buy_tx, 'remaining_amount') and buy_tx.remaining_amount > 0:
                    return buy_tx.timestamp.date()
                elif not hasattr(buy_tx, 'remaining_amount'):
                    # First buy transaction
                    return buy_tx.timestamp.date()

        # If no buy found, estimate (this shouldn't happen in a proper system)
        return (sell_tx.timestamp - timedelta(days=365)).date()

    @classmethod
    def _estimate_acquisition_date(cls, sell_tx, user, is_cex=False):
        """
        Estimate the acquisition date for a sell transaction

        This is a simplified placeholder. In reality, you would need to implement
        a more sophisticated algorithm that tracks the specific buy transactions
        that correspond to each sell based on your FIFO implementation.
        """
        # This is highly simplified - in a real system, you'd have a more accurate way
        # to determine which buys correspond to which sells
        if is_cex:
            buys = CexTransaction.objects.filter(
                user=user,
                asset_symbol=sell_tx.asset_symbol,
                transaction_type='buy',
                timestamp__lt=sell_tx.timestamp
            ).order_by('timestamp')
        else:
            wallet_addresses = user.wallet_addresses or []
            buys = Transaction.objects.filter(
                wallet__address__in=wallet_addresses,
                asset_symbol=sell_tx.asset_symbol,
                transaction_type='buy',
                timestamp__lt=sell_tx.timestamp
            ).order_by('timestamp')

        if buys.exists():
            # Return the earliest buy date (FIFO)
            return buys.first().timestamp.date()
        else:
            # If no buys found, estimate as 30 days before the sell
            # This is just a placeholder - in reality, you'd need a better solution
            return (sell_tx.timestamp - timezone.timedelta(days=30)).date()
