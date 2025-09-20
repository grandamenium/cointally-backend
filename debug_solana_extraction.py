#!/usr/bin/env python3
import os
import sys
import django

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.utils.blockchain_apis import fetch_solana_transactions
import requests

# Test specific transaction to see what data is being extracted
user_address = "DDYBCBCLadcSYnmrSqCznE7haZWoEKf9w8qfQ74WMMri"

# Get alchemy URL (this mirrors the code in blockchain_apis.py)
api_key = os.getenv('ALCHEMY_SOLANA_API_KEY')
if not api_key:
    print("No ALCHEMY_SOLANA_API_KEY found in environment")
    exit(1)

alchemy_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
print(f"Using Alchemy URL: {alchemy_url}")

try:
    print("Fetching Solana transactions...")
    transactions = fetch_solana_transactions(user_address)

    print(f"Found {len(transactions)} transactions:")

    for i, tx in enumerate(transactions):
        if tx.get('asset_symbol', '').startswith('SPL'):
            print(f"\n--- SPL Transaction {i+1} ---")
            print(f"Hash: {tx.get('transaction_hash', 'N/A')}")
            print(f"Asset: {tx.get('asset_symbol', 'N/A')}")
            print(f"Amount: {tx.get('amount', 'N/A')}")
            print(f"Contract Address: {tx.get('contract_address', 'N/A')}")
            print(f"Token Decimals: {tx.get('token_decimals', 'N/A')}")
            print(f"Price Source: {tx.get('price_source', 'N/A')}")
            print(f"Price Confidence: {tx.get('price_confidence', 'N/A')}")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()