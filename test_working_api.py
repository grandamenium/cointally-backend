#!/usr/bin/env python3
import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Use the working API key
api_key = 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'
wallet_address = 'EHDmeoni9Hpxvu2fFL2F4rHhZGhM1k6H3t69knDTsPtf'

print(f"Testing with working Alchemy API key...")
print(f"API Key: {api_key[:8]}...")
print(f"Wallet: {wallet_address}")
print("-" * 50)

url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "getSignaturesForAddress",
    "params": [
        wallet_address,
        {"limit": 10}
    ]
}

try:
    response = requests.post(
        url,
        json=payload,
        headers={'Content-Type': 'application/json'}
    )

    print(f"Status: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        if 'result' in result and result['result']:
            print(f"✅ SUCCESS! Found {len(result['result'])} transactions")
            print("\nTransaction signatures:")
            for sig in result['result'][:5]:
                print(f"  - {sig['signature'][:20]}... (slot: {sig['slot']})")
        else:
            print(f"Response: {json.dumps(result, indent=2)}")
    else:
        print(f"Error: {response.text}")

except Exception as e:
    print(f"Error: {e}")

print("-" * 50)
print("\nNow testing direct import of fetch_solana_transactions...")

# Import and test the actual function
import sys
sys.path.insert(0, '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/crypto-tax-app/backend')
os.environ['ALCHEMY_API_KEY'] = api_key

from crypto_tax_api.utils.blockchain_apis import fetch_solana_transactions

try:
    transactions = fetch_solana_transactions(wallet_address)
    print(f"✅ fetch_solana_transactions returned {len(transactions)} transactions")
    if transactions:
        print("\nFirst transaction:")
        print(json.dumps(transactions[0], indent=2, default=str))
except Exception as e:
    print(f"❌ Error calling fetch_solana_transactions: {e}")