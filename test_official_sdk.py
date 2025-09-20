#!/usr/bin/env python3
"""
Test script using official Coinbase Advanced Trade SDK
"""

import json
from coinbase.rest import RESTClient

# Read the CDP key file
CDP_KEY_FILE = '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/cdp_api_key (1).json'

def test_with_sdk():
    """Test using official SDK"""

    # Load CDP key
    with open(CDP_KEY_FILE, 'r') as f:
        key_data = json.load(f)

    print("=" * 60)
    print("Testing with Official Coinbase SDK")
    print("=" * 60)
    print(f"Key Name: {key_data['name']}")

    try:
        # Initialize client with CDP credentials
        client = RESTClient(
            api_key=key_data['name'],
            api_secret=key_data['privateKey']
        )

        print("\n--- Testing Accounts Endpoint ---")
        # Get accounts
        accounts = client.get_accounts()

        if accounts:
            print(f"✓ Success! Retrieved {len(accounts.accounts)} accounts")
            for account in accounts.accounts[:3]:  # Show first 3 accounts
                print(f"  - {account.name} ({account.currency}): {account.available_balance.value}")
        else:
            print("✗ No accounts returned")

        print("\n--- Testing Fills Endpoint ---")
        # Get fills
        fills = client.get_fills(limit=10)

        if fills:
            print(f"✓ Success! Retrieved fills")
            if fills.fills:
                for fill in fills.fills[:3]:  # Show first 3 fills
                    print(f"  - {fill.product_id}: {fill.side} {fill.size} @ {fill.price}")
            else:
                print("  No fills found (empty trading history)")
        else:
            print("✗ No fills returned")

    except Exception as e:
        print(f"\n✗ SDK Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_with_sdk()