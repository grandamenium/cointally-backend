"""
Coinbase Advanced Trading API Integration with CDP Authentication
Implements JWT-based authentication using CDP keys for secure API access
"""

import json
import time
import secrets
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from decimal import Decimal
import re
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
import httpx
import os
import base64
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class CdpKeyData:
    """CDP API Key data structure"""
    name: str
    private_key: str


@dataclass
class CdpKeyMeta:
    """CDP Key metadata"""
    key_id: str
    org_id: str


class CdpKeyEncryption:
    """Handles encryption/decryption of CDP keys"""

    def __init__(self):
        # Get encryption key from settings or environment
        self.master_key = settings.CDP_ENCRYPTION_KEY if hasattr(settings, 'CDP_ENCRYPTION_KEY') else os.environ.get('CDP_ENCRYPTION_KEY')
        if not self.master_key:
            logger.warning("CDP_ENCRYPTION_KEY not set, using default (NOT SECURE FOR PRODUCTION)")
            self.master_key = "CHANGE_THIS_IN_PRODUCTION_32BYTE"

        # Ensure key is 32 bytes
        if len(self.master_key) < 32:
            self.master_key = self.master_key.ljust(32, '0')[:32]
        else:
            self.master_key = self.master_key[:32]

    def encrypt(self, plaintext: str) -> str:
        """Encrypt sensitive data using AES-256-GCM"""
        # Generate a random 96-bit IV for GCM
        iv = os.urandom(12)

        # Create cipher
        encryptor = Cipher(
            algorithms.AES(self.master_key.encode()),
            modes.GCM(iv),
            backend=default_backend()
        ).encryptor()

        # Encrypt the plaintext
        ciphertext = encryptor.update(plaintext.encode()) + encryptor.finalize()

        # Combine IV + tag + ciphertext and encode as base64
        combined = iv + encryptor.tag + ciphertext
        return base64.b64encode(combined).decode('utf-8')

    def decrypt(self, encrypted: str) -> str:
        """Decrypt sensitive data with proper base64 padding - FIXED VERSION"""
        # Decode from base64
        # Ensure the base64 string is properly padded
        encrypted = encrypted.strip()
        missing_padding = len(encrypted) % 4
        if missing_padding:
            encrypted += '=' * (4 - missing_padding)

        combined = base64.b64decode(encrypted)

        # Extract components
        iv = combined[:12]
        tag = combined[12:28]
        ciphertext = combined[28:]

        # Create decryptor
        decryptor = Cipher(
            algorithms.AES(self.master_key.encode()),
            modes.GCM(iv, tag),
            backend=default_backend()
        ).decryptor()

        # Decrypt
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return plaintext.decode('utf-8')


def parse_cdp_key(json_string: str) -> CdpKeyData:
    """Parse CDP key JSON file"""
    try:
        data = json.loads(json_string)

        if 'name' not in data or 'privateKey' not in data:
            raise ValueError('Invalid CDP key format: missing name or privateKey')

        # Validate key name format
        match = re.match(r'organizations/([^/]+)/apiKeys/([^/]+)', data['name'])
        if not match:
            raise ValueError('Invalid key name format')

        return CdpKeyData(
            name=data['name'],
            private_key=data['privateKey']
        )
    except json.JSONDecodeError as e:
        raise ValueError(f'Invalid JSON format: {e}')


def extract_key_meta(key_data: CdpKeyData) -> CdpKeyMeta:
    """Extract metadata from CDP key"""
    match = re.match(r'organizations/([^/]+)/apiKeys/([^/]+)', key_data.name)
    if match:
        org_id, key_id = match.groups()
        return CdpKeyMeta(key_id=key_id, org_id=org_id)
    raise ValueError("Invalid key name format")


def sign_cdp_jwt(key: CdpKeyData, method: str, path: str) -> str:
    """Generate JWT for CDP authentication following Coinbase specifications"""
    # Load the private key
    private_key_bytes = key.private_key.encode('utf-8')
    try:
        private_key = serialization.load_pem_private_key(
            private_key_bytes,
            password=None,
            backend=default_backend()
        )
    except Exception as e:
        logger.error(f"Failed to load private key: {e}")
        raise ValueError(f"Invalid private key format: {e}")

    # Build URI (method + space + host + path)
    uri = f"{method} api.coinbase.com{path}"

    # JWT payload following Coinbase specifications
    current_time = int(time.time())
    payload = {
        'sub': key.name,
        'iss': 'cdp',  # Changed from 'coinbase-cloud' to 'cdp'
        'nbf': current_time,
        'exp': current_time + 120,  # 2-minute expiry
        'uri': uri
    }

    # JWT headers
    headers = {
        'alg': 'ES256',
        'kid': key.name,
        'nonce': secrets.token_hex(16),
        'typ': 'JWT'
    }

    # Generate JWT
    token = jwt.encode(
        payload,
        private_key,
        algorithm='ES256',
        headers=headers
    )

    return token


class CoinbaseAdvancedClient:
    """Coinbase Advanced Trade API client with CDP authentication"""

    def __init__(self, key_loader, logger=None):
        self.base_url = 'https://api.coinbase.com'
        self.api_version = '/api/v3/brokerage'
        self.key_loader = key_loader
        self.logger = logger or logging.getLogger(__name__)
        self.client = httpx.AsyncClient(timeout=30.0)
        self._rate_limiter = RateLimiter()

    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json_data: Optional[Dict] = None) -> Dict:
        """Make authenticated request to Coinbase API"""
        # Apply rate limiting
        await self._rate_limiter.wait_if_needed()

        # Get CDP key
        key = await self.key_loader()
        path = f"{self.api_version}{endpoint}"
        jwt_token = sign_cdp_jwt(key, method, path)

        url = f"{self.base_url}{path}"
        headers = {
            'Authorization': f'Bearer {jwt_token}',
            'Content-Type': 'application/json'
        }

        try:
            if method == 'GET':
                response = await self.client.get(url, params=params, headers=headers)
            elif method == 'POST':
                response = await self.client.post(url, json=json_data, headers=headers)
            else:
                response = await self.client.request(
                    method, url, params=params, json=json_data, headers=headers
                )

            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            self.logger.error(f"Coinbase API error: {e.response.status_code} - {e.response.text}")
            raise Exception(f"Coinbase API error: {e.response.status_code} - {e.response.text}")

    async def get_accounts(self, limit: int = 49, cursor: Optional[str] = None) -> Dict:
        """Get all accounts"""
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return await self._request('GET', '/accounts', params)

    async def get_account(self, account_id: str) -> Dict:
        """Get specific account details with balance"""
        return await self._request('GET', f'/accounts/{account_id}')

    async def list_fills(
        self,
        order_id: Optional[str] = None,
        product_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None
    ) -> Dict:
        """List fills (trade executions) - primary endpoint for tax calculations"""
        params = {}
        if order_id:
            params['order_id'] = order_id
        if product_id:
            params['product_id'] = product_id
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        if limit:
            params['limit'] = limit
        if cursor:
            params['cursor'] = cursor

        return await self._request('GET', '/orders/historical/fills', params)

    async def list_orders(
        self,
        product_id: Optional[str] = None,
        order_status: Optional[List[str]] = None,
        limit: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        cursor: Optional[str] = None
    ) -> Dict:
        """List historical orders"""
        params = {}
        if product_id:
            params['product_id'] = product_id
        if order_status:
            params['order_status'] = order_status
        if limit:
            params['limit'] = limit
        if start_date:
            params['start_date'] = start_date
        if end_date:
            params['end_date'] = end_date
        if cursor:
            params['cursor'] = cursor

        return await self._request('GET', '/orders/historical/batch', params)

    async def get_products(self, limit: int = 50, offset: int = 0) -> Dict:
        """Get available trading products"""
        params = {'limit': limit, 'offset': offset}
        return await self._request('GET', '/products', params)

    async def get_transactions(self, account_id: str, limit: int = 100, cursor: Optional[str] = None) -> Dict:
        """Get transactions for an account (deposits, withdrawals)"""
        params = {'limit': limit}
        if cursor:
            params['cursor'] = cursor
        return await self._request('GET', f'/accounts/{account_id}/transactions', params)

    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()


class RateLimiter:
    """Rate limiter for API requests"""

    def __init__(self, max_requests: int = 10, window_ms: int = 1000):
        self.max_requests = max_requests
        self.window_ms = window_ms
        self.requests = []

    async def wait_if_needed(self):
        """Wait if rate limit would be exceeded"""
        import asyncio

        now = time.time() * 1000  # Convert to milliseconds
        # Remove old requests outside the window
        self.requests = [t for t in self.requests if now - t < self.window_ms]

        if len(self.requests) >= self.max_requests:
            # Calculate wait time
            oldest_request = self.requests[0]
            wait_time = (self.window_ms - (now - oldest_request)) / 1000  # Convert to seconds
            if wait_time > 0:
                await asyncio.sleep(wait_time)

        self.requests.append(now)


def process_fill_for_tax(fill: Dict) -> Dict:
    """Process a fill (trade execution) for tax calculations"""
    try:
        product_parts = fill['product_id'].split('-')
        base_currency = product_parts[0] if len(product_parts) > 0 else 'UNKNOWN'
        quote_currency = product_parts[1] if len(product_parts) > 1 else 'USD'

        price = Decimal(str(fill.get('price', '0')))
        size = Decimal(str(fill.get('size', '0')))
        commission = Decimal(str(fill.get('commission', '0')))

        if fill.get('side') == 'BUY':
            return {
                'type': 'ACQUISITION',
                'timestamp': fill.get('trade_time'),
                'asset': base_currency,
                'quantity': float(size),
                'cost_basis': float((price * size) + commission),
                'fee': float(commission),
                'fee_currency': quote_currency,
                'exchange': 'coinbase',
                'transaction_id': fill.get('entry_id')
            }
        else:  # SELL
            return {
                'type': 'DISPOSAL',
                'timestamp': fill.get('trade_time'),
                'asset': base_currency,
                'quantity': float(size),
                'proceeds': float((price * size) - commission),
                'fee': float(commission),
                'fee_currency': quote_currency,
                'exchange': 'coinbase',
                'transaction_id': fill.get('entry_id')
            }
    except Exception as e:
        logger.error(f"Error processing fill for tax: {e}")
        raise


def redact_private_key(text: str) -> str:
    """Redact private key from text for logging"""
    return re.sub(
        r'-----BEGIN EC PRIVATE KEY-----[\s\S]*?-----END EC PRIVATE KEY-----',
        '-----BEGIN EC PRIVATE KEY-----\n[REDACTED]\n-----END EC PRIVATE KEY-----',
        text
    )


def sanitize_log_data(data: Any) -> Any:
    """Sanitize sensitive data for logging"""
    if isinstance(data, str):
        return redact_private_key(data)

    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in ['private', 'secret', 'password', 'key']):
                sanitized[key] = '[REDACTED]'
            else:
                sanitized[key] = sanitize_log_data(value)
        return sanitized

    if isinstance(data, list):
        return [sanitize_log_data(item) for item in data]

    return data