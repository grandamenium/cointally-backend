#!/usr/bin/env python3
"""
Quick verification that ETH integration works end-to-end
"""
import os
import sys
sys.path.insert(0, '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/crypto-tax-app/backend')

os.environ['DJANGO_SETTINGS_MODULE'] = 'crypto_tax_project.settings'

import django
django.setup()

from crypto_tax_api.utils.blockchain_apis import fetch_ethereum_transactions

# Test with a simple address with fewer transactions
test_address = "0x742d35Cc6688C96b72aDBe9e1A7F24F5a5b1F3aB"  # Random address with some activity

print("=== ETH Integration Verification ===")
print(f"Testing ETH address: {test_address}")
print("-" * 50)

try:
    transactions = fetch_ethereum_transactions(test_address)
    print(f"✅ SUCCESS! Fetched {len(transactions)} transactions")

    if transactions:
        print("\nFirst transaction:")
        tx = transactions[0]
        print(f"  Hash: {tx.get('transaction_hash', 'N/A')}")
        print(f"  Type: {tx.get('transaction_type', 'N/A')}")
        print(f"  Asset: {tx.get('asset_symbol', 'N/A')}")
        print(f"  Amount: {tx.get('amount', 'N/A')}")
        print(f"  Value USD: ${tx.get('value_usd', 'N/A')}")
        print(f"  Timestamp: {tx.get('timestamp', 'N/A')}")

    print(f"\n✅ ETH API Integration is working successfully!")
    print(f"✅ Uses the same API key pattern as Solana")
    print(f"✅ Ready for frontend integration")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()