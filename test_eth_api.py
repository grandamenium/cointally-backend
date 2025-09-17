#!/usr/bin/env python3
import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Test both API keys to see which one works
keys_to_test = [
    ('User Specified', 'dN6yJ1dHDtCc9LIRIC2lDf'),
    ('Working Solana Key', 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9')
]
# Use a well-known Ethereum address with activity (Vitalik's address)
wallet_address = '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045'

print(f"Testing ETH API integration...")
print(f"ETH Wallet: {wallet_address}")
print("=" * 60)

working_api_key = None

for key_name, api_key in keys_to_test:
    print(f"\nTesting {key_name}: {api_key[:8]}...")
    print("-" * 50)

    url = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

    # Test basic API connectivity with alchemy_getAssetTransfers
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "fromAddress": wallet_address,
                "category": ["external", "internal", "erc20"],
                "maxCount": "0x5"  # Limit to 5 for testing
            }
        ]
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )

        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            if 'result' in result and 'transfers' in result['result']:
                transfers = result['result']['transfers']
                print(f"✅ SUCCESS! Found {len(transfers)} transactions")
                working_api_key = api_key
                print("\nSample transactions:")
                for transfer in transfers[:3]:
                    print(f"  - Hash: {transfer.get('hash', 'N/A')[:20]}...")
                    print(f"    Asset: {transfer.get('asset', 'N/A')}")
                    print(f"    Value: {transfer.get('value', 'N/A')}")
                    print(f"    From: {transfer.get('from', 'N/A')[:10]}...")
                    print(f"    To: {transfer.get('to', 'N/A')[:10]}...")
                    print()
                break  # Stop on first successful key
            else:
                print(f"Response: {json.dumps(result, indent=2)}")
        else:
            print(f"❌ Error: {response.text}")

    except Exception as e:
        print(f"❌ Error: {e}")

print("-" * 50)
print("\nNow testing direct import of fetch_ethereum_transactions...")

# Import and test the actual function
import sys
sys.path.insert(0, '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/crypto-tax-app/backend')
os.environ['DJANGO_SETTINGS_MODULE'] = 'crypto_tax_project.settings'

import django
django.setup()

if working_api_key:
    os.environ['ALCHEMY_API_KEY'] = working_api_key
    print(f"Using working API key: {working_api_key[:8]}...")

from crypto_tax_api.utils.blockchain_apis import fetch_ethereum_transactions

try:
    transactions = fetch_ethereum_transactions(wallet_address)
    print(f"✅ fetch_ethereum_transactions returned {len(transactions)} transactions")
    if transactions:
        print("\nFirst transaction:")
        print(json.dumps(transactions[0], indent=2, default=str))

        # Show summary
        total_value = sum(float(tx.get('value_usd', 0)) for tx in transactions)
        print(f"\nTransaction Summary:")
        print(f"Total transactions: {len(transactions)}")
        print(f"Total value: ${total_value:.2f}")

        # Show transaction types
        tx_types = {}
        for tx in transactions:
            tx_type = tx.get('transaction_type', 'unknown')
            tx_types[tx_type] = tx_types.get(tx_type, 0) + 1
        print(f"Transaction types: {tx_types}")

except Exception as e:
    print(f"❌ Error calling fetch_ethereum_transactions: {e}")
    import traceback
    traceback.print_exc()