import logging

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from jwt import decode as jwt_decode
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

logger = logging.getLogger(__name__)

User = get_user_model()


@database_sync_to_async
def get_user_from_token(token_string):
    """
    Get user from JWT token
    """
    try:
        # Validate token
        UntypedToken(token_string)

        # Decode token to get user information
        decoded_data = jwt_decode(token_string, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = decoded_data.get('user_id')

        if user_id:
            user = User.objects.get(id=user_id)
            return user

    except (InvalidToken, TokenError, User.DoesNotExist, Exception) as e:
        logger.error(f"Error getting user from token: {e}")
        pass

    return AnonymousUser()


class JWTWebSocketMiddleware(BaseMiddleware):
    """
    Custom middleware to authenticate WebSocket connections using JWT tokens
    """

    async def __call__(self, scope, receive, send):
        # Only handle WebSocket connections
        if scope["type"] != "websocket":
            return await super().__call__(scope, receive, send)

        # Extract token from query string
        query_string = scope.get("query_string", b"").decode()
        token = None

        if query_string:
            params = {}
            for param in query_string.split("&"):
                if "=" in param:
                    key, value = param.split("=", 1)
                    params[key] = value
            token = params.get("token")

        # Get user from token
        if token:
            scope["user"] = await get_user_from_token(token)
            logger.info(f"WebSocket authentication: User {scope['user']} authenticated via JWT")
        else:
            scope["user"] = AnonymousUser()
            logger.warning("WebSocket authentication: No token provided, setting anonymous user")

        return await super().__call__(scope, receive, send)
