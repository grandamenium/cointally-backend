"""
ASGI config for crypto_tax_project project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/asgi/
"""

import os
from dotenv import load_dotenv

# Load environment variables FIRST - before any Django imports
load_dotenv()

from django.core.asgi import get_asgi_application

# Set Django settings module FIRST
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'crypto_tax_project.settings')

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

# NOW we can safely import Django Channels and our consumers
from channels.routing import ProtocolTypeRouter, URLRouter
from django.urls import path
from crypto_tax_api.websockets.consumers import ProgressConsumer
from crypto_tax_api.websockets.middleware import JWTWebSocketMiddleware

# WebSocket URL patterns
websocket_urlpatterns = [
    path('ws/progress/', ProgressConsumer.as_asgi()),
]

application = ProtocolTypeRouter({
    # Django's ASGI application to handle traditional HTTP requests
    "http": django_asgi_app,
    
    # WebSocket handler with JWT authentication
    "websocket": JWTWebSocketMiddleware(
        URLRouter(
            websocket_urlpatterns
        )
    ),
})
