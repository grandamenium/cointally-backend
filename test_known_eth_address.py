#!/usr/bin/env python3
"""
Test a known active ETH address to verify our API integration is working
"""
import requests
import json

# Use a well-known active ETH address (like Vitalik's)
known_address = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
api_key = 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'
alchemy_url = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

print("=== Testing Known Active ETH Address ===")
print(f"Address: {known_address} (Vitalik's wallet)")
print("=" * 60)

# Check balance
balance_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_getBalance",
    "params": [known_address, "latest"]
}

try:
    response = requests.post(alchemy_url, json=balance_payload, timeout=10)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data:
            balance_hex = data['result']
            balance_wei = int(balance_hex, 16)
            balance_eth = balance_wei / 1e18
            print(f"✅ Current ETH Balance: {balance_eth:.6f} ETH")
        else:
            print(f"Balance check failed: {data}")
    else:
        print(f"❌ Balance check error: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Balance check error: {e}")

# Check recent transactions
print("\nTesting recent outgoing transactions...")
outgoing_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "alchemy_getAssetTransfers",
    "params": [
        {
            "fromBlock": "0x0",
            "toBlock": "latest",
            "fromAddress": known_address.lower(),
            "category": ["external", "internal", "erc20"],
            "maxCount": "0x5"  # Just 5 for testing
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
                print("Sample transfers:")
                for transfer in transfers[:3]:
                    print(f"  - Hash: {transfer.get('hash', 'N/A')}")
                    print(f"    Asset: {transfer.get('asset', 'N/A')}")
                    print(f"    Value: {transfer.get('value', 'N/A')}")
                    print()
        else:
            print(f"No transfers found")
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Error: {e}")

print("\n" + "=" * 60)
print("If this known address shows transactions,")
print("then our API integration is working correctly!")