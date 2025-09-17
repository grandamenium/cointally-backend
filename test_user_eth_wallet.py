#!/usr/bin/env python3
"""
Test the user's specific ETH wallet to see what transactions we can find
"""
import os
import sys
import requests
import json
sys.path.insert(0, '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/crypto-tax-app/backend')

os.environ['DJANGO_SETTINGS_MODULE'] = 'crypto_tax_project.settings'

import django
django.setup()

from crypto_tax_api.utils.blockchain_apis import fetch_ethereum_transactions

# User's wallet address
user_wallet = "0x7A60A1D6c0Cc316b93C9b7E9A96dE61fF434BEbf"

print("=== Testing User's ETH Wallet ===")
print(f"Wallet: {user_wallet}")
print("=" * 60)

# First, let's test the raw API call to see what Alchemy returns
api_key = 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'
alchemy_url = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

print("\n1. Testing raw Alchemy API call...")
print("-" * 40)

# Test outgoing transactions
outgoing_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "alchemy_getAssetTransfers",
    "params": [
        {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "fromAddress": user_wallet.lower(),
            "category": ["external", "internal", "erc20", "erc721", "erc1155"]
        }
    ]
}

try:
    response = requests.post(alchemy_url, json=outgoing_payload, timeout=10)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data and 'transfers' in data['result']:
            transfers = data['result']['transfers']
            print(f"✅ Found {len(transfers)} outgoing transfers")
            if transfers:
                print("First few transfers:")
                for i, transfer in enumerate(transfers[:3]):
                    print(f"  {i+1}. Hash: {transfer.get('hash', 'N/A')}")
                    print(f"     Asset: {transfer.get('asset', 'N/A')}")
                    print(f"     Value: {transfer.get('value', 'N/A')}")
                    print(f"     Block: {transfer.get('blockNum', 'N/A')}")
                    print()
        else:
            print(f"No outgoing transfers found. Response: {json.dumps(data, indent=2)}")
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n2. Testing incoming transactions...")
print("-" * 40)

# Test incoming transactions
incoming_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "alchemy_getAssetTransfers",
    "params": [
        {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "toAddress": user_wallet.lower(),
            "category": ["external", "internal", "erc20"]
        }
    ]
}

try:
    response = requests.post(alchemy_url, json=incoming_payload, timeout=10)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data and 'transfers' in data['result']:
            transfers = data['result']['transfers']
            print(f"✅ Found {len(transfers)} incoming transfers")
            if transfers:
                print("First few transfers:")
                for i, transfer in enumerate(transfers[:3]):
                    print(f"  {i+1}. Hash: {transfer.get('hash', 'N/A')}")
                    print(f"     Asset: {transfer.get('asset', 'N/A')}")
                    print(f"     Value: {transfer.get('value', 'N/A')}")
                    print(f"     Block: {transfer.get('blockNum', 'N/A')}")
                    print()
        else:
            print(f"No incoming transfers found. Response: {json.dumps(data, indent=2)}")
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n3. Testing our fetch_ethereum_transactions function...")
print("-" * 50)

try:
    transactions = fetch_ethereum_transactions(user_wallet)
    print(f"✅ Our function returned {len(transactions)} transactions")

    if transactions:
        print("\nTransactions found:")
        for i, tx in enumerate(transactions):
            print(f"  {i+1}. Hash: {tx.get('transaction_hash', 'N/A')}")
            print(f"     Type: {tx.get('transaction_type', 'N/A')}")
            print(f"     Asset: {tx.get('asset_symbol', 'N/A')}")
            print(f"     Amount: {tx.get('amount', 'N/A')}")
            print(f"     Value USD: ${tx.get('value_usd', 'N/A')}")
            print(f"     Timestamp: {tx.get('timestamp', 'N/A')}")
            print()
    else:
        print("No transactions found by our function")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()