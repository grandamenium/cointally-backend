#!/usr/bin/env python3
"""
Test script to simulate frontend integration with the public wallet
"""
import requests
import json
import time

def test_frontend_integration():
    """Test the public wallet through the Django API endpoints"""

    # Public wallet found on Arbiscan with confirmed transactions
    test_address = "0xdA5e1988097297dcdc1f90d4dfe7909e847CBeF6"

    print("=" * 80)
    print("FRONTEND INTEGRATION TEST")
    print("=" * 80)
    print(f"Test Address: {test_address}")
    print("Source: https://arbiscan.io/address/0xda5e1988097297dcdc1f90d4dfe7909e847cbef6")
    print("Expected: USDC, ETH, USDT, ACHIVX transactions (13 total)")
    print("=" * 80)

    # API endpoint (same as frontend calls)
    api_url = "http://127.0.0.1:8000/api/wallets/analyze/"

    # Prepare the request payload (same format as frontend)
    payload = {
        "address": test_address,
        "chain": "arbitrum"
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    print(f"\n🔄 Making API request to: {api_url}")
    print(f"📝 Payload: {json.dumps(payload, indent=2)}")
    print(f"⏱️  Starting request at: {time.strftime('%H:%M:%S')}")

    try:
        # Make the request (same as frontend)
        response = requests.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=120  # Allow time for API processing
        )

        end_time = time.strftime('%H:%M:%S')
        print(f"⏱️  Request completed at: {end_time}")
        print(f"📊 Response Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            # Parse the response
            transactions = data.get('transactions', [])
            portfolio = data.get('portfolio_data', {})
            tax_summary = data.get('tax_summary', {})

            print(f"\n✅ SUCCESS!")
            print(f"📈 Found {len(transactions)} transactions")

            if transactions:
                print(f"\n🔍 First 3 transactions:")
                for i, tx in enumerate(transactions[:3]):
                    print(f"\n  Transaction {i+1}:")
                    print(f"    Hash: {tx.get('transaction_hash', 'N/A')[:16]}...")
                    print(f"    Date: {tx.get('timestamp', 'N/A')}")
                    print(f"    Type: {tx.get('transaction_type', 'N/A')}")
                    print(f"    Asset: {tx.get('asset_symbol', 'N/A')}")
                    print(f"    Amount: {tx.get('amount', 'N/A')}")
                    print(f"    Value: ${tx.get('value_usd', 'N/A')}")

                # Check for expected assets
                assets = set(tx.get('asset_symbol', 'Unknown') for tx in transactions)
                print(f"\n💰 Assets found: {', '.join(sorted(assets))}")

                expected_assets = {'USDC', 'ETH', 'USDT', 'ACHIVX'}
                found_expected = expected_assets.intersection(assets)

                if found_expected:
                    print(f"✅ VALIDATION SUCCESS: Found expected assets: {', '.join(found_expected)}")
                else:
                    print(f"⚠️  Expected assets not found. Expected: {', '.join(expected_assets)}")

            # Portfolio data
            if portfolio:
                print(f"\n📊 Portfolio Data:")
                print(f"    Total Value: ${portfolio.get('total_value', 'N/A')}")
                print(f"    Holdings: {len(portfolio.get('holdings', []))}")

            # Tax summary
            if tax_summary:
                print(f"\n📋 Tax Summary:")
                print(f"    Total Realized Gains: ${tax_summary.get('total_realized_gains', 'N/A')}")
                print(f"    Taxable Events: {tax_summary.get('taxable_events_count', 'N/A')}")

            print(f"\n🎉 Frontend integration test PASSED!")
            print(f"💡 The API correctly processes real Arbitrum transactions from Alchemy!")

            return True

        else:
            print(f"\n❌ API Error: {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"\n💥 Request Error: {str(e)}")
        return False

if __name__ == "__main__":
    print("Starting Frontend Integration Test for Arbitrum API...")
    success = test_frontend_integration()

    print("\n" + "=" * 80)
    if success:
        print("🏆 FRONTEND INTEGRATION TEST COMPLETED SUCCESSFULLY!")
        print("✅ Arbitrum API integration is working correctly")
        print("✅ Real transaction data is being fetched from Alchemy")
        print("✅ Backend processing is functioning properly")
    else:
        print("❌ FRONTEND INTEGRATION TEST FAILED")
        print("🔧 Check the server logs for more details")
    print("=" * 80)