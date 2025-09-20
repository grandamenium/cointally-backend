#!/usr/bin/env python3
"""
Reset CDP key - Delete existing and re-upload through proper encryption channels
"""

import os
import sys
import django
import json

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.models import User, ExchangeCredential
from crypto_tax_api.services.coinbase_cdp_auth import CdpKeyEncryption, parse_cdp_key, extract_key_meta

def delete_existing_cdp_keys():
    """Delete all existing CDP keys for grandamenium user"""

    user = User.objects.filter(email='grandamenium@gmail.com').first()
    if not user:
        print("❌ User grandamenium@gmail.com not found")
        return False

    # Find and delete all Coinbase Advanced Trade credentials
    credentials = ExchangeCredential.objects.filter(
        user=user,
        exchange='coinbase_advanced'
    )

    count = credentials.count()
    if count > 0:
        print(f"🗑️  Found {count} Coinbase Advanced Trade credential(s)")
        credentials.delete()
        print("✅ Deleted existing CDP keys")
    else:
        print("ℹ️  No existing CDP keys found")

    return True

def upload_new_cdp_key():
    """Upload CDP key through proper encryption channels"""

    CDP_KEY_FILE = '/Users/jamesgoldbach/Coding/StateSpaceDesign/CoinTally/cdp_api_key (1).json'

    # Load the CDP key
    print(f"\n📄 Loading CDP key from: {CDP_KEY_FILE}")
    with open(CDP_KEY_FILE, 'r') as f:
        key_json = f.read()

    # Parse the key
    try:
        key_data = parse_cdp_key(key_json)
        print(f"✅ Parsed CDP key: {key_data.name}")

        # Extract metadata
        key_meta = extract_key_meta(key_data)
        print(f"   Organization ID: {key_meta.org_id}")
        print(f"   Key ID: {key_meta.key_id}")

    except Exception as e:
        print(f"❌ Failed to parse CDP key: {e}")
        return False

    # Get user
    user = User.objects.filter(email='grandamenium@gmail.com').first()
    if not user:
        print("❌ User grandamenium@gmail.com not found")
        return False

    # Initialize encryption
    print("\n🔐 Encrypting private key with AES-256-GCM...")
    encryption = CdpKeyEncryption()

    # Create full JSON with both name and privateKey for storage
    full_key_json = json.dumps({
        'name': key_data.name,
        'privateKey': key_data.private_key
    })

    # Encrypt the full JSON
    encrypted_key = encryption.encrypt(full_key_json)
    print(f"✅ Encrypted key (length: {len(encrypted_key)} chars)")

    # Create new credential with CDP auth type
    print("\n💾 Storing encrypted CDP key in database...")
    credential = ExchangeCredential.objects.create(
        user=user,
        exchange='coinbase_advanced',
        auth_type='cdp',
        api_key=key_meta.key_id,  # Store key_id
        api_passphrase=key_meta.org_id,  # Store org_id
        api_secret=encrypted_key,  # Store encrypted full JSON
        is_connected=True
    )

    print(f"✅ Created new ExchangeCredential (ID: {credential.id})")
    print(f"   Exchange: {credential.exchange}")
    print(f"   Auth Type: {credential.auth_type}")
    print(f"   Connected: {credential.is_connected}")

    # Verify we can decrypt it
    print("\n🔍 Verifying encryption/decryption...")
    try:
        decrypted = encryption.decrypt(encrypted_key)
        decrypted_data = json.loads(decrypted)
        if decrypted_data['name'] == key_data.name:
            print("✅ Encryption/decryption verified successfully")
        else:
            print("❌ Decryption verification failed - data mismatch")
            return False
    except Exception as e:
        print(f"❌ Decryption verification failed: {e}")
        return False

    return True

def main():
    """Main function"""
    print("=" * 60)
    print("CDP Key Reset and Re-upload")
    print("=" * 60)

    # Step 1: Delete existing keys
    print("\n📋 Step 1: Deleting existing CDP keys...")
    if not delete_existing_cdp_keys():
        return

    # Step 2: Upload new key
    print("\n📋 Step 2: Uploading new CDP key...")
    if not upload_new_cdp_key():
        return

    print("\n" + "=" * 60)
    print("✅ CDP key successfully reset and re-uploaded!")
    print("=" * 60)
    print("\n🚀 You can now test the sync functionality")

if __name__ == '__main__':
    main()