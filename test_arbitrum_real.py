#!/usr/bin/env python3
"""
Direct test of Arbitrum API with user's provided endpoint and address
"""
import requests
import json
from datetime import datetime

def test_arbitrum_direct():
    """Test the actual Arbitrum endpoint with the user's address"""

    # User's provided API endpoint and address
    api_key = 'dN6yJ1dHDtCc9LIRC2lDf'
    user_address = '0xc9C9fafcE2AF75CF2924de3DFef8Eb8f50BC77b2'
    alchemy_url = f'https://arb-mainnet.g.alchemy.com/v2/{api_key}'

    print(f"Testing Arbitrum API with:")
    print(f"  Address: {user_address}")
    print(f"  API Key: {api_key}")
    print(f"  Endpoint: {alchemy_url}")
    print("=" * 60)

    # Test 1: Check if API is accessible
    print("\n1. Testing API connectivity...")
    test_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_blockNumber"
    }

    try:
        response = requests.post(alchemy_url, json=test_payload, timeout=10)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                block_num = int(data['result'], 16)
                print(f"   ✓ Connected! Current block: {block_num}")
            elif 'error' in data:
                print(f"   ✗ API Error: {data['error']}")
                return False
        else:
            print(f"   ✗ HTTP Error: {response.text}")
            return False
    except Exception as e:
        print(f"   ✗ Connection Error: {str(e)}")
        return False

    # Test 2: Get incoming transfers for the user's address
    print(f"\n2. Fetching incoming transfers for {user_address}...")
    incoming_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "toAddress": user_address.lower(),
                "category": ["external", "erc20", "erc721", "erc1155"],
                "maxCount": "0x14"  # Get 20 transactions
            }
        ]
    }

    try:
        response = requests.post(alchemy_url, json=incoming_payload, timeout=30)
        print(f"   Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if 'error' in data:
                print(f"   ✗ API Error: {data['error']}")
                return False
            elif 'result' in data and 'transfers' in data['result']:
                transfers = data['result']['transfers']
                print(f"   ✓ Found {len(transfers)} incoming transfers")

                # Look for ARB tokens
                arb_transfers = []
                for tx in transfers:
                    asset = tx.get('asset', '')
                    if 'ARB' in asset.upper():
                        arb_transfers.append(tx)

                if arb_transfers:
                    print(f"\n   🎯 Found {len(arb_transfers)} ARB transfers!")
                    for tx in arb_transfers[:3]:  # Show first 3
                        print(f"\n   ARB Transfer:")
                        print(f"     Hash: {tx.get('hash', 'N/A')}")
                        print(f"     Block: {tx.get('blockNum', 'N/A')}")
                        print(f"     From: {tx.get('from', 'N/A')[:20]}...")
                        print(f"     Asset: {tx.get('asset', 'N/A')}")
                        print(f"     Value: {tx.get('value', 'N/A')}")

                        # Convert block number to approximate date if possible
                        if tx.get('blockNum'):
                            block_num = int(tx.get('blockNum'), 16)
                            print(f"     Block Number (dec): {block_num}")

                # Show sample of all transfers
                print(f"\n   Sample of all transfers (first 5):")
                for i, tx in enumerate(transfers[:5]):
                    print(f"\n   Transfer {i+1}:")
                    print(f"     Hash: {tx.get('hash', 'N/A')}")
                    print(f"     Asset: {tx.get('asset', 'N/A')}")
                    print(f"     Value: {tx.get('value', 'N/A')}")
                    print(f"     From: {tx.get('from', 'N/A')[:20]}...")

                return True
            else:
                print("   ⚠️ No transfers found for this address")
                return True  # API works but no data
        else:
            print(f"   ✗ HTTP Error: {response.text}")
            return False

    except Exception as e:
        print(f"   ✗ Request Error: {str(e)}")
        return False

    # Test 3: Get outgoing transfers
    print(f"\n3. Fetching outgoing transfers...")
    outgoing_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "fromAddress": user_address.lower(),
                "category": ["external", "erc20"],
                "maxCount": "0xA"
            }
        ]
    }

    try:
        response = requests.post(alchemy_url, json=outgoing_payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'transfers' in data['result']:
                transfers = data['result']['transfers']
                print(f"   ✓ Found {len(transfers)} outgoing transfers")

                if transfers:
                    print("\n   Sample outgoing transfer:")
                    tx = transfers[0]
                    print(f"     Hash: {tx.get('hash', 'N/A')}")
                    print(f"     Asset: {tx.get('asset', 'N/A')}")
                    print(f"     Value: {tx.get('value', 'N/A')}")
    except Exception as e:
        print(f"   ✗ Error: {str(e)}")

    return True

if __name__ == "__main__":
    print("Direct Arbitrum API Test")
    print("Expected: ARB transaction of +1.95 ARB (~$0.99) on Sep 16, 2025")
    print("=" * 60)

    success = test_arbitrum_direct()

    print("\n" + "=" * 60)
    if success:
        print("✅ API connection successful!")
        print("Note: If no transactions found, the address may not have activity on Arbitrum")
    else:
        print("❌ API connection failed - check the API key or endpoint")