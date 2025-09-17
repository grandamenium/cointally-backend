#!/usr/bin/env python
"""
Debug script to help identify Django/WebSocket startup issues
Run this before starting Daphne to check your configuration
"""

import os
import sys
import django
from pathlib import Path


def check_environment():
    """Check basic environment setup"""
    print("=== Environment Check ===")
    print(f"Python version: {sys.version}")
    print(f"Current directory: {os.getcwd()}")
    print(f"Python path: {sys.path[:3]}...")  # First 3 entries

    # Check if manage.py exists
    if Path('manage.py').exists():
        print("✓ manage.py found")
    else:
        print("❌ manage.py not found - make sure you're in the Django project root")
        return False

    return True


def check_django_setup():
    """Check Django configuration"""
    print("\n=== Django Setup Check ===")

    try:
        # Set Django settings
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')

        # Setup Django
        django.setup()
        print("✓ Django setup successful")

        # Check settings
        from django.conf import settings
        print(f"✓ Settings loaded: {settings.SETTINGS_MODULE}")
        print(f"✓ Debug mode: {settings.DEBUG}")
        print(f"✓ Installed apps: {len(settings.INSTALLED_APPS)} apps")

        # Check for required apps
        required_apps = ['channels', 'crypto_tax_api']
        for app in required_apps:
            if any(app in installed_app for installed_app in settings.INSTALLED_APPS):
                print(f"✓ {app} found in INSTALLED_APPS")
            else:
                print(f"❌ {app} missing from INSTALLED_APPS")

        return True

    except Exception as e:
        print(f"❌ Django setup failed: {e}")
        return False


def check_models():
    """Check if models can be imported"""
    print("\n=== Models Check ===")

    try:
        from crypto_tax_api.models import ExchangeCredential
        print("✓ Models imported successfully")
        return True
    except Exception as e:
        print(f"❌ Model import failed: {e}")
        return False


def check_websocket_consumer():
    """Check if WebSocket consumer can be imported"""
    print("\n=== WebSocket Consumer Check ===")

    try:
        from crypto_tax_api.websockets.consumers import ProgressConsumer
        print("✓ WebSocket consumer imported successfully")
        return True
    except Exception as e:
        print(f"❌ WebSocket consumer import failed: {e}")
        print("   Make sure the file exists at: crypto_tax_api/websockets/consumers.py")
        return False


def check_asgi():
    """Check ASGI configuration"""
    print("\n=== ASGI Configuration Check ===")

    try:
        from crypto_tax_project.asgi import application
        print("✓ ASGI application imported successfully")
        print(f"✓ Application type: {type(application).__name__}")
        return True
    except Exception as e:
        print(f"❌ ASGI application import failed: {e}")
        return False


def check_redis():
    """Check Redis connection"""
    print("\n=== Redis Check ===")

    try:
        import redis
        r = redis.Redis(host='127.0.0.1', port=6379, db=0)
        r.ping()
        print("✓ Redis connection successful")
        return True
    except ImportError:
        print("❌ Redis package not installed: pip install redis")
        return False
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("   Make sure Redis is running: brew services start redis")
        return False


def check_channels():
    """Check Django Channels configuration"""
    print("\n=== Channels Check ===")

    try:
        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()

        if channel_layer is None:
            print("❌ No channel layer configured")
            return False

        print(f"✓ Channel layer configured: {type(channel_layer).__name__}")
        return True
    except Exception as e:
        print(f"❌ Channels check failed: {e}")
        return False


def main():
    """Run all checks"""
    print("Django/WebSocket Configuration Debug")
    print("=" * 40)

    checks = [
        check_environment,
        check_django_setup,
        check_models,
        check_websocket_consumer,
        check_asgi,
        check_redis,
        check_channels,
    ]

    results = []
    for check in checks:
        try:
            result = check()
            results.append(result)
        except Exception as e:
            print(f"❌ Check failed with exception: {e}")
            results.append(False)

    print("\n" + "=" * 40)
    print("Summary:")
    passed = sum(results)
    total = len(results)
    print(f"Checks passed: {passed}/{total}")

    if passed == total:
        print("✓ All checks passed! You should be able to start Daphne now.")
        print("\nStart command:")
        print("daphne -b 127.0.0.1 -p 8000 crypto_tax_project.asgi:application")
    else:
        print("❌ Some checks failed. Please fix the issues above before starting Daphne.")

        print("\nCommon fixes:")
        print("1. Install missing packages: pip install channels channels_redis redis daphne")
        print("2. Start Redis: brew services start redis")
        print("3. Check file structure and imports")
        print("4. Run Django migrations: python manage.py migrate")


if __name__ == "__main__":
    main()