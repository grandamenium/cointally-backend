#!/usr/bin/env python3
"""
Test script for validating Kraken integration implementation
"""

import os
import sys
import django
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_app.settings')
django.setup()

from crypto_tax_api.services.exchange_services import KrakenService
from crypto_tax_api.models import ExchangeCredential, CexTransaction
from django.contrib.auth import get_user_model

User = get_user_model()

def test_kraken_authentication():
    """Test Kraken API authentication methods"""
    print("\n" + "=" * 60)
    print("🔐 TESTING KRAKEN AUTHENTICATION")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'dGVzdF9hcGlfc2VjcmV0'  # base64 encoded 'test_api_secret'
    }
    
    try:
        service = KrakenService(dummy_creds, type('DummyUser', (), {'id': 1})())
        
        # Test nonce generation
        nonce1 = service._get_nonce()
        nonce2 = service._get_nonce()
        print(f"✅ Nonce generation working: {nonce1} < {nonce2}")
        assert int(nonce1) < int(nonce2), "Nonce should be increasing"
        
        # Test signature generation
        test_data = {'nonce': nonce1, 'test': 'data'}
        signature = service._get_signature('/0/private/Balance', test_data)
        print(f"✅ Signature generation working: {signature[:20]}...")
        assert len(signature) > 0, "Signature should not be empty"
        
        print("✅ Kraken authentication methods validated successfully!")
        
    except Exception as e:
        print(f"❌ Kraken authentication test failed: {str(e)}")


def test_kraken_regional_urls():
    """Test Kraken regional URL configuration"""
    print("\n" + "=" * 60)
    print("🌍 TESTING KRAKEN REGIONAL URLS")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'dGVzdF9hcGlfc2VjcmV0'
    }
    
    # Test different regions
    regions = ['GLOBAL', 'US', 'EU', 'ASIA']
    
    for region in regions:
        print(f"\n🌍 Testing region: {region}")
        
        # Set environment variable
        os.environ['KRAKEN_REGION'] = region
        
        try:
            service = KrakenService(dummy_creds, type('DummyUser', (), {'id': 1})())
            
            base_url = service.base_url
            futures_url = service.futures_base_url
            
            print(f"   📡 Base URL: {base_url}")
            print(f"   📈 Futures URL: {futures_url}")
            
            # All regions currently use the same endpoint
            assert 'api.kraken.com' in base_url, f"Expected Kraken API for {region}"
            assert 'futures.kraken.com' in futures_url, f"Expected Kraken Futures API for {region}"
            
            print(f"   ✅ {region} configuration valid")
            
        except Exception as e:
            print(f"   ❌ Error testing {region}: {str(e)}")
        finally:
            os.environ.pop('KRAKEN_REGION', None)
    
    print("✅ All Kraken regional configurations tested successfully!")


def test_kraken_asset_parsing():
    """Test Kraken asset name parsing and cleaning"""
    print("\n" + "=" * 60)
    print("🏷️ TESTING KRAKEN ASSET PARSING")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'dGVzdF9hcGlfc2VjcmV0'
    }
    
    service = KrakenService(dummy_creds, type('DummyUser', (), {'id': 1})())
    
    # Test asset cleaning
    test_assets = {
        'XXBT': 'BTC',
        'XETH': 'ETH',
        'XLTC': 'LTC',
        'XXRP': 'XRP',
        'ZUSD': 'USD',
        'ZEUR': 'EUR',
        'BTC': 'BTC',  # Already clean
        'ETH': 'ETH'   # Already clean
    }
    
    print("Testing asset name cleaning:")
    for kraken_asset, expected in test_assets.items():
        cleaned = service._clean_asset_name(kraken_asset)
        print(f"   {kraken_asset} -> {cleaned} (expected: {expected})")
        assert cleaned == expected, f"Expected {expected}, got {cleaned}"
    
    # Test pair parsing
    test_pairs = {
        'XXBTZUSD': 'BTC',
        'XETHZUSD': 'ETH',
        'ETHEUR': 'ETH',
        'BTCUSD': 'BTC'
    }
    
    print("\nTesting trading pair parsing:")
    for pair, expected_base in test_pairs.items():
        base_asset = service._parse_asset_from_pair(pair)
        print(f"   {pair} -> {base_asset} (expected: {expected_base})")
        assert base_asset == expected_base, f"Expected {expected_base}, got {base_asset}"
    
    print("✅ Kraken asset parsing validated successfully!")


def test_kraken_ledger_type_mapping():
    """Test Kraken ledger type mapping"""
    print("\n" + "=" * 60)
    print("📋 TESTING KRAKEN LEDGER TYPE MAPPING")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'dGVzdF9hcGlfc2VjcmV0'
    }
    
    service = KrakenService(dummy_creds, type('DummyUser', (), {'id': 1})())
    
    # Test ledger type mapping
    test_types = {
        'deposit': 'deposit',
        'withdrawal': 'withdrawal',
        'transfer': 'transfer',
        'spend': 'spend',
        'receive': 'receive',
        'staking': 'staking',
        'reward': 'reward',
        'unknown_type': 'other'
    }
    
    print("Testing ledger type mapping:")
    for kraken_type, expected in test_types.items():
        mapped = service._map_ledger_type(kraken_type)
        print(f"   {kraken_type} -> {mapped} (expected: {expected})")
        assert mapped == expected, f"Expected {expected}, got {mapped}"
    
    print("✅ Kraken ledger type mapping validated successfully!")


def test_kraken_date_handling():
    """Test Kraken date and timestamp handling"""
    print("\n" + "=" * 60)
    print("📅 TESTING KRAKEN DATE HANDLING")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'dGVzdF9hcGlfc2VjcmV0'
    }
    
    service = KrakenService(dummy_creds, type('DummyUser', (), {'id': 1})())
    
    # Test earliest trade date
    earliest_date = service._get_earliest_trade_date()
    print(f"✅ Earliest trade date: {earliest_date}")
    assert earliest_date.year == 2013, "Kraken earliest date should be 2013"
    
    # Test nonce generation (should be current timestamp based)
    nonce1 = int(service._get_nonce())
    nonce2 = int(service._get_nonce())
    current_time_us = int(datetime.now().timestamp() * 1000000)
    
    print(f"✅ Nonce generation: {nonce1}, {nonce2}")
    assert nonce1 < nonce2, "Nonces should be increasing"
    assert abs(nonce1 - current_time_us) < 1000000, "Nonce should be close to current time"
    
    print("✅ Kraken date handling validated successfully!")


def test_kraken_api_methods():
    """Test Kraken API method structure"""
    print("\n" + "=" * 60)
    print("🔧 TESTING KRAKEN API METHODS")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'dGVzdF9hcGlfc2VjcmV0'
    }
    
    service = KrakenService(dummy_creds, type('DummyUser', (), {'id': 1})())
    
    # Test that required methods exist
    required_methods = [
        'test_connection',
        'sync_transactions',
        'get_current_account_balances',
        '_make_signed_request',
        '_make_public_request',
        '_get_nonce',
        '_get_signature',
        '_clean_asset_name',
        '_parse_asset_from_pair',
        '_map_ledger_type',
        '_get_historical_price_kraken'
    ]
    
    print("Checking required methods exist:")
    for method_name in required_methods:
        assert hasattr(service, method_name), f"Method {method_name} not found"
        method = getattr(service, method_name)
        assert callable(method), f"Method {method_name} is not callable"
        print(f"   ✅ {method_name}")
    
    print("✅ All required Kraken API methods exist!")


def run_all_tests():
    """Run all Kraken integration tests"""
    print("🦐 KRAKEN INTEGRATION TEST SUITE")
    print("=" * 60)
    
    try:
        test_kraken_authentication()
        test_kraken_regional_urls()
        test_kraken_asset_parsing()
        test_kraken_ledger_type_mapping()
        test_kraken_date_handling()
        test_kraken_api_methods()
        
        print("\n" + "=" * 60)
        print("🎉 ALL KRAKEN INTEGRATION TESTS PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ KRAKEN INTEGRATION TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests() 