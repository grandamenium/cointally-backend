# middleware/rate_limiter.py

from django.core.cache import cache
from django.http import HttpResponse
import time
import logging

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """
    Middleware to rate limit API requests to prevent overloading the server.
    Specifically targets progress check endpoints which are prone to high-frequency calls.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only rate limit specific APIs that are prone to high frequency checks
        if self._should_rate_limit(request.path):
            # Get client identifier (user ID or IP address)
            client_id = self._get_client_id(request)

            # Apply rate limiting
            if not self._check_rate_limit(request.path, client_id):
                logger.warning(f"Rate limit exceeded for {client_id} on {request.path}")
                return HttpResponse(
                    '{"error": "Rate limit exceeded. Please reduce request frequency."}',
                    status=429,
                    content_type='application/json'
                )

        # Process the request normally if not rate limited
        return self.get_response(request)

    def _should_rate_limit(self, path):
        """Determine if the path should be rate limited"""
        # Rate limit individual progress checks but not bulk checks (to encourage bulk usage)
        return '/api/exchanges/' in path and '/sync_progress/' in path and not '/bulk_sync_progress/' in path

    def _get_client_id(self, request):
        """Get a unique identifier for the client"""
        # Use authenticated user ID if available
        if request.user and request.user.is_authenticated:
            return f"user_{request.user.id}"

        # Fall back to IP address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        return f"ip_{ip}"

    def _check_rate_limit(self, path, client_id):
        """
        Check if the client has exceeded rate limits
        Returns True if request should proceed, False if it should be blocked
        """
        now = int(time.time())

        # Different rate limits based on the path
        if '/sync_progress/' in path:
            # Stricter limit for individual progress checks to encourage use of bulk endpoint
            window_size = 10  # seconds
            max_requests = 3  # max 3 requests per 10 seconds per client per endpoint
        else:
            # Default limit for other rate-limited endpoints
            window_size = 60  # seconds
            max_requests = 30  # max 30 requests per minute per client per endpoint

        # Create a unique cache key for this client and endpoint
        # Extract exchange ID from path to rate limit per exchange
        exchange_id = self._extract_exchange_id(path)
        cache_key = f"ratelimit:{client_id}:{exchange_id or path}:{now // window_size}"

        # Get current count from cache
        count = cache.get(cache_key, 0)

        # Check if limit exceeded
        if count >= max_requests:
            return False

        # Increment counter
        cache.set(cache_key, count + 1, window_size)

        return True

    def _extract_exchange_id(self, path):
        """Extract exchange ID from the path if available"""
        try:
            # Pattern: /api/exchanges/{id}/sync_progress/
            parts = path.strip('/').split('/')
            if 'exchanges' in parts and parts.index('exchanges') + 1 < len(parts):
                exchange_id = parts[parts.index('exchanges') + 1]
                # Verify it's an ID (not a path segment like 'bulk_sync_progress')
                if exchange_id.isdigit() or (exchange_id.startswith('0x') and len(exchange_id) > 2):
                    return exchange_id
        except Exception:
            pass

        return None
