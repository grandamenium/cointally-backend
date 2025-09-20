#!/usr/bin/env python
"""
Script to upload a new CDP key with trade permissions
Replace the CDP_KEY_JSON with your actual CDP key data
"""

import os
import sys
import django
import json

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.models import ExchangeCredential, User

# IMPORTANT: Replace this with your actual CDP key JSON content
CDP_KEY_JSON = """
{
    "name": "organizations/YOUR_ORG_ID/apiKeys/YOUR_KEY_ID",
    "privateKey": "-----BEGIN EC PRIVATE KEY-----\\nYOUR_PRIVATE_KEY_HERE\\n-----END EC PRIVATE KEY-----"
}
"""

def main():
    """Upload the new CDP key"""
    try:
        # Parse the CDP JSON
        cdp_data = json.loads(CDP_KEY_JSON)

        # Get the first user
        user = User.objects.first()
        if not user:
            print("No user found. Please create a user first.")
            return False

        print(f"Using user: {user.username}")

        # Extract org_id and key_id from the name
        import re
        match = re.match(r'organizations/([^/]+)/apiKeys/([^/]+)', cdp_data['name'])
        if not match:
            print("Invalid key name format")
            return False

        org_id, key_id = match.groups()

        # Delete old credentials
        deleted = ExchangeCredential.objects.filter(
            user=user,
            exchange='coinbase_advanced'
        ).delete()

        if deleted[0] > 0:
            print(f"Deleted {deleted[0]} old CDP credential(s)")

        # Create new credential with CDP auth type
        credential = ExchangeCredential.objects.create(
            user=user,
            exchange='coinbase_advanced',
            api_key=key_id,
            api_passphrase=org_id,
            api_secret=CDP_KEY_JSON,  # Store the full JSON
            auth_type='cdp',
            is_active=True,
            is_connected=True
        )

        print(f"✅ Created new CDP credential with ID: {credential.id}")
        print(f"   Key ID: {key_id}")
        print(f"   Org ID: {org_id}")
        print(f"   Auth Type: {credential.auth_type}")

        # Test decryption
        try:
            decrypted = credential.get_decrypted_credentials()
            cdp_test = json.loads(decrypted['api_secret'])
            print(f"✅ Successfully decrypted and parsed CDP key")
            print(f"   Key name: {cdp_test['name']}")
            print(f"   Has private key: {'privateKey' in cdp_test}")
        except Exception as e:
            print(f"❌ Error testing decryption: {e}")

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("CDP Key Upload Script")
    print("=" * 60)
    print("\n⚠️  IMPORTANT: Edit this file and replace CDP_KEY_JSON with your actual CDP key data!")
    print("   The key should have 'trade' permissions enabled.\n")
    print("=" * 60)

    if "YOUR_ORG_ID" in CDP_KEY_JSON:
        print("\n❌ ERROR: You need to edit this file first!")
        print("   Replace CDP_KEY_JSON with your actual CDP key data.")
        print("   The JSON should contain 'name' and 'privateKey' fields.")
    else:
        if main():
            print("\n✅ CDP key uploaded successfully!")
            print("\nYou can now:")
            print("1. Go to http://localhost:3000/premium-dashboard")
            print("2. Click on 'Sync' for Coinbase Advanced Trade")
            print("3. Or run: python3 test_cdp_upload.py")
        else:
            print("\n❌ Failed to upload CDP key")