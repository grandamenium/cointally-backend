#!/usr/bin/env python3

"""
Test script to validate the new earliest trade date functionality
"""

import os
import sys
import django
from datetime import datetime, timezone

# Add the backend directory to Python path
sys.path.insert(0, '/Users/mustafa/Projects/crypto-tax-app/backend')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
django.setup()

from crypto_tax_api.models import ExchangeCredential
from crypto_tax_api.services.exchange_services import ExchangeServiceFactory

def test_earliest_trade_date():
    """Test the new earliest trade date functionality"""
    print("🔍 Testing Earliest Trade Date Functionality")
    print("=" * 60)
    
    try:
        # Get the first Binance credential
        binance_credential = ExchangeCredential.objects.filter(exchange='binance').first()
        
        if not binance_credential:
            print("❌ No Binance credentials found")
            return
            
        print(f"📊 Testing for user: {binance_credential.user.email}")
        
        # Initialize service
        service = ExchangeServiceFactory.get_service('binance', binance_credential.user)
        
        # Test connection first
        success, message = service.test_connection()
        if not success:
            print(f"❌ Connection failed: {message}")
            return
            
        print("✅ Connection successful!")
        
        # Test the new earliest trade date method
        print("\n🔍 Testing _get_earliest_trade_date() method...")
        earliest_date = service._get_earliest_trade_date()
        
        if earliest_date:
            print(f"✅ Earliest trade date found: {earliest_date}")
            print(f"   📅 Formatted: {earliest_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            
            # Calculate how far back this goes
            days_ago = (datetime.now(timezone.utc) - earliest_date).days
            print(f"   ⏰ This was {days_ago} days ago")
            
            if days_ago > 365:
                print(f"   🎯 This replaces the old 1-year fallback (saved {days_ago - 365} days of unnecessary syncing)")
            else:
                print(f"   📝 This is within the 1-year range (account is relatively new)")
                
        else:
            print("⚠️  No earliest trade date found - will fall back to 1 year ago")
            
        # Test last sync timestamp
        print("\n🔍 Testing last sync logic...")
        last_sync = service._get_last_sync_timestamp()
        
        if last_sync:
            last_sync_date = datetime.fromtimestamp(last_sync / 1000, tz=timezone.utc)
            print(f"✅ Last sync timestamp: {last_sync_date}")
            print("   📝 Regular 'Sync Now' would continue from this date")
        else:
            print("⚪ No previous sync found")
            print("   📝 Regular 'Sync Now' would use earliest trade date for initial sync")
            
        # Simulate the logic for both sync types
        print("\n🎯 SIMULATING SYNC BEHAVIOR:")
        print("-" * 40)
        
        print("📱 'Sync Now' button (force_full_sync=False):")
        if last_sync:
            sync_from = datetime.fromtimestamp(last_sync / 1000, tz=timezone.utc)
            print(f"   ➡️  Would sync from: {sync_from} (last sync + 1ms)")
        elif earliest_date:
            print(f"   ➡️  Would sync from: {earliest_date} (earliest trade - initial sync)")
        else:
            fallback_date = datetime.now(timezone.utc).replace(year=datetime.now().year - 1)
            print(f"   ➡️  Would sync from: {fallback_date} (1 year fallback)")
            
        print("\n🚀 'Force Full Sync' button (force_full_sync=True):")
        if earliest_date:
            print(f"   ➡️  Would sync from: {earliest_date} (earliest trade)")
        else:
            fallback_date = datetime.now(timezone.utc).replace(year=datetime.now().year - 1)
            print(f"   ➡️  Would sync from: {fallback_date} (1 year fallback)")
            
        print(f"\n✅ Test completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_earliest_trade_date() 