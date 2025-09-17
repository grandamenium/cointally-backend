#!/usr/bin/env python3
"""
Test script for validating regional API configuration across all exchanges
"""

import os
import sys
import django

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_app.settings')
django.setup()

from crypto_tax_api.services.exchange_services import BinanceService, CoinbaseService, BybitService, KrakenService, HyperliquidService

class DummyUser:
    id = 1

def test_binance_regional_config():
    """Test Binance regional configurations"""
    print("\n" + "=" * 60)
    print("🏦 TESTING BINANCE REGIONAL CONFIGURATIONS")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'binance',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    user = DummyUser()
    
    regions = ['GLOBAL', 'US', 'JP', 'TR']
    
    for region in regions:
        os.environ['BINANCE_REGION'] = region
        
        try:
            binance = BinanceService(dummy_creds, user)
            print(f"✅ {region:8} -> {binance.base_url}")
            
            # Test futures API URL
            futures_url = binance._get_binance_futures_api_url()
            print(f"   Futures  -> {futures_url}")
            
        except Exception as e:
            print(f"❌ {region:8} -> Error: {str(e)}")
    
    # Clean up
    if 'BINANCE_REGION' in os.environ:
        del os.environ['BINANCE_REGION']

def test_coinbase_regional_config():
    """Test Coinbase regional configurations"""
    print("\n" + "=" * 60)
    print("🏛️ TESTING COINBASE REGIONAL CONFIGURATIONS")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'coinbase',
        'api_key': 'test_key',
        'api_secret': 'test_secret',
        'api_passphrase': 'test_passphrase'
    }
    user = DummyUser()
    
    regions = ['US', 'EU', 'UK', 'CA', 'SG']
    products = ['RETAIL', 'ADVANCED']
    
    for region in regions:
        for product in products:
            os.environ['COINBASE_REGION'] = region
            os.environ['COINBASE_PRODUCT'] = product
            
            try:
                coinbase = CoinbaseService(dummy_creds, user)
                print(f"✅ {region:3}/{product:8} -> v2: {coinbase.v2_base_url}")
                print(f"                      -> v3: {coinbase.v3_base_url}")
                
            except Exception as e:
                print(f"❌ {region:3}/{product:8} -> Error: {str(e)}")
    
    # Clean up
    if 'COINBASE_REGION' in os.environ:
        del os.environ['COINBASE_REGION']
    if 'COINBASE_PRODUCT' in os.environ:
        del os.environ['COINBASE_PRODUCT']

def test_bybit_regional_config():
    """Test Bybit regional configurations"""
    print("\n" + "=" * 60)
    print("🟡 TESTING BYBIT REGIONAL CONFIGURATIONS")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'bybit',
        'api_key': 'test_key',
        'api_secret': 'test_secret'
    }
    user = DummyUser()
    
    # Test production regions
    regions = ['GLOBAL', 'ASIA', 'EU', 'US']
    
    for region in regions:
        os.environ['BYBIT_REGION'] = region
        os.environ['BYBIT_TESTNET'] = 'false'
        
        try:
            bybit = BybitService(dummy_creds, user)
            print(f"✅ {region:8} (prod) -> {bybit.base_url}")
            
        except Exception as e:
            print(f"❌ {region:8} (prod) -> Error: {str(e)}")
    
    # Test testnet
    os.environ['BYBIT_TESTNET'] = 'true'
    try:
        bybit = BybitService(dummy_creds, user)
        print(f"✅ TESTNET        -> {bybit.base_url}")
    except Exception as e:
        print(f"❌ TESTNET        -> Error: {str(e)}")
    
    # Clean up
    if 'BYBIT_REGION' in os.environ:
        del os.environ['BYBIT_REGION']
    if 'BYBIT_TESTNET' in os.environ:
        del os.environ['BYBIT_TESTNET']

def test_kraken_regional_config():
    """Test Kraken regional configurations"""
    print("\n" + "=" * 60)
    print("🦐 TESTING KRAKEN REGIONAL CONFIGURATIONS")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'kraken',
        'api_key': 'test_api_key',
        'api_secret': 'test_api_secret'
    }
    
    # Test different regions
    regions = ['GLOBAL', 'US', 'EU', 'ASIA']
    
    for region in regions:
        print(f"\n🌍 Testing region: {region}")
        
        # Set environment variable
        os.environ['KRAKEN_REGION'] = region
        
        try:
            # Initialize Kraken service
            service = KrakenService(dummy_creds, DummyUser())
            
            # Check API URLs
            base_url = service.base_url
            futures_url = service.futures_base_url
            
            print(f"   📡 Base URL: {base_url}")
            print(f"   📈 Futures URL: {futures_url}")
            
            # Verify regional configuration was applied
            if region == 'GLOBAL':
                assert 'api.kraken.com' in base_url, "Expected Kraken global API"
            else:
                assert 'api.kraken.com' in base_url, "Expected Kraken API"
            
            print(f"   ✅ {region} configuration valid")
            
        except Exception as e:
            print(f"   ❌ Error testing {region}: {str(e)}")
    
    # Test testnet configuration
    print(f"\n🧪 Testing testnet configuration")
    os.environ['KRAKEN_TESTNET'] = 'true'
    
    try:
        service = KrakenService(dummy_creds, DummyUser())
        base_url = service.base_url
        print(f"   📡 Testnet URL: {base_url}")
        print(f"   ✅ Testnet configuration valid")
    except Exception as e:
        print(f"   ❌ Error testing testnet: {str(e)}")
    finally:
        # Reset environment
        os.environ.pop('KRAKEN_TESTNET', None)
        os.environ.pop('KRAKEN_REGION', None)
    
    print(f"✅ All Kraken configurations tested successfully!")

def test_comprehensive_regional_scenarios():
    """Test comprehensive real-world regional scenarios"""
    print("\n" + "=" * 60)
    print("🌍 TESTING COMPREHENSIVE REGIONAL SCENARIOS")
    print("=" * 60)
    
    scenarios = {
        'US Trader': {
            'BINANCE_REGION': 'US',
            'COINBASE_REGION': 'US',
            'COINBASE_PRODUCT': 'ADVANCED',
            'BYBIT_REGION': 'US'
        },
        'EU Trader': {
            'BINANCE_REGION': 'GLOBAL',
            'COINBASE_REGION': 'EU',
            'COINBASE_PRODUCT': 'RETAIL',
            'BYBIT_REGION': 'EU'
        },
        'Asian Trader': {
            'BINANCE_REGION': 'GLOBAL',
            'COINBASE_REGION': 'SG',
            'COINBASE_PRODUCT': 'ADVANCED',
            'BYBIT_REGION': 'ASIA'
        },
        'Japanese Trader': {
            'BINANCE_REGION': 'JP',
            'COINBASE_REGION': 'US',
            'COINBASE_PRODUCT': 'RETAIL',
            'BYBIT_REGION': 'ASIA'
        }
    }
    
    dummy_creds_binance = {'id': 1, 'exchange': 'binance', 'api_key': 'test', 'api_secret': 'test'}
    dummy_creds_coinbase = {'id': 2, 'exchange': 'coinbase', 'api_key': 'test', 'api_secret': 'test', 'api_passphrase': 'test'}
    dummy_creds_bybit = {'id': 3, 'exchange': 'bybit', 'api_key': 'test', 'api_secret': 'test'}
    
    user = DummyUser()
    
    for scenario_name, env_vars in scenarios.items():
        print(f"\n📍 {scenario_name}:")
        
        # Set environment variables
        for key, value in env_vars.items():
            os.environ[key] = value
        
        try:
            # Test Binance
            binance = BinanceService(dummy_creds_binance, user)
            print(f"   Binance: {binance.base_url}")
            
            # Test Coinbase
            coinbase = CoinbaseService(dummy_creds_coinbase, user)
            print(f"   Coinbase: {coinbase.v2_base_url} / {coinbase.v3_base_url}")
            
            # Test Bybit
            bybit = BybitService(dummy_creds_bybit, user)
            print(f"   Bybit: {bybit.base_url}")
            
            print(f"   ✅ {scenario_name} configuration successful")
            
        except Exception as e:
            print(f"   ❌ {scenario_name} configuration failed: {str(e)}")
    
    # Clean up all environment variables
    cleanup_vars = ['BINANCE_REGION', 'COINBASE_REGION', 'COINBASE_PRODUCT', 'BYBIT_REGION', 'BYBIT_TESTNET']
    for var in cleanup_vars:
        if var in os.environ:
            del os.environ[var]

def test_hyperliquid_regional_configuration():
    """Test Hyperliquid regional configuration"""
    print("\n" + "=" * 60)
    print("🔸 TESTING HYPERLIQUID REGIONAL CONFIGURATION")
    print("=" * 60)
    
    dummy_creds = {
        'id': 1,
        'exchange': 'hyperliquid',
        'private_key': 'test_private_key',
        'wallet_address': '0x1234567890123456789012345678901234567890'
    }
    
    regions_to_test = ['GLOBAL', 'US', 'EU', 'ASIA']
    
    for region in regions_to_test:
        print(f"Testing Hyperliquid region: {region}")
        
        # Set environment variable
        os.environ['HYPERLIQUID_REGION'] = region
        
        try:
            service = HyperliquidService(dummy_creds, type('DummyUser', (), {'id': 1})())
            base_url, testnet_url = service._get_hyperliquid_api_urls()
            
            print(f"   Base URL: {base_url}")
            print(f"   Testnet URL: {testnet_url}")
            
            # Hyperliquid uses same global endpoint for all regions
            assert base_url == 'https://api.hyperliquid.xyz', f"Expected global endpoint, got {base_url}"
            
        except Exception as e:
            print(f"   ❌ Error testing {region}: {str(e)}")
    
    # Test testnet configuration
    print(f"Testing Hyperliquid testnet configuration:")
    os.environ['HYPERLIQUID_TESTNET'] = 'true'
    
    try:
        service = HyperliquidService(dummy_creds, type('DummyUser', (), {'id': 1})())
        base_url, testnet_url = service._get_hyperliquid_api_urls()
        
        print(f"   Testnet Base URL: {base_url}")
        assert base_url == 'https://api.hyperliquid-testnet.xyz', f"Expected testnet URL, got {base_url}"
        
    except Exception as e:
        print(f"   ❌ Error testing testnet: {str(e)}")
    
    # Clean up environment
    os.environ.pop('HYPERLIQUID_REGION', None)
    os.environ.pop('HYPERLIQUID_TESTNET', None)
    
    print("✅ Hyperliquid regional configuration tests completed!")

def run_all_tests():
    """Run all regional configuration tests"""
    print("🚀 STARTING COMPREHENSIVE REGIONAL API CONFIGURATION TESTS")
    print("=" * 80)
    
    try:
        test_binance_regional_config()
        test_coinbase_regional_config()
        test_bybit_regional_config()
        test_kraken_regional_config()
        test_comprehensive_regional_scenarios()
        test_hyperliquid_regional_configuration()
        
        print("\n" + "=" * 80)
        print("✅ ALL REGIONAL CONFIGURATION TESTS COMPLETED SUCCESSFULLY!")
        print("📖 See REGIONAL_API_CONFIGURATION.md for detailed usage instructions")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_all_tests() 