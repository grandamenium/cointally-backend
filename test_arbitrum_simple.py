#!/usr/bin/env python3
"""
Simple test script for Arbitrum API without Django dependencies
"""
import os
import json
import requests
from decimal import Decimal
from datetime import datetime, timezone

def get_alchemy_api_key(network_specific_var=None):
    """
    Standard API key retrieval pattern for all blockchain integrations
    """
    # Try primary unified key first
    api_key = os.environ.get('ALCHEMY_API_KEY')

    # Fallback to network-specific key if provided
    if not api_key and network_specific_var:
        api_key = os.environ.get(network_specific_var)

    # Last resort hardcoded fallback (from the endpoint you provided)
    if not api_key:
        api_key = 'dN6yJ1dHDtCc9LIRIC2lDf'

    # Clean the API key
    api_key = api_key.strip().replace("'", "").replace('"', '')

    return api_key

def test_arbitrum_api_direct(address):
    """Test Arbitrum API connectivity directly"""
    print("=== Testing Arbitrum API Direct Connection ===")

    # Get API key
    api_key = get_alchemy_api_key('ALCHEMY_ARBITRUM_API_KEY')
    print(f"Using API key: {api_key[:10]}...")

    # Arbitrum endpoint
    alchemy_url = f"https://arb-mainnet.g.alchemy.com/v2/{api_key}"
    print(f"Endpoint: {alchemy_url[:50]}...")

    # Test basic connectivity
    test_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_blockNumber"
    }

    print("\n1. Testing basic connectivity...")
    try:
        response = requests.post(alchemy_url, json=test_payload, timeout=10)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                block_num = int(data['result'], 16)
                print(f"✓ Connected! Current block: {block_num}")
            else:
                print(f"✗ API Error: {data}")
        else:
            print(f"✗ HTTP Error: {response.text}")
    except Exception as e:
        print(f"✗ Connection Error: {str(e)}")

    # Test asset transfers for incoming transactions
    print(f"\n2. Testing asset transfers for address {address}...")
    transfers_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "toAddress": address.lower(),
                "category": ["external", "erc20"],
                "maxCount": "0xA"  # Get 10 transactions
            }
        ]
    }

    try:
        response = requests.post(alchemy_url, json=transfers_payload, timeout=30)
        print(f"Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if 'error' in data:
                print(f"✗ API Error: {data['error']}")
            elif 'result' in data:
                transfers = data['result'].get('transfers', [])
                print(f"✓ Found {len(transfers)} incoming transfers")

                if transfers:
                    print("\nSample transactions:")
                    for i, tx in enumerate(transfers[:3]):
                        print(f"\nTransaction {i+1}:")
                        print(f"  Hash: {tx.get('hash', 'N/A')}")
                        print(f"  Block: {tx.get('blockNum', 'N/A')}")
                        print(f"  From: {tx.get('from', 'N/A')}")
                        print(f"  To: {tx.get('to', 'N/A')}")
                        print(f"  Asset: {tx.get('asset', 'N/A')}")
                        print(f"  Value: {tx.get('value', 'N/A')}")

                        # Check if this could be an ARB token transfer
                        if tx.get('asset') and 'ARB' in str(tx.get('asset', '')).upper():
                            print(f"  *** This might be an ARB transaction! ***")

                    # Look for ARB specifically
                    arb_transfers = [tx for tx in transfers if tx.get('asset') and 'ARB' in str(tx.get('asset', '')).upper()]
                    if arb_transfers:
                        print(f"\n✓ Found {len(arb_transfers)} potential ARB transfers!")
                        for tx in arb_transfers:
                            print(f"  ARB Transfer: {tx.get('value', 'N/A')} {tx.get('asset', 'N/A')}")

        else:
            print(f"✗ HTTP Error: {response.text}")
    except Exception as e:
        print(f"✗ Transfer Request Error: {str(e)}")

    # Test outgoing transactions too
    print(f"\n3. Testing outgoing transactions...")
    outgoing_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "fromAddress": address.lower(),
                "category": ["external", "erc20"],
                "maxCount": "0x5"  # Get 5 transactions
            }
        ]
    }

    try:
        response = requests.post(alchemy_url, json=outgoing_payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                transfers = data['result'].get('transfers', [])
                print(f"✓ Found {len(transfers)} outgoing transfers")
    except Exception as e:
        print(f"✗ Outgoing Request Error: {str(e)}")

def test_eth_mainnet_for_comparison():
    """Test the same address on Ethereum mainnet for comparison"""
    print("\n=== Testing Same Address on Ethereum Mainnet (for comparison) ===")

    api_key = get_alchemy_api_key()
    eth_url = f"https://eth-mainnet.g.alchemy.com/v2/{api_key}"

    test_address = "0xc9C9fafcE2AF75CF2924de3DFef8Eb8f50BC77b2"

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": "0x0",
                "toBlock": "latest",
                "toAddress": test_address.lower(),
                "category": ["external", "erc20"],
                "maxCount": "0x5"
            }
        ]
    }

    try:
        response = requests.post(eth_url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                transfers = data['result'].get('transfers', [])
                print(f"Ethereum transfers for same address: {len(transfers)}")
    except Exception as e:
        print(f"Ethereum test error: {str(e)}")

if __name__ == "__main__":
    # Your Arbitrum address
    test_address = "0xc9C9fafcE2AF75CF2924de3DFef8Eb8f50BC77b2"

    print("Arbitrum API Integration Test")
    print(f"Testing address: {test_address}")
    print(f"Expected: +1.95 ARB transaction on Sep 16, 2025 (~$0.99)")
    print("=" * 60)

    # Test the API
    test_arbitrum_api_direct(test_address)

    # Compare with Ethereum
    test_eth_mainnet_for_comparison()

    print("\n" + "=" * 60)
    print("Test completed!")