#!/usr/bin/env python3
import os
import sys
import django
from datetime import datetime, timedelta

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.models import Transaction, Wallet

# Clear SPL cache and force fresh sync
wallet = Wallet.objects.filter(address='DDYBCBCLadcSYnmrSqCznE7haZWoEKf9w8qfQ74WMMri').first()
if wallet:
    print(f"Found wallet: {wallet.address}")

    # Delete all transactions for this wallet
    deleted_count = Transaction.objects.filter(wallet=wallet).delete()[0]
    print(f"Deleted {deleted_count} transactions")

    # Set last_updated to force fresh sync
    wallet.last_updated = datetime.now() - timedelta(hours=24)
    wallet.save()
    print(f"Set last_updated to {wallet.last_updated} to force fresh sync")

    print("Cache cleared successfully. Wallet will sync fresh data on next request.")
else:
    print("Wallet not found")