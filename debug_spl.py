#!/usr/bin/env python3
import os
import sys
import django

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.models import Transaction, Wallet

# Check SPL transactions
wallet = Wallet.objects.filter(address='DDYBCBCLadcSYnmrSqCznE7haZWoEKf9w8qfQ74WMMri').first()
if wallet:
    print(f"Wallet last sync: {wallet.last_updated}")
    spl_txs = Transaction.objects.filter(wallet=wallet, asset_symbol__startswith='SPL')
    print(f"SPL transactions: {spl_txs.count()}")

    for tx in spl_txs[:5]:
        print(f"- {tx.transaction_hash[:20]}...: {tx.asset_symbol} {tx.amount} @ {tx.timestamp}")

    # Check if we have any contract_address data
    contract_txs = Transaction.objects.filter(wallet=wallet).exclude(contract_address__isnull=True).exclude(contract_address='')
    print(f"Transactions with contract_address: {contract_txs.count()}")

    for tx in contract_txs[:5]:
        print(f"- Contract: {tx.contract_address} | Symbol: {tx.asset_symbol}")
else:
    print("Wallet not found")