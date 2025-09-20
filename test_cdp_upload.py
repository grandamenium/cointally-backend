#!/usr/bin/env python
"""
Test script to upload CDP key and test Coinbase Advanced Trade sync
"""

import os
import sys
import django
import json

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.models import ExchangeCredential, User

# Test CDP key JSON (you'll need to replace this with your actual CDP key)
CDP_KEY_JSON = {
    "name": "organizations/45b8c9ce-a0d3-4149-977f-1fa0b1631639/apiKeys/60243a3e-344d-4d95-a047-b26a9201d6e5",
    "privateKey": "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEILMs4WOUzk2706fp/t9yb9Z0v93EFiCGCZsv+OVMOag3oAoGCCqGSM49\nAwEHoUQDQgAEhFq6hYyxaWc3IKo9IWf7/E2PJbxDFQmIucSSRCwa4LDFIXaoiy4S\nrpJ0tiRX4N5gDSCKz1PdX8tIPdmQWVB3Jg==\n-----END EC PRIVATE KEY-----"
}

def upload_cdp_key():
    """Upload CDP key to the database"""
    try:
        # Get the first user (or create one for testing)
        user = User.objects.first()
        if not user:
            print("No user found. Please create a user first.")
            return False

        print(f"Using user: {user.username}")

        # Convert CDP key to JSON string
        cdp_json_str = json.dumps(CDP_KEY_JSON)

        # Create or update the credential
        credential, created = ExchangeCredential.objects.update_or_create(
            user=user,
            exchange='coinbase_advanced',
            defaults={
                'api_key': '60243a3e-344d-4d95-a047-b26a9201d6e5',  # key_id
                'api_passphrase': '45b8c9ce-a0d3-4149-977f-1fa0b1631639',  # org_id
                'api_secret': cdp_json_str,  # Full CDP JSON
                'auth_type': 'cdp',
                'is_active': True,
                'is_connected': True
            }
        )

        action = "Created" if created else "Updated"
        print(f"{action} CDP credential with ID: {credential.id}")

        # Verify the credential was saved correctly
        saved_cred = ExchangeCredential.objects.get(id=credential.id)
        print(f"Auth type: {saved_cred.auth_type}")
        print(f"Exchange: {saved_cred.exchange}")

        # Try to decrypt and parse the saved credentials
        decrypted = saved_cred.get_decrypted_credentials()
        print(f"Successfully decrypted credentials")

        # Check if the CDP JSON is properly stored
        try:
            cdp_data = json.loads(decrypted['api_secret'])
            print(f"CDP key name: {cdp_data['name']}")
            print(f"Private key present: {'privateKey' in cdp_data}")
        except json.JSONDecodeError:
            print("Note: CDP JSON not stored in api_secret field, using fallback method")

        return True

    except Exception as e:
        print(f"Error uploading CDP key: {e}")
        return False

def test_sync():
    """Test the sync functionality"""
    try:
        from crypto_tax_api.services.exchange_services import ExchangeServiceFactory

        user = User.objects.first()
        if not user:
            print("No user found.")
            return False

        print("\nTesting sync functionality...")

        # Get the service
        service = ExchangeServiceFactory.get_service('coinbase_advanced', user)

        # Test connection
        print("Testing connection...")
        success, message = service.test_connection()
        print(f"Connection test: {success} - {message}")

        if success:
            # Try to sync a small date range
            print("\nAttempting to sync transactions...")
            from datetime import datetime, timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            count = service.sync_transactions(
                start_date=start_date,
                end_date=end_date
            )
            print(f"Synced {count} transactions")

        return success

    except Exception as e:
        print(f"Error testing sync: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("CDP Key Upload and Test Script")
    print("=" * 50)

    # Upload the CDP key
    if upload_cdp_key():
        print("\n✓ CDP key uploaded successfully")

        # Test the sync
        if test_sync():
            print("\n✓ Sync test completed successfully")
        else:
            print("\n✗ Sync test failed")
    else:
        print("\n✗ Failed to upload CDP key")