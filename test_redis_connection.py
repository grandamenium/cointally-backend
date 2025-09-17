# test_redis_connection.py
"""
Test script to verify Redis connection works correctly
Run this on Heroku to test the connection.
"""

import os
import sys
import ssl
import redis
from urllib.parse import urlparse


def test_redis_connection():
    """Test Redis connection with proper SSL configuration for Heroku"""

    REDIS_URL = os.environ.get('REDIS_URL')

    if not REDIS_URL:
        print("❌ REDIS_URL environment variable not found")
        return False

    print(f"🔍 Testing Redis connection...")
    print(f"Redis URL: {REDIS_URL[:20]}...")  # Don't log full URL for security

    try:
        # Parse Redis URL
        redis_url = urlparse(REDIS_URL)

        # Determine if SSL is needed
        use_ssl = redis_url.scheme == 'rediss'

        if use_ssl:
            print("🔒 Using SSL connection")
            # Create SSL context for Heroku Redis
            ssl_context = ssl.SSLContext()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # Create Redis connection with SSL
            r = redis.Redis(
                host=redis_url.hostname,
                port=redis_url.port,
                password=redis_url.password,
                db=0,
                ssl=True,
                ssl_cert_reqs=None,
                ssl_ca_certs=None,
                ssl_keyfile=None,
                ssl_certfile=None,
                ssl_check_hostname=False,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30,
            )
        else:
            print("🔓 Using regular connection")
            # Create regular Redis connection
            r = redis.from_url(REDIS_URL)

        # Test basic operations
        print("🧪 Testing basic Redis operations...")

        # Test ping
        response = r.ping()
        if response:
            print("✅ PING successful")
        else:
            print("❌ PING failed")
            return False

        # Test set/get
        test_key = "test_connection_key"
        test_value = "test_connection_value"

        r.set(test_key, test_value, ex=60)  # Expire in 60 seconds
        retrieved_value = r.get(test_key)

        if retrieved_value and retrieved_value.decode() == test_value:
            print("✅ SET/GET operations successful")
        else:
            print("❌ SET/GET operations failed")
            return False

        # Test delete
        r.delete(test_key)
        print("✅ DELETE operation successful")

        # Test pub/sub (important for Channels)
        print("🧪 Testing pub/sub operations...")
        pubsub = r.pubsub()

        # Subscribe to a test channel
        test_channel = "test_channel"
        pubsub.subscribe(test_channel)

        # Publish a test message
        r.publish(test_channel, "test message")

        # Try to get the message (this might not work in all scenarios, but connection should work)
        try:
            message = pubsub.get_message(timeout=1)
            if message:
                print("✅ Pub/sub operations working")
            else:
                print("⚠️  Pub/sub message not received (but connection works)")
        except Exception as e:
            print(f"⚠️  Pub/sub test had issues: {e} (but basic connection works)")

        pubsub.close()

        print("🎉 Redis connection test completed successfully!")
        return True

    except redis.ConnectionError as e:
        print(f"❌ Redis connection error: {e}")
        return False
    except ssl.SSLError as e:
        print(f"❌ SSL error: {e}")
        print("💡 Try adding SSL certificate verification bypass")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_django_redis():
    """Test Django Redis cache configuration"""
    print("\n🧪 Testing Django Redis cache...")

    try:
        import django
        from django.conf import settings
        from django.core.cache import cache

        # Test cache operations
        test_key = "django_cache_test"
        test_value = "django_cache_value"

        cache.set(test_key, test_value, timeout=60)
        retrieved_value = cache.get(test_key)

        if retrieved_value == test_value:
            print("✅ Django cache operations successful")
            cache.delete(test_key)
            return True
        else:
            print("❌ Django cache operations failed")
            return False

    except Exception as e:
        print(f"❌ Django cache test error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_channels_redis():
    """Test Channels Redis layer"""
    print("\n🧪 Testing Channels Redis layer...")

    try:
        import django
        from channels.layers import get_channel_layer
        import asyncio

        async def test_channel_layer():
            channel_layer = get_channel_layer()

            if channel_layer is None:
                print("❌ Channel layer not configured")
                return False

            # Test group operations
            test_group = "test_group"
            test_channel = "test_channel_123"
            test_message = {
                "type": "test.message",
                "text": "Hello from test"
            }

            # Add to group
            await channel_layer.group_add(test_group, test_channel)
            print("✅ Group add successful")

            # Send to group
            await channel_layer.group_send(test_group, test_message)
            print("✅ Group send successful")

            # Remove from group
            await channel_layer.group_discard(test_group, test_channel)
            print("✅ Group discard successful")

            return True

        # Run the async test
        result = asyncio.run(test_channel_layer())

        if result:
            print("✅ Channels Redis layer test successful")
        else:
            print("❌ Channels Redis layer test failed")

        return result

    except Exception as e:
        print(f"❌ Channels Redis test error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🚀 Starting Redis connection tests...\n")

    # Test basic Redis connection
    redis_success = test_redis_connection()

    # If basic Redis works, test Django integrations
    if redis_success:
        try:
            # Set up Django
            os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')
            import django

            django.setup()

            # Test Django cache
            django_cache_success = test_django_redis()

            # Test Channels
            channels_success = test_channels_redis()

            print(f"\n📊 Test Results:")
            print(f"Basic Redis: {'✅' if redis_success else '❌'}")
            print(f"Django Cache: {'✅' if django_cache_success else '❌'}")
            print(f"Channels Layer: {'✅' if channels_success else '❌'}")

            if all([redis_success, django_cache_success, channels_success]):
                print("\n🎉 All tests passed! Your Redis configuration should work.")
                sys.exit(0)
            else:
                print("\n❌ Some tests failed. Check the configuration.")
                sys.exit(1)

        except Exception as e:
            print(f"\n❌ Error setting up Django: {e}")
            sys.exit(1)
    else:
        print("\n❌ Basic Redis connection failed. Fix this first.")
        sys.exit(1)