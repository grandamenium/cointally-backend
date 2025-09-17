#!/usr/bin/env python3
import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Test configuration
api_key = 'dN6yJ1dHDtCc9LIRIC2lDf'
wallet_address = 'EHDmeoni9Hpxvu2fFL2F4rHhZGhM1k6H3t69knDTsPtf'

print(f"Testing Alchemy Solana API authentication...")
print(f"API Key: {api_key}")
print(f"Wallet: {wallet_address}")
print("-" * 50)

# Test 1: Direct URL with API key in path (like curl)
url1 = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
payload1 = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "getSignaturesForAddress",
    "params": [
        wallet_address,
        {"limit": 10}
    ]
}

print("\nTest 1: Direct URL with API key in path")
print(f"URL: {url1}")
print(f"Payload: {json.dumps(payload1, indent=2)}")

try:
    # Match curl headers exactly
    headers1 = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    response1 = requests.post(url1, json=payload1, headers=headers1)
    print(f"Status: {response1.status_code}")
    print(f"Response: {json.dumps(response1.json(), indent=2)[:500]}")
except Exception as e:
    print(f"Error: {e}")

print("-" * 50)

# Test 2: Try with different header configurations
print("\nTest 2: With User-Agent header (sometimes required)")
headers2 = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'User-Agent': 'Mozilla/5.0'
}

try:
    response2 = requests.post(url1, json=payload1, headers=headers2)
    print(f"Status: {response2.status_code}")
    print(f"Response: {json.dumps(response2.json(), indent=2)[:500]}")
except Exception as e:
    print(f"Error: {e}")

print("-" * 50)

# Test 3: Try with Authorization header instead
print("\nTest 3: With Authorization header")
url3 = "https://solana-mainnet.g.alchemy.com/v2/"
headers3 = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Authorization': f'Bearer {api_key}'
}

try:
    response3 = requests.post(url3 + api_key, json=payload1, headers=headers3)
    print(f"Status: {response3.status_code}")
    print(f"Response: {json.dumps(response3.json(), indent=2)[:500]}")
except Exception as e:
    print(f"Error: {e}")

print("-" * 50)

# Test 4: Exact curl equivalent
print("\nTest 4: Exact curl equivalent with minimal headers")
try:
    # Use requests.Session to have more control
    session = requests.Session()
    response4 = session.post(
        url1,
        data=json.dumps(payload1),
        headers={'Content-Type': 'application/json'}
    )
    print(f"Status: {response4.status_code}")
    print(f"Response Headers: {dict(response4.headers)}")
    print(f"Response: {json.dumps(response4.json(), indent=2)[:500]}")
except Exception as e:
    print(f"Error: {e}")

print("-" * 50)

# Test 5: Check if the issue is with JSON serialization
print("\nTest 5: Raw string body (exact curl match)")
body_str = json.dumps(payload1)
try:
    response5 = requests.post(
        url1,
        data=body_str,
        headers={'Content-Type': 'application/json'}
    )
    print(f"Status: {response5.status_code}")
    if response5.status_code == 200:
        result = response5.json()
        if 'result' in result and result['result']:
            print(f"✅ SUCCESS! Found {len(result['result'])} transactions")
            print(f"First signature: {result['result'][0]['signature'][:20]}...")
        else:
            print(f"Response: {json.dumps(result, indent=2)[:500]}")
    else:
        print(f"Response: {response5.text[:500]}")
except Exception as e:
    print(f"Error: {e}")