#!/usr/bin/env python3
"""
Debug the user's ETH wallet with comprehensive API testing
"""
import requests
import json

# User's wallet address
user_wallet = "0x7A60A1D6c0Cc316b93C9b7E9A96dE61fF434BEbf"
api_key = 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'
alchemy_url = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

print("=== Comprehensive ETH Wallet Debug ===")
print(f"Wallet: {user_wallet}")
print(f"API Key: {api_key[:8]}...")
print("=" * 60)

# 1. Check account balance first
print("\n1. Checking account balance...")
print("-" * 40)
balance_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_getBalance",
    "params": [user_wallet, "latest"]
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
            if balance_eth > 0:
                print("   (Wallet has ETH, so transactions should exist)")
            else:
                print("   (Wallet has no ETH currently)")
        else:
            print(f"Balance check failed: {data}")
    else:
        print(f"❌ Balance check error: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Balance check error: {e}")

# 2. Try with different block ranges (recent first)
print("\n2. Testing with recent block range...")
print("-" * 40)

# Get current block number
current_block_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_blockNumber",
    "params": []
}

try:
    response = requests.post(alchemy_url, json=current_block_payload, timeout=10)
    if response.status_code == 200:
        data = response.json()
        current_block_hex = data['result']
        current_block = int(current_block_hex, 16)

        # Calculate blocks for last 6 months (~1.3M blocks)
        blocks_6_months = 1300000
        start_block = max(0, current_block - blocks_6_months)

        print(f"Current block: {current_block}")
        print(f"Searching from block {start_block} to {current_block}")

        # Search recent transactions
        recent_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": hex(start_block),
                    "toBlock": "latest",
                    "fromAddress": user_wallet.lower(),
                    "category": ["external", "internal", "erc20", "erc721", "erc1155"],
                    "maxCount": "0x3e8"  # 1000 max results
                }
            ]
        }

        response = requests.post(alchemy_url, json=recent_payload, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'transfers' in data['result']:
                transfers = data['result']['transfers']
                print(f"✅ Found {len(transfers)} recent outgoing transfers")
                if transfers:
                    print("Recent transfers:")
                    for transfer in transfers[:5]:
                        print(f"  - Hash: {transfer.get('hash', 'N/A')}")
                        print(f"    Asset: {transfer.get('asset', 'N/A')}")
                        print(f"    Value: {transfer.get('value', 'N/A')}")
                        print(f"    Block: {transfer.get('blockNum', 'N/A')}")
                        print()
            else:
                print(f"No recent transfers found")
        else:
            print(f"❌ Recent transfers error: {response.status_code} - {response.text}")

except Exception as e:
    print(f"❌ Recent transfers error: {e}")

# 3. Try searching for incoming with recent blocks
print("\n3. Testing incoming transactions with recent blocks...")
print("-" * 40)

try:
    incoming_recent_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": hex(start_block),
                "toBlock": "latest",
                "toAddress": user_wallet.lower(),
                "category": ["external", "internal", "erc20"],
                "maxCount": "0x3e8"  # 1000 max results
            }
        ]
    }

    response = requests.post(alchemy_url, json=incoming_recent_payload, timeout=15)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data and 'transfers' in data['result']:
            transfers = data['result']['transfers']
            print(f"✅ Found {len(transfers)} recent incoming transfers")
            if transfers:
                print("Recent incoming transfers:")
                for transfer in transfers[:5]:
                    print(f"  - Hash: {transfer.get('hash', 'N/A')}")
                    print(f"    Asset: {transfer.get('asset', 'N/A')}")
                    print(f"    Value: {transfer.get('value', 'N/A')}")
                    print(f"    Block: {transfer.get('blockNum', 'N/A')}")
                    print()
        else:
            print(f"No recent incoming transfers found")
    else:
        print(f"❌ Recent incoming transfers error: {response.status_code} - {response.text}")

except Exception as e:
    print(f"❌ Recent incoming transfers error: {e}")

# 4. Try a different approach - get transaction count
print("\n4. Checking transaction count...")
print("-" * 40)

tx_count_payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "eth_getTransactionCount",
    "params": [user_wallet, "latest"]
}

try:
    response = requests.post(alchemy_url, json=tx_count_payload, timeout=10)
    if response.status_code == 200:
        data = response.json()
        if 'result' in data:
            count_hex = data['result']
            tx_count = int(count_hex, 16)
            print(f"✅ Transaction count (nonce): {tx_count}")
            if tx_count > 0:
                print("   (This confirms the wallet has sent transactions)")
            else:
                print("   (Wallet has never sent a transaction)")
        else:
            print(f"Transaction count check failed: {data}")
    else:
        print(f"❌ Transaction count error: {response.status_code} - {response.text}")
except Exception as e:
    print(f"❌ Transaction count error: {e}")

print(f"\n" + "=" * 60)
print("SUMMARY:")
print("If balance > 0 or tx count > 0, but transfers = 0,")
print("then the API method might not be capturing all transaction types")
print("or there might be an issue with the search parameters.")