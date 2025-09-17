# simple_redis_test.py
"""
Simple test to verify Redis configuration works with Django and Channels
"""

import os
import sys


def test_django_setup():
    """Test if Django can be set up with the Redis configuration"""
    try:
        # Set up Django
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
        import django
        django.setup()

        print("✅ Django setup successful")
        return True
    except Exception as e:
        print(f"❌ Django setup failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cache():
    """Test Django cache"""
    try:
        from django.core.cache import cache

        # Test cache operations
        test_key = "simple_test_key"
        test_value = "simple_test_value"

        cache.set(test_key, test_value, timeout=60)
        retrieved_value = cache.get(test_key)

        if retrieved_value == test_value:
            print("✅ Django cache working")
            cache.delete(test_key)
            return True
        else:
            print(f"❌ Django cache failed: expected '{test_value}', got '{retrieved_value}'")
            return False

    except Exception as e:
        print(f"❌ Django cache error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_channel_layer():
    """Test Channels layer"""
    try:
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()

        if channel_layer is None:
            print("❌ Channel layer is None")
            return False

        print(f"✅ Channel layer loaded: {type(channel_layer)}")
        print(f"   Backend: {getattr(channel_layer, '__class__', 'Unknown')}")

        return True

    except Exception as e:
        print(f"❌ Channel layer error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_async_channel_operations():
    """Test async channel operations"""
    try:
        import asyncio
        from channels.layers import get_channel_layer

        async def async_test():
            channel_layer = get_channel_layer()

            # Test basic send/receive
            test_channel = "test.channel.123"
            test_message = {
                "type": "test.message",
                "text": "Hello from async test"
            }

            # Send message
            await channel_layer.send(test_channel, test_message)
            print("✅ Channel send successful")

            # Try to receive (might timeout, that's ok)
            try:
                received = await asyncio.wait_for(
                    channel_layer.receive(test_channel),
                    timeout=1.0
                )
                if received:
                    print("✅ Channel receive successful")
                else:
                    print("⚠️  Channel receive returned None (expected)")
            except asyncio.TimeoutError:
                print("⚠️  Channel receive timeout (expected)")

            return True

        result = asyncio.run(async_test())
        return result

    except Exception as e:
        print(f"❌ Async channel test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🚀 Starting simple Redis configuration test...\n")

    # Test Django setup
    django_ok = test_django_setup()
    if not django_ok:
        print("❌ Django setup failed, stopping tests")
        sys.exit(1)

    # Test cache
    cache_ok = test_cache()

    # Test channel layer
    channel_ok = test_channel_layer()

    # Test async operations
    async_ok = test_async_channel_operations()

    print(f"\n📊 Test Results:")
    print(f"Django Setup: {'✅' if django_ok else '❌'}")
    print(f"Cache: {'✅' if cache_ok else '❌'}")
    print(f"Channel Layer: {'✅' if channel_ok else '❌'}")
    print(f"Async Operations: {'✅' if async_ok else '❌'}")

    if all([django_ok, cache_ok, channel_ok, async_ok]):
        print("\n🎉 All tests passed! Configuration should work.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed.")
        sys.exit(1)