"""
Dynamic Price Service for resolving prices of any ERC20 token using contract addresses.
Implements a multi-source waterfall approach with confidence scoring.
"""

import os
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from decimal import Decimal
from django.core.cache import cache

logger = logging.getLogger(__name__)

# API Configuration
COINGECKO_API_KEY = os.getenv('COINGECKO_API_KEY')
CRYPTOCOMPARE_API_KEY = os.getenv('CRYPTOCOMPARE_API_KEY')

# Cache durations for different data types
CACHE_LAYERS = {
    'token_metadata': 604800,      # 7 days - Token info rarely changes
    'historical_price': 86400,     # 24 hours - Historical data is immutable
    'pool_discovery': 3600,        # 1 hour - Pools can change
    'current_price': 300,          # 5 minutes - Current prices fluctuate
    'contract_mapping': 2592000,   # 30 days - Contract addresses are permanent
}


class DynamicPriceResolver:
    """Resolves prices for any ERC20 token using contract addresses"""

    def __init__(self):
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.geckoterminal_base_url = "https://api.geckoterminal.com/api/v2"
        self.dexscreener_base_url = "https://api.dexscreener.com/latest/dex"

        # Headers for CoinGecko (if API key is available)
        self.coingecko_headers = {}
        if COINGECKO_API_KEY:
            self.coingecko_headers = {"x-cg-pro-api-key": COINGECKO_API_KEY}

    def resolve_token_price(self, contract_address: str, timestamp: int,
                           symbol: str = None) -> Dict[str, Any]:
        """
        Resolve historical price for any token

        Priority:
        1. CoinGecko by contract address
        2. GeckoTerminal DEX prices
        3. DexScreener current prices (if recent)
        4. On-chain Uniswap reserves (future implementation)

        Args:
            contract_address: Token contract address (checksummed)
            timestamp: Unix timestamp for the price
            symbol: Optional token symbol for fallback lookup

        Returns:
            Dict containing price, source, and confidence level
        """
        # Check cache first
        cache_key = f"token_price_{contract_address}_{timestamp}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result

        # Try CoinGecko first
        price = self._try_coingecko_contract(contract_address, timestamp)
        if price:
            result = {'price': price, 'source': 'coingecko', 'confidence': 'high'}
            cache.set(cache_key, result, CACHE_LAYERS['historical_price'])
            return result

        # Try GeckoTerminal for DEX prices
        price = self._try_geckoterminal(contract_address, timestamp)
        if price:
            result = {'price': price, 'source': 'geckoterminal', 'confidence': 'medium'}
            cache.set(cache_key, result, CACHE_LAYERS['historical_price'])
            return result

        # Try DexScreener for current price (if timestamp is recent)
        if timestamp > time.time() - 86400:  # Within 24 hours
            price = self._try_dexscreener(contract_address)
            if price:
                result = {'price': price, 'source': 'dexscreener', 'confidence': 'low'}
                cache.set(cache_key, result, CACHE_LAYERS['current_price'])
                return result

        # Fallback - could implement on-chain Uniswap reading here
        logger.warning(f"No price found for token {contract_address} at {timestamp}")
        return {'price': 0.01, 'source': 'fallback', 'confidence': 'none'}

    def _try_coingecko_contract(self, contract_address: str, timestamp: int) -> Optional[float]:
        """Fetch price by contract address from CoinGecko"""
        try:
            # First, get token info by contract to get the CoinGecko ID
            contract_lower = contract_address.lower()
            info_url = f"{self.coingecko_base_url}/coins/ethereum/contract/{contract_lower}"

            response = requests.get(info_url, headers=self.coingecko_headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                coin_id = data.get('id')

                if coin_id:
                    # Now fetch historical price using the coin ID
                    return self._fetch_coingecko_historical(coin_id, timestamp)
            elif response.status_code == 429:
                logger.warning("CoinGecko rate limit hit")
            else:
                logger.debug(f"Token not found on CoinGecko: {contract_address}")

        except Exception as e:
            logger.error(f"Error fetching CoinGecko price for {contract_address}: {str(e)}")

        return None

    def _fetch_coingecko_historical(self, coin_id: str, timestamp: int) -> Optional[float]:
        """Fetch historical price from CoinGecko by coin ID"""
        try:
            # Convert timestamp to date string
            date = datetime.fromtimestamp(timestamp)
            date_str = date.strftime("%d-%m-%Y")

            # Fetch historical data
            url = f"{self.coingecko_base_url}/coins/{coin_id}/history"
            params = {"date": date_str}

            response = requests.get(url, params=params, headers=self.coingecko_headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if 'market_data' in data and 'current_price' in data['market_data']:
                    price = data['market_data']['current_price'].get('usd', 0)
                    return float(price) if price else None

        except Exception as e:
            logger.error(f"Error fetching CoinGecko historical price: {str(e)}")

        return None

    def _try_geckoterminal(self, contract_address: str, timestamp: int) -> Optional[float]:
        """Fetch DEX prices from GeckoTerminal"""
        try:
            # Find pools for token
            pools_url = f"{self.geckoterminal_base_url}/networks/eth/tokens/{contract_address.lower()}/pools"

            response = requests.get(pools_url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                pools = data.get('data', [])

                if pools:
                    # Get the pool with highest liquidity/volume
                    best_pool = None
                    highest_liquidity = 0

                    for pool in pools[:5]:  # Check top 5 pools
                        attributes = pool.get('attributes', {})
                        reserve_usd = float(attributes.get('reserve_in_usd', 0))

                        if reserve_usd > highest_liquidity:
                            highest_liquidity = reserve_usd
                            best_pool = pool

                    if best_pool:
                        # For now, return current price from the best pool
                        # In a full implementation, we'd fetch OHLCV data for historical prices
                        attributes = best_pool.get('attributes', {})
                        price_usd = attributes.get('base_token_price_usd')

                        if price_usd:
                            return float(price_usd)

        except Exception as e:
            logger.error(f"Error fetching GeckoTerminal price: {str(e)}")

        return None

    def _try_dexscreener(self, contract_address: str) -> Optional[float]:
        """Fetch current price from DexScreener"""
        try:
            # Search for token on Ethereum
            url = f"{self.dexscreener_base_url}/tokens/{contract_address.lower()}"

            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])

                if pairs:
                    # Get pair with highest liquidity
                    best_pair = None
                    highest_liquidity = 0

                    for pair in pairs:
                        if pair.get('chainId') == 'ethereum':
                            liquidity_usd = float(pair.get('liquidity', {}).get('usd', 0))

                            if liquidity_usd > highest_liquidity:
                                highest_liquidity = liquidity_usd
                                best_pair = pair

                    if best_pair:
                        price_usd = best_pair.get('priceUsd')
                        if price_usd:
                            return float(price_usd)

        except Exception as e:
            logger.error(f"Error fetching DexScreener price: {str(e)}")

        return None

    def fetch_prices_batch(self, transactions: list) -> dict:
        """
        Batch fetch prices for multiple transactions

        Args:
            transactions: List of transaction dictionaries with contract_address and timestamp

        Returns:
            Dict mapping transaction hashes to price data
        """
        # Group transactions by token to optimize API calls
        token_groups = {}
        for tx in transactions:
            contract = tx.get('contract_address', '')
            if contract not in token_groups:
                token_groups[contract] = []
            token_groups[contract].append(tx)

        # Process each token group
        results = {}
        for contract, txs in token_groups.items():
            # Find min/max timestamps for this token
            timestamps = [tx['timestamp'] for tx in txs]
            min_ts = min(timestamps)
            max_ts = max(timestamps)

            # For tokens with many transactions, consider fetching a time series
            # For now, fetch individual prices
            for tx in txs:
                price_data = self.resolve_token_price(
                    contract,
                    tx['timestamp'],
                    tx.get('asset_symbol')
                )
                results[tx['transaction_hash']] = price_data

        return results


class TokenMetadataResolver:
    """Resolves token metadata using various sources"""

    @staticmethod
    def fetch_from_alchemy(contract_address: str, alchemy_url: str) -> Dict[str, Any]:
        """
        Fetch token metadata using Alchemy's getTokenMetadata

        Args:
            contract_address: Token contract address
            alchemy_url: Alchemy API URL

        Returns:
            Dict containing symbol, name, decimals, and logo
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "alchemy_getTokenMetadata",
                "params": [contract_address]
            }

            response = requests.post(alchemy_url, json=payload, timeout=10)

            if response.status_code == 200:
                data = response.json()
                result = data.get('result', {})

                return {
                    'symbol': result.get('symbol', 'UNKNOWN'),
                    'name': result.get('name', ''),
                    'decimals': result.get('decimals', 18),
                    'logo': result.get('logo', '')
                }
        except Exception as e:
            logger.error(f"Error fetching token metadata from Alchemy: {str(e)}")

        return {
            'symbol': 'UNKNOWN',
            'name': '',
            'decimals': 18,
            'logo': ''
        }

    @staticmethod
    def fetch_solana_token_metadata(mint_address: str, alchemy_url: str) -> Dict[str, Any]:
        """
        Fetch Solana SPL token metadata using Alchemy's getTokenMetadata for Solana

        Args:
            mint_address: SPL token mint address
            alchemy_url: Alchemy Solana API URL

        Returns:
            Dict containing symbol, name, decimals, and logo
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenMetadata",
                "params": [mint_address]
            }

            response = requests.post(alchemy_url, json=payload, timeout=10)

            if response.status_code == 200:
                data = response.json()
                result = data.get('result', {})

                # Alchemy Solana returns different structure
                return {
                    'symbol': result.get('symbol', 'UNKNOWN'),
                    'name': result.get('name', ''),
                    'decimals': result.get('decimals', 9),  # Default to 9 for SPL tokens
                    'logo': result.get('logoURI', '')
                }
        except Exception as e:
            logger.error(f"Error fetching Solana token metadata from Alchemy: {str(e)}")

        return {
            'symbol': 'UNKNOWN',
            'name': '',
            'decimals': 9,
            'logo': ''
        }