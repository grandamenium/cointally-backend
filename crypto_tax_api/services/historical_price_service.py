"""
Historical Price Service for fetching cryptocurrency prices at specific timestamps.
Supports CoinGecko and CryptoCompare APIs with fallback mechanisms.
"""

import os
import time
import logging
import requests
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, Any
from django.core.cache import cache
from decimal import Decimal

logger = logging.getLogger(__name__)

# API Configuration
COINGECKO_API_KEY = os.getenv('COINGECKO_API_KEY')
CRYPTOCOMPARE_API_KEY = os.getenv('CRYPTOCOMPARE_API_KEY')

# Symbol to CoinGecko ID mapping
COINGECKO_ID_MAP = {
    'ETH': 'ethereum',
    'BTC': 'bitcoin',
    'USDT': 'tether',
    'USDC': 'usd-coin',
    'BNB': 'binancecoin',
    'XRP': 'ripple',
    'ADA': 'cardano',
    'DOGE': 'dogecoin',
    'SOL': 'solana',
    'TRX': 'tron',
    'DOT': 'polkadot',
    'MATIC': 'matic-network',
    'AVAX': 'avalanche-2',
    'SHIB': 'shiba-inu',
    'WBTC': 'wrapped-bitcoin',
    'WETH': 'weth',
    'UNI': 'uniswap',
    'LINK': 'chainlink',
    'LEO': 'leo-token',
    'LTC': 'litecoin',
    'FTT': 'ftx-token',
    'CRO': 'crypto-com-coin',
    'NEAR': 'near',
    'ATOM': 'cosmos',
    'XLM': 'stellar',
    'XMR': 'monero',
    'BCH': 'bitcoin-cash',
    'ALGO': 'algorand',
    'VET': 'vechain',
    'FLOW': 'flow',
    'MANA': 'decentraland',
    'SAND': 'the-sandbox',
    'AXS': 'axie-infinity',
    'HBAR': 'hedera',
    'ICP': 'internet-computer',
    'EGLD': 'elrond-erd-2',
    'XTZ': 'tezos',
    'THETA': 'theta-token',
    'AAVE': 'aave',
    'EOS': 'eos',
    'GALA': 'gala',
    'QNT': 'quant-network',
    'CHZ': 'chiliz',
    'KCS': 'kucoin-shares',
    'CAKE': 'pancakeswap-token',
    'FTM': 'fantom',
    'GRT': 'the-graph',
    'NEO': 'neo',
    'MKR': 'maker',
    'HT': 'huobi-token',
    'RUNE': 'thorchain',
    'ZEC': 'zcash',
    'ENJ': 'enjincoin',
    'APE': 'apecoin',
    'STX': 'blockstack',
    'BAT': 'basic-attention-token',
    'DASH': 'dash',
    'LDO': 'lido-dao',
    'CRV': 'curve-dao-token',
    'COMP': 'compound-governance-token',
    'SNX': 'havven',
    'IMX': 'immutable-x',
    'TWT': 'trust-wallet-token',
    '1INCH': '1inch',
    'RNDR': 'render-token',
    'BLUR': 'blur',
    'OP': 'optimism',
    'INJ': 'injective-protocol',
    'SUI': 'sui',
    'PEPE': 'pepe',
    'FLOKI': 'floki',
    'ARB': 'arbitrum',
    'WLD': 'worldcoin',
    'TON': 'the-open-network',
    'ORDI': 'ordinals',
    'SATS': 'sats-1000sats',
    'BONK': 'bonk',
    'WIF': 'dogwifhat',
    'VIRTUAL': 'virtuals-protocol',
    'JUNFOX': 'junfox',
    'EPIN': 'epin',
}


class APIError(Exception):
    """Custom API error class"""
    pass


class RateLimitError(APIError):
    """Rate limit exceeded error"""
    pass


def retry_on_failure(max_retries=3, backoff_factor=1.0):
    """
    Decorator for API retry logic with exponential backoff
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 429:  # Rate limit
                        if attempt < max_retries:
                            wait_time = backoff_factor * (2 ** attempt)
                            logger.warning(f"Rate limit hit. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                            time.sleep(wait_time)
                            continue
                        else:
                            raise RateLimitError("Max retries exceeded due to rate limiting")
                    elif e.response.status_code in [500, 502, 503, 504]:  # Server errors
                        if attempt < max_retries:
                            wait_time = backoff_factor * (2 ** attempt)
                            logger.warning(f"Server error {e.response.status_code}. Retrying in {wait_time}s")
                            time.sleep(wait_time)
                            continue
                    raise APIError(f"HTTP {e.response.status_code}: {e.response.text}")
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries:
                        wait_time = backoff_factor * (2 ** attempt)
                        logger.warning(f"Request failed: {str(e)}. Retrying in {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    raise APIError(f"Request failed after {max_retries} retries: {str(e)}")
            return None
        return wrapper
    return decorator


class CoinGeckoHistoricalAPI:
    """CoinGecko API client for historical price data"""

    def __init__(self):
        self.api_key = COINGECKO_API_KEY
        self.base_url = 'https://pro-api.coingecko.com/api/v3' if self.api_key else 'https://api.coingecko.com/api/v3'
        self.headers = {'x-cg-pro-api-key': self.api_key} if self.api_key else {}

    @retry_on_failure(max_retries=3, backoff_factor=1.0)
    def fetch_historical_price(self, symbol: str, timestamp: int) -> Optional[float]:
        """
        Fetch historical price for a symbol at a specific timestamp

        Args:
            symbol: Cryptocurrency symbol (e.g., 'ETH', 'BTC')
            timestamp: Unix timestamp

        Returns:
            Price in USD or None if not found
        """
        # Convert symbol to CoinGecko ID
        coin_id = COINGECKO_ID_MAP.get(symbol.upper())
        if not coin_id:
            logger.warning(f"No CoinGecko ID mapping for symbol: {symbol}")
            return None

        # Convert timestamp to date format required by CoinGecko (DD-MM-YYYY)
        date = datetime.fromtimestamp(timestamp)
        date_str = date.strftime('%d-%m-%Y')

        # Cache key for this specific price
        cache_key = f"coingecko_historical_{symbol}_{date_str}"
        cached_price = cache.get(cache_key)
        if cached_price is not None:
            logger.debug(f"Cache hit for {symbol} on {date_str}: ${cached_price}")
            return float(cached_price)

        endpoint = f"{self.base_url}/coins/{coin_id}/history"
        params = {
            'date': date_str,
            'localization': 'false'
        }

        try:
            response = requests.get(endpoint, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if 'market_data' in data and 'current_price' in data['market_data']:
                price = data['market_data']['current_price'].get('usd')
                if price:
                    # Cache for 24 hours (historical data doesn't change)
                    cache.set(cache_key, price, 86400)
                    logger.info(f"CoinGecko: {symbol} price on {date_str}: ${price}")
                    return float(price)

            logger.warning(f"No price data found in CoinGecko response for {symbol} on {date_str}")
            return None

        except Exception as e:
            logger.error(f"CoinGecko API error for {symbol} on {date_str}: {str(e)}")
            raise


class CryptoCompareHistoricalAPI:
    """CryptoCompare API client for historical price data"""

    def __init__(self):
        self.api_key = CRYPTOCOMPARE_API_KEY
        self.base_url = 'https://min-api.cryptocompare.com/data'

    @retry_on_failure(max_retries=3, backoff_factor=1.0)
    def fetch_historical_price(self, symbol: str, timestamp: int) -> Optional[float]:
        """
        Fetch historical price for a symbol at a specific timestamp

        Args:
            symbol: Cryptocurrency symbol (e.g., 'ETH', 'BTC')
            timestamp: Unix timestamp

        Returns:
            Price in USD or None if not found
        """
        # Cache key for this specific price
        date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
        cache_key = f"cryptocompare_historical_{symbol}_{date_str}"
        cached_price = cache.get(cache_key)
        if cached_price is not None:
            logger.debug(f"Cache hit for {symbol} on {date_str}: ${cached_price}")
            return float(cached_price)

        # Use histohour endpoint for more precise data
        endpoint = f"{self.base_url}/histohour"
        params = {
            'fsym': symbol.upper(),
            'tsym': 'USD',
            'toTs': timestamp,
            'limit': 1
        }

        if self.api_key:
            params['api_key'] = self.api_key

        try:
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('Response') == 'Error':
                logger.warning(f"CryptoCompare error for {symbol}: {data.get('Message')}")
                return None

            if 'Data' in data and len(data['Data']) > 0:
                # Get the closest price data point
                price_data = data['Data'][-1]  # Last item is closest to requested timestamp
                price = price_data.get('close') or price_data.get('open')
                if price:
                    # Cache for 24 hours
                    cache.set(cache_key, price, 86400)
                    logger.info(f"CryptoCompare: {symbol} price on {date_str}: ${price}")
                    return float(price)

            logger.warning(f"No price data found in CryptoCompare response for {symbol}")
            return None

        except Exception as e:
            logger.error(f"CryptoCompare API error for {symbol}: {str(e)}")
            raise


def fetch_historical_price(symbol: str, timestamp: int, chain: str = 'ethereum') -> float:
    """
    Main function to fetch historical price with fallback mechanism

    Args:
        symbol: Cryptocurrency symbol (e.g., 'ETH', 'BTC')
        timestamp: Unix timestamp
        chain: Blockchain network (for context, not used in price fetching)

    Returns:
        Price in USD, with fallback to current price if historical price unavailable
    """
    # Quick cache check
    date_str = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')
    cache_key = f"historical_price_{symbol}_{date_str}"
    cached_price = cache.get(cache_key)
    if cached_price is not None:
        return float(cached_price)

    # Try CoinGecko first (usually more reliable for historical data)
    try:
        coingecko_api = CoinGeckoHistoricalAPI()
        price = coingecko_api.fetch_historical_price(symbol, timestamp)
        if price:
            cache.set(cache_key, price, 86400)  # Cache for 24 hours
            return price
    except Exception as e:
        logger.warning(f"CoinGecko failed for {symbol}: {str(e)}")

    # Fallback to CryptoCompare
    try:
        cryptocompare_api = CryptoCompareHistoricalAPI()
        price = cryptocompare_api.fetch_historical_price(symbol, timestamp)
        if price:
            cache.set(cache_key, price, 86400)  # Cache for 24 hours
            return price
    except Exception as e:
        logger.warning(f"CryptoCompare failed for {symbol}: {str(e)}")

    # If all APIs fail, use the current price as last resort (with warning)
    logger.warning(f"Failed to fetch historical price for {symbol} at {date_str}. Using current price as fallback.")

    # Import here to avoid circular dependency
    from crypto_tax_api.utils.blockchain_apis import fetch_price_data
    current_price = fetch_price_data(symbol)

    # Don't cache fallback price as historical
    return current_price


def get_historical_price_for_transaction(transaction_data: Dict[str, Any]) -> float:
    """
    Helper function to extract symbol and timestamp from transaction data

    Args:
        transaction_data: Dictionary containing transaction details

    Returns:
        Historical price in USD
    """
    symbol = transaction_data.get('asset_symbol', 'ETH')
    timestamp = transaction_data.get('timestamp')

    if not timestamp:
        logger.error(f"No timestamp provided for transaction: {transaction_data}")
        # Return current price as fallback
        from crypto_tax_api.utils.blockchain_apis import fetch_price_data
        return fetch_price_data(symbol)

    # Convert timestamp to Unix timestamp if it's a datetime object
    if isinstance(timestamp, datetime):
        timestamp = int(timestamp.timestamp())
    elif isinstance(timestamp, str):
        # Parse ISO format or other date strings
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            timestamp = int(dt.timestamp())
        except:
            logger.error(f"Failed to parse timestamp: {timestamp}")
            from crypto_tax_api.utils.blockchain_apis import fetch_price_data
            return fetch_price_data(symbol)

    return fetch_historical_price(symbol, timestamp)


# Batch fetch function for efficiency
def fetch_historical_prices_batch(transactions: list) -> Dict[str, float]:
    """
    Fetch historical prices for multiple transactions efficiently

    Args:
        transactions: List of transaction dictionaries

    Returns:
        Dictionary mapping transaction_hash to historical price
    """
    price_map = {}

    for tx in transactions:
        tx_hash = tx.get('transaction_hash', '')
        symbol = tx.get('asset_symbol', 'ETH')
        timestamp = tx.get('timestamp')

        if timestamp:
            price = fetch_historical_price(symbol, timestamp)
            price_map[tx_hash] = price

    return price_map