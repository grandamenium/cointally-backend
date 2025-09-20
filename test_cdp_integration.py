#!/usr/bin/env python3
"""
Test script for Coinbase CDP (Advanced Trade) Integration
Tests the complete flow from CDP key upload to transaction syncing
"""

import os
import sys
import json
import asyncio
from datetime import datetime, timedelta

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
import django
django.setup()

from crypto_tax_api.services.coinbase_cdp_auth import (
    parse_cdp_key, extract_key_meta, sign_cdp_jwt,
    CdpKeyData, CdpKeyEncryption, CoinbaseAdvancedClient,
    process_fill_for_tax, redact_private_key, sanitize_log_data
)

def test_cdp_key_parsing():
    """Test parsing of CDP key JSON"""
    print("\n" + "=" * 60)
    print("🔐 TESTING CDP KEY PARSING")
    print("=" * 60)

    # Sample CDP key JSON (you'll need to replace with real key for actual testing)
    sample_cdp_key = {
        "name": "organizations/test-org-123/apiKeys/test-key-456",
        "privateKey": "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIJX6bJbnROpP3FTrZ...\n-----END EC PRIVATE KEY-----\n"
    }

    json_string = json.dumps(sample_cdp_key)

    try:
        # Parse the key
        key_data = parse_cdp_key(json_string)
        print(f"✅ Successfully parsed CDP key")
        print(f"   Key Name: {key_data.name}")
        print(f"   Private Key: {redact_private_key(key_data.private_key)}")

        # Extract metadata
        key_meta = extract_key_meta(key_data)
        print(f"✅ Extracted metadata:")
        print(f"   Organization ID: {key_meta.org_id}")
        print(f"   Key ID: {key_meta.key_id}")

        return key_data

    except Exception as e:
        print(f"❌ Failed to parse CDP key: {e}")
        return None


def test_encryption():
    """Test encryption/decryption of CDP keys"""
    print("\n" + "=" * 60)
    print("🔒 TESTING ENCRYPTION")
    print("=" * 60)

    encryption = CdpKeyEncryption()
    test_data = "This is sensitive private key data"

    try:
        # Encrypt
        encrypted = encryption.encrypt(test_data)
        print(f"✅ Encrypted data: {encrypted[:50]}...")

        # Decrypt
        decrypted = encryption.decrypt(encrypted)
        print(f"✅ Decrypted successfully")

        # Verify
        assert decrypted == test_data, "Decrypted data doesn't match original!"
        print(f"✅ Encryption/Decryption working correctly")

        return True

    except Exception as e:
        print(f"❌ Encryption test failed: {e}")
        return False


def test_jwt_generation(key_data):
    """Test JWT generation for CDP authentication"""
    print("\n" + "=" * 60)
    print("🎫 TESTING JWT GENERATION")
    print("=" * 60)

    if not key_data:
        print("⚠️  Skipping JWT test - no valid key data")
        return None

    try:
        # Generate JWT for a sample request
        jwt_token = sign_cdp_jwt(key_data, "GET", "/api/v3/brokerage/accounts")
        print(f"✅ Generated JWT token")
        print(f"   Token (first 100 chars): {jwt_token[:100]}...")

        # Decode to verify structure (without verification)
        import jwt
        header = jwt.get_unverified_header(jwt_token)
        payload = jwt.decode(jwt_token, options={"verify_signature": False})

        print(f"✅ JWT Header:")
        print(f"   Algorithm: {header.get('alg')}")
        print(f"   Kid: {header.get('kid')}")
        print(f"   Nonce: {header.get('nonce')[:10]}...")

        print(f"✅ JWT Payload:")
        print(f"   Subject: {payload.get('sub')}")
        print(f"   Issuer: {payload.get('iss')}")
        print(f"   URI: {payload.get('uri')}")
        print(f"   Expires in: {payload.get('exp') - payload.get('nbf')} seconds")

        return jwt_token

    except Exception as e:
        print(f"❌ JWT generation failed: {e}")
        return None


async def test_api_client():
    """Test the Coinbase Advanced API client (requires real CDP key)"""
    print("\n" + "=" * 60)
    print("🌐 TESTING API CLIENT")
    print("=" * 60)

    # For testing, you'll need to provide a real CDP key
    # Either load from file or use environment variable
    cdp_key_path = os.environ.get('CDP_KEY_PATH', 'cdp_api_key.json')

    if not os.path.exists(cdp_key_path):
        print(f"⚠️  CDP key file not found at {cdp_key_path}")
        print("   Set CDP_KEY_PATH environment variable to point to your key file")
        return

    try:
        # Load the CDP key
        with open(cdp_key_path, 'r') as f:
            key_json = f.read()

        key_data = parse_cdp_key(key_json)

        # Create key loader
        async def load_key():
            return key_data

        # Create client
        client = CoinbaseAdvancedClient(load_key)

        # Test 1: Get accounts
        print("\n📊 Testing GET /accounts...")
        accounts = await client.get_accounts(limit=5)
        print(f"✅ Retrieved {len(accounts.get('accounts', []))} accounts")

        for acc in accounts.get('accounts', [])[:3]:
            print(f"   - {acc.get('currency')}: {acc.get('available_balance', {}).get('value')}")

        # Test 2: Get products
        print("\n📈 Testing GET /products...")
        products = await client.get_products(limit=5)
        print(f"✅ Retrieved {len(products.get('products', []))} products")

        # Test 3: Get recent fills
        print("\n💱 Testing GET /fills...")
        end_date = datetime.now().isoformat()
        start_date = (datetime.now() - timedelta(days=30)).isoformat()

        fills = await client.list_fills(
            start_date=start_date,
            end_date=end_date,
            limit=5
        )
        print(f"✅ Retrieved {len(fills.get('fills', []))} fills")

        # Process fills for tax
        for fill in fills.get('fills', [])[:2]:
            tax_data = process_fill_for_tax(fill)
            print(f"   - {tax_data['type']}: {tax_data['quantity']} {tax_data['asset']}")

        # Clean up
        await client.close()

    except Exception as e:
        print(f"❌ API client test failed: {e}")
        import traceback
        traceback.print_exc()


def test_data_sanitization():
    """Test data sanitization for logging"""
    print("\n" + "=" * 60)
    print("🧹 TESTING DATA SANITIZATION")
    print("=" * 60)

    test_data = {
        "api_key": "sensitive_api_key_123",
        "private_key": "-----BEGIN EC PRIVATE KEY-----\nSENSITIVE\n-----END EC PRIVATE KEY-----\n",
        "public_data": "This is public",
        "nested": {
            "secret": "hidden_value",
            "normal": "visible_value"
        }
    }

    sanitized = sanitize_log_data(test_data)

    print("✅ Original data keys:", list(test_data.keys()))
    print("✅ Sanitized data:")
    print(json.dumps(sanitized, indent=2))

    # Verify sanitization
    assert sanitized['api_key'] == '[REDACTED]'
    assert sanitized['private_key'] == '-----BEGIN EC PRIVATE KEY-----\n[REDACTED]\n-----END EC PRIVATE KEY-----'
    assert sanitized['public_data'] == 'This is public'
    assert sanitized['nested']['secret'] == '[REDACTED]'
    assert sanitized['nested']['normal'] == 'visible_value'

    print("✅ All sensitive data properly sanitized")


def main():
    """Run all tests"""
    print("\n" + "🚀 " * 20)
    print(" COINBASE CDP INTEGRATION TEST SUITE")
    print("🚀 " * 20)

    # Test 1: Key parsing
    key_data = test_cdp_key_parsing()

    # Test 2: Encryption
    test_encryption()

    # Test 3: JWT generation
    if key_data:
        test_jwt_generation(key_data)

    # Test 4: Data sanitization
    test_data_sanitization()

    # Test 5: API client (async)
    print("\n" + "=" * 60)
    print("Running async API tests...")
    print("=" * 60)
    asyncio.run(test_api_client())

    print("\n" + "🎉 " * 20)
    print(" TEST SUITE COMPLETED")
    print("🎉 " * 20)


if __name__ == "__main__":
    main()