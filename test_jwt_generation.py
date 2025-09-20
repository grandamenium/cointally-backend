#!/usr/bin/env python3
"""
Test script to debug JWT generation for Coinbase CDP authentication
"""

import json
import time
import secrets
import jwt
import httpx
import asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Read the CDP key file
CDP_KEY_FILE = '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/cdp_api_key (1).json'

def load_cdp_key():
    """Load CDP key from file"""
    with open(CDP_KEY_FILE, 'r') as f:
        data = json.load(f)
    print(f"Loaded CDP key: {data['name']}")
    return data

def generate_jwt(key_data, method='GET', path='/api/v3/brokerage/accounts'):
    """Generate JWT token for CDP authentication"""

    # Parse private key
    private_key_bytes = key_data['privateKey'].encode('utf-8')
    try:
        private_key = serialization.load_pem_private_key(
            private_key_bytes,
            password=None,
            backend=default_backend()
        )
        print("✓ Private key loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load private key: {e}")
        raise

    # Build URI (method + space + host + path)
    uri = f"{method} api.coinbase.com{path}"
    print(f"URI: {uri}")

    # JWT payload following Coinbase specifications
    current_time = int(time.time())
    payload = {
        'sub': key_data['name'],
        'iss': 'cdp',  # issuer must be 'cdp'
        'nbf': current_time,
        'exp': current_time + 120,  # 2-minute expiry
        'uri': uri
    }

    print(f"Payload: {json.dumps(payload, indent=2)}")

    # JWT headers
    headers = {
        'alg': 'ES256',
        'kid': key_data['name'],
        'nonce': secrets.token_hex(16),
        'typ': 'JWT'
    }

    print(f"Headers: {json.dumps(headers, indent=2)}")

    # Generate JWT
    token = jwt.encode(
        payload,
        private_key,
        algorithm='ES256',
        headers=headers
    )

    print(f"\n✓ JWT generated successfully")
    print(f"Token length: {len(token)} characters")

    # Decode to verify
    try:
        # Get public key from private key for verification
        public_key = private_key.public_key()
        decoded = jwt.decode(token, public_key, algorithms=['ES256'])
        print(f"✓ JWT verification successful")
        print(f"Decoded payload: {json.dumps(decoded, indent=2)}")
    except Exception as e:
        print(f"✗ JWT verification failed: {e}")

    return token

async def test_api_call(key_data):
    """Test actual API call with generated JWT"""

    # Generate JWT
    method = 'GET'
    path = '/api/v3/brokerage/accounts'
    jwt_token = generate_jwt(key_data, method, path)

    # Make API call
    url = f"https://api.coinbase.com{path}"
    headers = {
        'Authorization': f'Bearer {jwt_token}',
        'Content-Type': 'application/json'
    }

    print(f"\n--- Making API Call ---")
    print(f"URL: {url}")
    print(f"Method: {method}")
    print(f"Headers: Authorization: Bearer <token>")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers)
            print(f"\n✓ API Response Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Success! Retrieved {len(data.get('accounts', []))} accounts")
                for account in data.get('accounts', [])[:3]:  # Show first 3 accounts
                    print(f"  - {account.get('name', 'Unknown')} ({account.get('currency', 'N/A')}): {account.get('available_balance', {}).get('value', '0')}")
            else:
                print(f"✗ Error: {response.status_code}")
                print(f"Response: {response.text}")

                # Try to decode error message
                try:
                    error_data = response.json()
                    print(f"Error details: {json.dumps(error_data, indent=2)}")
                except:
                    pass

        except Exception as e:
            print(f"✗ Request failed: {e}")

async def test_fills_endpoint(key_data):
    """Test the fills endpoint that was failing"""

    # Generate JWT for fills endpoint
    method = 'GET'
    path = '/api/v3/brokerage/orders/historical/fills'
    jwt_token = generate_jwt(key_data, method, path)

    # Make API call
    url = f"https://api.coinbase.com{path}"
    headers = {
        'Authorization': f'Bearer {jwt_token}',
        'Content-Type': 'application/json'
    }

    params = {
        'limit': 10  # Get just 10 fills for testing
    }

    print(f"\n--- Testing Fills Endpoint ---")
    print(f"URL: {url}")
    print(f"Method: {method}")
    print(f"Params: {params}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            print(f"\n✓ Fills API Response Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Success! Retrieved {len(data.get('fills', []))} fills")
                for fill in data.get('fills', [])[:3]:  # Show first 3 fills
                    print(f"  - {fill.get('product_id', 'Unknown')}: {fill.get('side', 'N/A')} {fill.get('size', '0')} @ {fill.get('price', '0')}")
            else:
                print(f"✗ Error: {response.status_code}")
                print(f"Response: {response.text}")

        except Exception as e:
            print(f"✗ Request failed: {e}")

def main():
    """Main test function"""
    print("=" * 60)
    print("Coinbase CDP JWT Authentication Test")
    print("=" * 60)

    try:
        # Load CDP key
        key_data = load_cdp_key()

        # Test JWT generation
        print("\n--- Testing JWT Generation ---")
        generate_jwt(key_data)

        # Test actual API calls
        print("\n" + "=" * 60)
        print("Testing API Calls")
        print("=" * 60)

        # Run async tests
        asyncio.run(test_api_call(key_data))
        asyncio.run(test_fills_endpoint(key_data))

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()