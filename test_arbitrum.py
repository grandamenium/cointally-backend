#!/usr/bin/env python3
"""
Test script for Arbitrum transactions using the updated implementation
"""
import os
import sys
import json
from decimal import Decimal
from datetime import datetime, timezone

# Add the Django project to the path
sys.path.append('/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/crypto-tax-app/backend')

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_api.settings')

import django
django.setup()

from crypto_tax_api.utils.blockchain_apis import fetch_arbitrum_transactions, get_alchemy_api_key

def test_arbitrum_api():
    """Test Arbitrum API connectivity and key management"""
    print("=== Testing Arbitrum API ===")

    # Test API key retrieval
    api_key = get_alchemy_api_key('ALCHEMY_ARBITRUM_API_KEY')
    print(f"API Key retrieved: {api_key[:10]}..." if api_key else "No API key found")

    # Test the endpoint URL construction
    from crypto_tax_api.utils.blockchain_apis import ALCHEMY_ENDPOINTS
    endpoint = ALCHEMY_ENDPOINTS['arbitrum'].format(api_key=api_key)
    print(f"Endpoint: {endpoint[:50]}...")

    return api_key is not None

def test_arbitrum_transactions(address):
    """Test fetching Arbitrum transactions for the provided address"""
    print(f"\n=== Testing Arbitrum Transactions for {address} ===")

    try:
        transactions = fetch_arbitrum_transactions(address)

        print(f"Found {len(transactions)} transactions")

        if transactions:
            print("\nFirst few transactions:")
            for i, tx in enumerate(transactions[:3]):
                print(f"\nTransaction {i+1}:")
                print(f"  Hash: {tx['transaction_hash']}")
                print(f"  Timestamp: {tx['timestamp']}")
                print(f"  Type: {tx['transaction_type']}")
                print(f"  Asset: {tx['asset_symbol']}")
                print(f"  Amount: {tx['amount']}")
                print(f"  Price USD: ${tx['price_usd']}")
                print(f"  Value USD: ${tx['value_usd']}")
                print(f"  Fee USD: ${tx['fee_usd']}")

        # Look for ARB token transactions specifically
        arb_transactions = [tx for tx in transactions if tx['asset_symbol'] == 'ARB']
        print(f"\nFound {len(arb_transactions)} ARB token transactions")

        if arb_transactions:
            print("\nARB transactions:")
            for tx in arb_transactions:
                print(f"  {tx['timestamp']}: {tx['transaction_type']} {tx['amount']} ARB (${tx['value_usd']})")

        return transactions

    except Exception as e:
        print(f"Error testing Arbitrum transactions: {str(e)}")
        import traceback
        traceback.print_exc()
        return []

def test_manual_api_call(address):
    """Make a manual API call to Arbitrum endpoint for verification"""
    print(f"\n=== Manual API Call Test ===")

    import requests

    api_key = get_alchemy_api_key('ALCHEMY_ARBITRUM_API_KEY')
    if not api_key:
        print("No API key available for manual test")
        return

    alchemy_url = f"https://arb-mainnet.g.alchemy.com/v2/{api_key}"

    # Test basic API connectivity
    test_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "toAddress": address.lower(),
                "category": ["external", "erc20"],
                "maxCount": "0x5"  # Just get 5 transactions for testing
            }
        ]
    }

    try:
        response = requests.post(alchemy_url, json=test_payload, timeout=10)
        print(f"Response status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print("API call successful!")

            if 'error' in data:
                print(f"API Error: {data['error']}")
            elif 'result' in data:
                transfers = data['result'].get('transfers', [])
                print(f"Found {len(transfers)} transfers in manual test")

                if transfers:
                    print("\nSample transfer:")
                    sample = transfers[0]
                    print(json.dumps(sample, indent=2))
        else:
            print(f"API call failed: {response.text}")

    except Exception as e:
        print(f"Manual API call error: {str(e)}")

if __name__ == "__main__":
    # Test address provided by user
    test_address = "0xc9C9fafcE2AF75CF2924de3DFef8Eb8f50BC77b2"

    print("Starting Arbitrum Integration Test")
    print(f"Test Address: {test_address}")
    print(f"Expected Transaction: +1.95 ARB on Sep 16, 2025 (~$0.99)")

    # Test API setup
    if not test_arbitrum_api():
        print("API setup test failed, but continuing with fallback...")

    # Test manual API call
    test_manual_api_call(test_address)

    # Test full transaction fetching
    transactions = test_arbitrum_transactions(test_address)

    print(f"\n=== Test Summary ===")
    print(f"Total transactions found: {len(transactions)}")

    # Check for expected transaction around Sep 16, 2025
    if transactions:
        sep_2025_txs = [
            tx for tx in transactions
            if tx['timestamp'].year == 2025 and tx['timestamp'].month == 9
        ]
        print(f"Transactions in September 2025: {len(sep_2025_txs)}")

        if sep_2025_txs:
            for tx in sep_2025_txs:
                print(f"  {tx['timestamp']}: {tx['transaction_type']} {tx['amount']} {tx['asset_symbol']} (${tx['value_usd']})")