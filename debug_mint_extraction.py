#!/usr/bin/env python3
import os
import sys
import django

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

import requests
import time
from decimal import Decimal

# Get alchemy URL using same method as blockchain_apis.py
from crypto_tax_api.utils.blockchain_apis import get_alchemy_api_key

api_key = get_alchemy_api_key('ALCHEMY_SOLANA_API_KEY')
if not api_key:
    print("No Alchemy API key found")
    exit(1)

alchemy_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
user_address = "DDYBCBCLadcSYnmrSqCznE7haZWoEKf9w8qfQ74WMMri"

# Get signatures first
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "getSignaturesForAddress",
    "params": [user_address, {"limit": 10}]
}

response = requests.post(alchemy_url, json=payload, timeout=30)
signatures_data = response.json()

print(f"API Response status: {response.status_code}")
print(f"API Response: {signatures_data}")

if 'result' not in signatures_data or not signatures_data['result']:
    print("No signatures found")
    exit(1)

signatures = [sig['signature'] for sig in signatures_data['result']]
print(f"Found {len(signatures)} signatures")

# Get transaction details for first few
for i, signature in enumerate(signatures[:5]):
    print(f"\n=== Transaction {i+1}: {signature} ===")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0
            }
        ]
    }

    response = requests.post(alchemy_url, json=payload, timeout=30)
    tx_data = response.json()

    if 'result' not in tx_data or not tx_data['result']:
        print("No transaction data found")
        continue

    transaction = tx_data['result']['transaction']
    instructions = transaction['message']['instructions']

    print(f"Found {len(instructions)} instructions")

    for j, instruction in enumerate(instructions):
        if 'parsed' in instruction:
            parsed = instruction['parsed']
            program = parsed.get('type', 'unknown')
            instruction_program = instruction.get('program', 'unknown')

            print(f"  Raw instruction {j+1}: program='{instruction_program}', type='{program}'")

            if program in ['transfer', 'transferChecked']:
                info = parsed.get('info', {})
                print(f"  Instruction {j+1} ({program}):")
                print(f"    Source: {info.get('source', 'N/A')}")
                print(f"    Destination: {info.get('destination', 'N/A')}")
                print(f"    Authority: {info.get('authority', 'N/A')}")
                print(f"    Amount: {info.get('amount', 'N/A')}")
                print(f"    Mint: {info.get('mint', 'N/A')}")  # This is the key field!
                print(f"    TokenAmount: {info.get('tokenAmount', 'N/A')}")

                # Check if user is involved
                if (info.get('source') == user_address or
                    info.get('destination') == user_address or
                    info.get('authority') == user_address):
                    print(f"    *** USER INVOLVED ***")

                    mint_address = info.get('mint', 'UNKNOWN')
                    print(f"    *** MINT ADDRESS: '{mint_address}' ***")
                    if mint_address == 'UNKNOWN':
                        print(f"    *** PROBLEM: Mint address is 'UNKNOWN' string! ***")
                    elif mint_address:
                        print(f"    *** GOOD: Found real mint address ***")
                    else:
                        print(f"    *** PROBLEM: Mint address is None/empty ***")

    time.sleep(0.1)  # Rate limiting