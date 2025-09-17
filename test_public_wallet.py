#!/usr/bin/env python3
"""
Test script for publicly available Arbitrum wallet address
Source: https://arbiscan.io/address/0xda5e1988097297dcdc1f90d4dfe7909e847cbef6
"""
import sys
import os

# Add the Django project to the path
sys.path.append('.')

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')

import django
django.setup()

from crypto_tax_api.utils.blockchain_apis import fetch_arbitrum_transactions

def test_public_wallet():
    """Test with publicly available wallet that has known transactions"""

    # Address found on Arbiscan with recent activity
    address = '0xdA5e1988097297dcdc1f90d4dfe7909e847CBeF6'

    print("=" * 70)
    print("Testing Arbitrum API with Publicly Available Wallet")
    print("=" * 70)
    print(f"Address: {address}")
    print("Source: https://arbiscan.io/address/0xda5e1988097297dcdc1f90d4dfe7909e847cbef6")
    print("Known Holdings: USDC ($1,074), ETH (0.025), Recent approve transactions")
    print("=" * 70)

    try:
        print("\nCalling fetch_arbitrum_transactions()...")
        transactions = fetch_arbitrum_transactions(address)

        print(f"\n✅ SUCCESS: Found {len(transactions)} transactions")

        if transactions:
            print(f"\nFirst {min(5, len(transactions))} transactions:")
            for i, tx in enumerate(transactions[:5]):
                print(f"\nTransaction {i+1}:")
                print(f"  Hash: {tx.get('transaction_hash', 'N/A')}")
                print(f"  Timestamp: {tx.get('timestamp', 'N/A')}")
                print(f"  Type: {tx.get('transaction_type', 'N/A')}")
                print(f"  Asset: {tx.get('asset_symbol', 'N/A')}")
                print(f"  Amount: {tx.get('amount', 'N/A')}")
                print(f"  Value USD: ${tx.get('value_usd', 'N/A')}")
                print(f"  Fee USD: ${tx.get('fee_usd', 'N/A')}")

            # Look for specific token types
            assets = set(tx.get('asset_symbol', 'Unknown') for tx in transactions)
            print(f"\nAssets found: {', '.join(sorted(assets))}")

            # Check for USDC transactions (known to exist)
            usdc_txs = [tx for tx in transactions if tx.get('asset_symbol') == 'USDC']
            print(f"USDC transactions: {len(usdc_txs)}")

            if usdc_txs:
                print("✅ VALIDATION: Found USDC transactions as expected!")

        else:
            print("⚠️ No transactions found - this might indicate an API issue")

        return len(transactions) > 0

    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_public_wallet()
    print("\n" + "=" * 70)
    if success:
        print("✅ Test completed successfully - API is working with real data!")
    else:
        print("❌ Test failed - check API configuration")
    print("=" * 70)