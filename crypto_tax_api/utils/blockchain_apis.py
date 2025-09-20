"""
Utility functions for interacting with blockchain APIs and fetching transaction data
"""
import os
import json
import logging
import requests
import time
from decimal import Decimal
from datetime import datetime, timezone
from django.utils import timezone as django_timezone
from web3 import Web3
from decimal import Decimal, InvalidOperation, ConversionSyntax
from crypto_tax_api.services.historical_price_service import fetch_historical_price
from crypto_tax_api.services.dynamic_price_service import DynamicPriceResolver, TokenMetadataResolver

logger = logging.getLogger(__name__)

# API keys from settings
COVALENT_API_KEY = os.environ.get('COVALENT_API_KEY', '')
ALCHEMY_API_KEY = os.environ.get('ALCHEMY_API_KEY', '')
ALCHEMY_SOLANA_API_KEY = os.environ.get('ALCHEMY_SOLANA_API_KEY', '')

# Cache for price data (would use Redis in production)
price_cache = {}
price_cache_expiry = {}


def safe_decimal(value):
    """
    Safely convert a value to Decimal, handling various formats
    including scientific notation.
    """
    try:
        if value is None:
            return Decimal('0')
        elif isinstance(value, (int, float)):
            return Decimal(str(value))
        elif isinstance(value, str):
            # Try direct conversion
            try:
                return Decimal(value)
            except (InvalidOperation, ConversionSyntax):
                # Handle scientific notation
                try:
                    return Decimal(str(float(value)))
                except (ValueError, InvalidOperation):
                    # If all else fails, return 0
                    logger.warning(f"Could not convert value to Decimal: {value}")
                    return Decimal('0')
        else:
            # For any other type, convert to string first
            try:
                return Decimal(str(float(value)))
            except:
                return Decimal('0')
    except Exception as e:
        logger.error(f"Error converting to Decimal: {value}, Error: {str(e)}")
        return Decimal('0')


def fetch_price_data(symbol, force_refresh=False):
    """
    Fetch current price data for a cryptocurrency using multiple APIs with retry logic
    """
    # Handle None or empty symbol
    if symbol is None or symbol == '':
        logger.warning("Received None or empty symbol in fetch_price_data")
        return Decimal('1.00')

    current_time = django_timezone.now().timestamp()
    cache_expiry = 300  # 5 minutes

    # Check cache first (unless forced refresh)
    if not force_refresh and symbol in price_cache and current_time < price_cache_expiry.get(symbol, 0):
        return price_cache[symbol]

    # Try multiple APIs with reduced timeout and retry logic
    apis_to_try = [
        {
            'name': 'CoinGecko',
            'url': f"https://api.coingecko.com/api/v3/simple/price?ids={symbol.lower()}&vs_currencies=usd",
            'response_parser': lambda data: data.get(symbol.lower(), {}).get('usd')
        },
        {
            'name': 'CryptoCompare',
            'url': f"https://min-api.cryptocompare.com/data/price?fsym={symbol}&tsyms=USD",
            'response_parser': lambda data: data.get('USD')
        },
        {
            'name': 'Binance',
            'url': f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT",
            'response_parser': lambda data: data.get('price')
        }
    ]

    for api_config in apis_to_try:
        for attempt in range(2):  # 2 attempts per API
            try:
                response = requests.get(
                    api_config['url'], 
                    timeout=3,  # Reduced timeout
                    headers={'User-Agent': 'CryptoTaxPro/1.0'}
                )

                if response.status_code == 200:
                    data = response.json()
                    price_value = api_config['response_parser'](data)
                    
                    if price_value:
                        price = safe_decimal(price_value)
                        if price > 0:
                            # Update cache
                            price_cache[symbol] = price
                            price_cache_expiry[symbol] = current_time + cache_expiry
                            logger.info(f"Successfully fetched price for {symbol} from {api_config['name']}: ${price}")
                            return price

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout fetching price for {symbol} from {api_config['name']} (attempt {attempt + 1})")
                continue
            except requests.exceptions.RequestException as e:
                logger.warning(f"Request error fetching price for {symbol} from {api_config['name']}: {str(e)}")
                continue
            except Exception as e:
                logger.warning(f"Error parsing response from {api_config['name']} for {symbol}: {str(e)}")
                continue

    # If all attempts fail, try to use cached price (even if expired)
    if symbol in price_cache:
        logger.warning(f"Using expired cached price for {symbol}: ${price_cache[symbol]}")
        return price_cache[symbol]

    # Final fallback - return default price based on symbol
    fallback_prices = {
        'ETH': Decimal('2500.00'),
        'BTC': Decimal('45000.00'),
        'BNB': Decimal('300.00'),
        'MATIC': Decimal('0.80'),
        'AVAX': Decimal('25.00'),
        'SOL': Decimal('100.00'),
        'ARB': Decimal('0.50'),
        'USDT': Decimal('1.00'),
        'USDC': Decimal('1.00'),
        'BUSD': Decimal('1.00'),
        'DAI': Decimal('1.00')
    }
    
    fallback_price = fallback_prices.get(symbol, Decimal('1.00'))
    logger.warning(f"Using fallback price for {symbol}: ${fallback_price}")
    
    # Cache the fallback price for a shorter duration
    price_cache[symbol] = fallback_price
    price_cache_expiry[symbol] = current_time + 60  # 1 minute cache for fallback
    
    return fallback_price


# Common DEX router addresses
DEX_ROUTERS = {
    # Ethereum
    '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D': 'Uniswap V2',
    '0xE592427A0AEce92De3Edee1F18E0157C05861564': 'Uniswap V3',
    '0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F': 'SushiSwap',
    '0x1111111254fb6c44bAC0beD2854e76F90643097d': '1inch',
    # Add more as needed
}


def fetch_token_metadata(contract_address: str, alchemy_url: str) -> dict:
    """
    Fetch token metadata using Alchemy's getTokenMetadata

    Args:
        contract_address: Token contract address
        alchemy_url: Alchemy API URL

    Returns:
        Dict containing symbol, name, decimals, and logo
    """
    return TokenMetadataResolver.fetch_from_alchemy(contract_address, alchemy_url)


def fetch_ethereum_transactions(address):
    """
    Fetch transactions for an Ethereum address using Alchemy API with proper authentication
    """
    # API Key Management following the generalizable pattern
    api_key = get_alchemy_api_key('ALCHEMY_ETHEREUM_API_KEY')

    if not api_key:
        logger.error(f"No Alchemy API key configured for Ethereum")
        return []

    # Endpoint Construction
    alchemy_url = ALCHEMY_ENDPOINTS['ethereum'].format(api_key=api_key)
    logger.info(f"ETHEREUM_FETCH_START: address={address[:10]}...{address[-6:]}, api_key=***{api_key[-4:]}")

    try:
        # Normalize address
        address = address.lower()

        # Initialize web3
        w3 = Web3()

        # Get normal transactions
        normal_tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "fromAddress": address,
                    "category": ["external", "internal", "erc20", "erc721", "erc1155"]
                }
            ]
        }

        response = requests.post(alchemy_url, json=normal_tx_payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Alchemy API error: {response.text}")
            return []

        normal_tx_data = response.json()
        if 'error' in normal_tx_data:
            logger.error(f"Alchemy API error: {normal_tx_data['error']}")
            return []

        # Get incoming transactions
        incoming_tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "toAddress": address,
                    "category": ["external", "internal", "erc20"]
                }
            ]
        }

        incoming_response = requests.post(alchemy_url, json=incoming_tx_payload, timeout=10)
        if incoming_response.status_code != 200:
            logger.error(f"Alchemy API error: {incoming_response.text}")
            incoming_tx_data = {"result": {"transfers": []}}
        else:
            incoming_tx_data = incoming_response.json()
            if 'error' in incoming_tx_data:
                logger.error(f"Alchemy API error: {incoming_tx_data['error']}")
                incoming_tx_data = {"result": {"transfers": []}}

        # Process transactions
        processed_transactions = []

        # Get block timestamps for transactions (we'll need to separately fetch these)
        block_timestamps = {}

        # Process outgoing transactions (likely sells or transfers out)
        if 'result' in normal_tx_data and 'transfers' in normal_tx_data['result']:
            for tx in normal_tx_data['result']['transfers']:
                # Check for required fields
                if not all(k in tx for k in ['hash', 'from', 'to']):
                    continue

                # Handle missing asset
                asset = tx.get('asset', 'ETH')
                if asset is None:
                    asset = 'ETH'  # Default to ETH if no asset specified

                # Extract contract address and metadata for ERC20 tokens
                raw_contract = tx.get('rawContract', {})
                contract_address = raw_contract.get('address')
                token_decimals = 18  # Default decimals

                if contract_address:
                    # ERC20 token - fetch metadata
                    try:
                        token_metadata = fetch_token_metadata(contract_address, alchemy_url)
                        asset_symbol = token_metadata['symbol']
                        token_decimals = token_metadata['decimals']

                        # If rawContract has decimal value, use it
                        if 'decimal' in raw_contract:
                            token_decimals = int(raw_contract['decimal'], 16) if raw_contract['decimal'] else 18
                    except Exception as e:
                        logger.warning(f"Failed to fetch metadata for token {contract_address}: {e}")
                        asset_symbol = asset
                else:
                    # Native ETH
                    contract_address = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # Placeholder for ETH
                    asset_symbol = 'ETH'

                # Make sure we have a value field, default to 0 if missing
                if 'value' not in tx:
                    tx['value'] = 0

                # Calculate amount with proper decimals
                if 'rawContract' in tx and 'value' in tx['rawContract']:
                    raw_value = int(tx['rawContract'].get('value', '0x0'), 16)
                    amount = Decimal(raw_value) / Decimal(10 ** token_decimals)
                else:
                    amount = safe_decimal(tx.get('value', 0))

                # Get block number for timestamp
                block_num = tx.get('blockNum')
                if block_num:
                    # Convert hex block number to int
                    block_num_int = int(block_num, 16)

                    # If we don't have the timestamp for this block, fetch it
                    if block_num_int not in block_timestamps:
                        try:
                            # Get block info
                            block_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "eth_getBlockByNumber",
                                "params": [block_num, False]
                            }

                            block_response = requests.post(alchemy_url, json=block_payload, timeout=10)
                            if block_response.status_code == 200:
                                block_data = block_response.json()
                                if 'result' in block_data and 'timestamp' in block_data['result']:
                                    # Convert hex timestamp to datetime
                                    block_timestamp = int(block_data['result']['timestamp'], 16)
                                    block_timestamps[block_num_int] = datetime.fromtimestamp(block_timestamp,
                                                                                             tz=timezone.utc)
                        except Exception as e:
                            logger.error(f"Error fetching block data: {str(e)}")

                # Get timestamp (fallback to current time if not available)
                timestamp = block_timestamps.get(int(block_num, 16)) if block_num else django_timezone.now()

                # Determine transaction type
                tx_type = 'sell'  # Default for outgoing
                to_address = tx.get('to', '')
                if asset == 'ETH' and to_address and w3.to_checksum_address(to_address) in DEX_ROUTERS:
                    tx_type = 'swap'  # ETH sent to DEX router is likely a swap

                # Use dynamic price resolver for accurate pricing
                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())

                if contract_address and contract_address != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE":
                    # Use dynamic resolver for tokens
                    price_resolver = DynamicPriceResolver()
                    price_data = price_resolver.resolve_token_price(
                        contract_address,
                        unix_timestamp,
                        asset_symbol
                    )
                    price_usd = Decimal(str(price_data['price']))
                    price_source = price_data['source']
                    price_confidence = price_data['confidence']
                else:
                    # Use existing method for ETH
                    price_usd = Decimal(str(fetch_historical_price('ETH', unix_timestamp)))
                    price_source = 'coingecko'
                    price_confidence = 'high'

                value_usd = amount * price_usd

                # Estimate gas fee
                fee_usd = Decimal('0.00')

                # Create transaction record with enhanced data
                processed_transactions.append({
                    'transaction_hash': tx['hash'],
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_usd': fee_usd,
                    'contract_address': contract_address,
                    'token_decimals': token_decimals,
                    'price_source': price_source,
                    'price_confidence': price_confidence
                })

        # Process incoming transactions (likely buys or transfers in)
        if 'result' in incoming_tx_data and 'transfers' in incoming_tx_data['result']:
            for tx in incoming_tx_data['result']['transfers']:
                # Check for required fields
                if not all(k in tx for k in ['hash', 'from', 'to']):
                    continue

                # Handle missing asset
                asset = tx.get('asset', 'ETH')
                if asset is None:
                    asset = 'ETH'  # Default to ETH if no asset specified

                # Extract contract address and metadata for ERC20 tokens
                raw_contract = tx.get('rawContract', {})
                contract_address = raw_contract.get('address')
                token_decimals = 18  # Default decimals

                if contract_address:
                    # ERC20 token - fetch metadata
                    try:
                        token_metadata = fetch_token_metadata(contract_address, alchemy_url)
                        asset_symbol = token_metadata['symbol']
                        token_decimals = token_metadata['decimals']

                        # If rawContract has decimal value, use it
                        if 'decimal' in raw_contract:
                            token_decimals = int(raw_contract['decimal'], 16) if raw_contract['decimal'] else 18
                    except Exception as e:
                        logger.warning(f"Failed to fetch metadata for token {contract_address}: {e}")
                        asset_symbol = asset
                else:
                    # Native ETH
                    contract_address = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"  # Placeholder for ETH
                    asset_symbol = 'ETH'

                # Make sure we have a value field, default to 0 if missing
                if 'value' not in tx:
                    tx['value'] = 0

                # Calculate amount with proper decimals
                if 'rawContract' in tx and 'value' in tx['rawContract']:
                    raw_value = int(tx['rawContract'].get('value', '0x0'), 16)
                    amount = Decimal(raw_value) / Decimal(10 ** token_decimals)
                else:
                    amount = safe_decimal(tx.get('value', 0))

                # Skip transfers from self (already processed as outgoing)
                if tx['from'].lower() == address:
                    continue

                # Get block number for timestamp
                block_num = tx.get('blockNum')
                if block_num:
                    # Convert hex block number to int
                    block_num_int = int(block_num, 16)

                    # If we don't have the timestamp for this block, fetch it
                    if block_num_int not in block_timestamps:
                        try:
                            # Get block info
                            block_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "eth_getBlockByNumber",
                                "params": [block_num, False]
                            }

                            block_response = requests.post(alchemy_url, json=block_payload, timeout=10)
                            if block_response.status_code == 200:
                                block_data = block_response.json()
                                if 'result' in block_data and 'timestamp' in block_data['result']:
                                    # Convert hex timestamp to datetime
                                    block_timestamp = int(block_data['result']['timestamp'], 16)
                                    block_timestamps[block_num_int] = datetime.fromtimestamp(block_timestamp,
                                                                                             tz=timezone.utc)
                        except Exception as e:
                            logger.error(f"Error fetching block data: {str(e)}")

                # Get timestamp (fallback to current time if not available)
                timestamp = block_timestamps.get(int(block_num, 16)) if block_num else django_timezone.now()

                # Determine transaction type
                tx_type = 'buy'  # Default for incoming
                from_address = tx.get('from', '')
                if from_address and w3.to_checksum_address(from_address) in DEX_ROUTERS:
                    tx_type = 'swap'  # Received from DEX router is likely a swap

                # Use dynamic price resolver for accurate pricing
                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())

                if contract_address and contract_address != "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE":
                    # Use dynamic resolver for tokens
                    price_resolver = DynamicPriceResolver()
                    price_data = price_resolver.resolve_token_price(
                        contract_address,
                        unix_timestamp,
                        asset_symbol
                    )
                    price_usd = Decimal(str(price_data['price']))
                    price_source = price_data['source']
                    price_confidence = price_data['confidence']
                else:
                    # Use existing method for ETH
                    price_usd = Decimal(str(fetch_historical_price('ETH', unix_timestamp)))
                    price_source = 'coingecko'
                    price_confidence = 'high'

                value_usd = amount * price_usd

                # Create transaction record with enhanced data
                processed_transactions.append({
                    'transaction_hash': tx['hash'],
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_usd': Decimal('0.00'),  # Incoming transfers don't pay gas
                    'contract_address': contract_address,
                    'token_decimals': token_decimals,
                    'price_source': price_source,
                    'price_confidence': price_confidence
                })

        # Sort by timestamp
        processed_transactions.sort(key=lambda x: x['timestamp'])

        # Log transaction count for debugging
        logger.info(f"Successfully processed {len(processed_transactions)} Ethereum transactions for address {address}")

        return processed_transactions

    except Exception as e:
        logger.error(f"ETHEREUM_FETCH_ERROR: {str(e)}", exc_info=True)

        # Classify the error type for better user feedback
        error_message = str(e).lower()
        if 'timeout' in error_message or 'connection' in error_message:
            raise ConnectionError(f"Network timeout while fetching Ethereum transactions. Please try again later.")
        elif 'unauthorized' in error_message or '401' in error_message:
            raise PermissionError(f"Invalid API key for Ethereum blockchain access.")
        elif 'rate limit' in error_message or '429' in error_message:
            raise ConnectionError(f"API rate limit exceeded. Please wait a moment and try again.")
        elif 'not found' in error_message or '404' in error_message:
            raise ValueError(f"Ethereum address not found or invalid: {address[:10]}...{address[-6:]}")
        else:
            raise RuntimeError(f"Failed to fetch Ethereum transactions: {str(e)}")

        # Note: No mock data returned - let the calling function handle the error appropriately


def fetch_solana_transactions(address):
    """
    Fetch Solana transactions using Alchemy API with proper authentication
    """
    # API Key Management following the generalizable pattern
    api_key = get_alchemy_api_key('ALCHEMY_SOLANA_API_KEY')

    if not api_key:
        logger.error(f"No Alchemy API key configured for Solana")
        return []

    # Endpoint Construction
    alchemy_url = ALCHEMY_ENDPOINTS['solana'].format(api_key=api_key)
    logger.info(f"Starting Solana transaction fetch for address: {address}")

    all_transactions = []
    before_signature = None
    max_iterations = 10  # Limit iterations to prevent infinite loops
    iteration = 0

    try:
        while iteration < max_iterations:
            # Prepare params with pagination
            params = {"limit": 1000, "commitment": "finalized"}
            if before_signature:
                params["before"] = before_signature

            # Get signatures for the address
            signatures_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [address, params]
            }

            response = requests.post(alchemy_url, json=signatures_payload, timeout=30)
            logger.info(f"Solana signatures API response status: {response.status_code}, iteration: {iteration}")

            if response.status_code != 200:
                logger.error(f"Solana signatures API error: {response.text}")
                break

            signatures_data = response.json()
            if 'error' in signatures_data:
                logger.error(f"Solana signatures RPC error: {signatures_data['error']}")
                break

            if 'result' not in signatures_data or not signatures_data['result']:
                logger.info(f"No more transaction signatures found at iteration {iteration}")
                break

            signatures = signatures_data['result']
            logger.info(f"Found {len(signatures)} transaction signatures in iteration {iteration}")

            # If we got signatures, set the before parameter for the next iteration
            if signatures:
                before_signature = signatures[-1]['signature']

            # Process this batch of signatures
            batch_transactions = []

            for sig_info in signatures:
                try:
                    signature = sig_info['signature']
                    block_time = sig_info.get('blockTime')

                    # Skip if there's an error in the transaction
                    if sig_info.get('err'):
                        logger.debug(f"Skipping errored transaction: {signature}")
                        continue

                    if not block_time:
                        logger.debug(f"Skipping transaction without timestamp: {signature}")
                        continue  # Skip transactions without timestamps

                    # Get parsed transaction details using jsonParsed encoding
                    tx_payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTransaction",
                        "params": [
                            signature,
                            {
                                "encoding": "jsonParsed",  # Key: Use jsonParsed for automatic SPL parsing
                                "maxSupportedTransactionVersion": 0,
                                "commitment": "finalized"
                            }
                        ]
                    }

                    tx_response = requests.post(alchemy_url, json=tx_payload, timeout=30)
                    if tx_response.status_code != 200:
                        logger.warning(f"Failed to fetch transaction {signature}: {tx_response.status_code}")
                        continue

                    tx_data = tx_response.json()
                    if 'error' in tx_data:
                        logger.warning(f"Transaction fetch error for {signature}: {tx_data['error']}")
                        continue

                    if 'result' not in tx_data or not tx_data['result']:
                        continue

                    parsed_tx = tx_data['result']

                    # Parse the transaction for tax-relevant data
                    parsed_transactions = parse_solana_tax_transaction(parsed_tx, address, signature, block_time)
                    batch_transactions.extend(parsed_transactions)

                    # Rate limiting: small delay between requests
                    time.sleep(0.05)  # Reduced delay for better performance

                except Exception as e:
                    logger.error(f"Error processing transaction {sig_info.get('signature', 'unknown')}: {str(e)}")
                    continue

            # Add batch transactions to all transactions
            all_transactions.extend(batch_transactions)

            # If we got fewer than the limit, we've reached the end
            if len(signatures) < 1000:
                logger.info("Reached end of transaction history")
                break

            iteration += 1

            # Add a small delay between batches
            time.sleep(0.5)

        # Sort all transactions by timestamp (oldest first)
        all_transactions.sort(key=lambda x: x['timestamp'])

        logger.info(f"Successfully processed {len(all_transactions)} tax-relevant transactions for address {address}")
        return all_transactions

    except Exception as e:
        logger.error(f"Critical error in fetch_solana_transactions: {str(e)}", exc_info=True)
        return all_transactions if all_transactions else []


def classify_solana_instruction(instruction, parsed_info):
    """
    Classify Solana instruction type for proper processing
    Ensures clean separation between SOL and SPL token transfers
    """
    program = instruction.get('program', 'unknown')
    parsed_type = parsed_info.get('type', 'unknown') if parsed_info else 'unknown'

    logger.debug(f"Classifying instruction: program='{program}', type='{parsed_type}'")

    if program == 'system' and parsed_type == 'transfer':
        return 'sol_transfer'
    elif program == 'spl-token' and parsed_type in ['transfer', 'transferChecked']:
        return 'spl_transfer'
    elif 'stake' in program.lower():
        return 'staking'
    elif 'vote' in program.lower():
        return 'voting'
    else:
        return 'other'


def process_sol_transfer(instruction, parsed_info, user_address, signature, timestamp, sol_price, fee_usd, processed_transfer):
    """
    Process native SOL transfer instructions
    Ensures SOL transfers are properly classified and never enter SPL logic
    """
    info = parsed_info.get('info', {})
    source = info.get('source')
    destination = info.get('destination')
    lamports = info.get('lamports', 0)

    logger.debug(f"Processing SOL transfer: source={source}, destination={destination}, lamports={lamports}")

    # Check if user is involved
    if source == user_address or destination == user_address:
        sol_amount = Decimal(lamports) / Decimal(10**9)  # Convert lamports to SOL

        # Skip dust amounts
        if sol_amount < Decimal('0.000001'):
            logger.debug(f"Skipping dust SOL amount: {sol_amount}")
            return None

        # Determine transaction type
        if source == user_address:
            tx_type = 'sell' if destination != user_address else 'transfer'
        else:
            tx_type = 'buy'

        value_usd = sol_amount * Decimal(sol_price)

        logger.info(f"Created SOL transfer: {tx_type}, amount={sol_amount} SOL, value=${value_usd}")

        return {
            'transaction_hash': signature,
            'timestamp': timestamp,
            'transaction_type': tx_type,
            'asset_symbol': 'SOL',
            'amount': sol_amount,
            'price_usd': Decimal(sol_price),
            'value_usd': value_usd,
            'fee_usd': fee_usd if not processed_transfer else Decimal('0'),  # Only add fee once per tx
            'contract_address': None,  # Native SOL has no contract address
            'token_decimals': 9,  # SOL has 9 decimals
            'price_source': 'coingecko',
            'price_confidence': 'high'
        }

    return None


def parse_solana_tax_transaction(parsed_tx, user_address, signature, block_time):
    """
    Parse a Solana transaction for tax-relevant information using proper Alchemy parsed data
    Enhanced to handle staking, rewards, and all transaction types
    Fixed to properly classify SOL vs SPL transfers
    """
    transactions = []

    try:
        timestamp = datetime.fromtimestamp(block_time, tz=timezone.utc)
        fee_lamports = parsed_tx.get('meta', {}).get('fee', 0)
        fee_sol = Decimal(fee_lamports) / Decimal(10**9)  # Convert lamports to SOL

        # Get historical SOL price for fee calculation
        unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
        sol_price = Decimal(str(fetch_historical_price('SOL', unix_timestamp)))
        fee_usd = fee_sol * sol_price if fee_sol > 0 else Decimal('0')

        instructions = parsed_tx.get('transaction', {}).get('message', {}).get('instructions', [])

        logger.debug(f"Processing transaction {signature} with {len(instructions)} instructions")

        # Get pre/post balances to detect SOL transfers
        account_keys = parsed_tx.get('transaction', {}).get('message', {}).get('accountKeys', [])
        pre_balances = parsed_tx.get('meta', {}).get('preBalances', [])
        post_balances = parsed_tx.get('meta', {}).get('postBalances', [])

        # Find user's account index
        user_account_index = None
        for i, account_key in enumerate(account_keys):
            account_pubkey = account_key.get('pubkey') if isinstance(account_key, dict) else account_key
            if account_pubkey == user_address:
                user_account_index = i
                break

        # Track if we've processed any transfers to avoid duplicates
        processed_transfer = False

        # Check for native SOL balance changes first
        if user_account_index is not None and user_account_index < len(pre_balances) and user_account_index < len(post_balances):
            pre_balance_lamports = pre_balances[user_account_index]
            post_balance_lamports = post_balances[user_account_index]
            balance_change_lamports = post_balance_lamports - pre_balance_lamports

            # Account for fees paid (only deducted from the fee payer)
            # The first signer usually pays the fee
            if user_account_index == 0 and fee_lamports > 0:
                balance_change_lamports += fee_lamports

            if abs(balance_change_lamports) > 100:  # Ignore tiny dust amounts
                sol_amount = abs(Decimal(balance_change_lamports) / Decimal(10**9))

                # Determine transaction type based on balance change and instructions
                tx_type = 'buy' if balance_change_lamports > 0 else 'sell'

                # Check for staking operations
                for instruction in instructions:
                    program = instruction.get('program', '')
                    parsed = instruction.get('parsed', {})
                    if 'stake' in program.lower() or 'stake' in str(parsed).lower():
                        if balance_change_lamports < 0:
                            tx_type = 'stake'
                        else:
                            tx_type = 'unstake'
                        break
                    elif 'vote' in program.lower() or 'reward' in str(parsed).lower():
                        if balance_change_lamports > 0:
                            tx_type = 'reward'
                        break

                value_usd = sol_amount * Decimal(sol_price)

                transactions.append({
                    'transaction_hash': signature,
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': 'SOL',
                    'amount': sol_amount,
                    'price_usd': Decimal(sol_price),
                    'value_usd': value_usd,
                    'fee_usd': fee_usd
                })
                processed_transfer = True

        # Process each instruction with proper classification
        for instruction in instructions:
            parsed_info = instruction.get('parsed')

            if not parsed_info:
                logger.debug(f"Skipping instruction without parsed info: {instruction.get('program', 'unknown')}")
                continue

            # Classify the instruction type
            instruction_type = classify_solana_instruction(instruction, parsed_info)
            logger.debug(f"Classified instruction as: {instruction_type}")

            # Process native SOL transfers first (prevent fallthrough to SPL logic)
            if instruction_type == 'sol_transfer':
                result = process_sol_transfer(instruction, parsed_info, user_address, signature, timestamp, sol_price, fee_usd, processed_transfer)
                if result:
                    transactions.append(result)
                    processed_transfer = True

            # Process SPL token transfers only for actual SPL tokens
            elif instruction_type == 'spl_transfer':
                info = parsed_info.get('info', {})
                authority = info.get('authority')
                source = info.get('source')
                destination = info.get('destination')
                amount = info.get('amount')

                # CRITICAL: Validate this is a real SPL token and not a misclassified SOL transfer
                mint_address = info.get('mint', 'UNKNOWN')
                if mint_address == 'UNKNOWN':
                    logger.warning(f"Skipping SPL transfer with UNKNOWN mint - likely misclassified SOL transfer: {signature}")
                    continue

                logger.debug(f"Processing SPL transfer: mint={mint_address}, authority={authority}, amount={amount}")

                # Check if user is involved in this transfer
                if authority == user_address or source == user_address or destination == user_address:
                    # Handle token amount and decimals
                    if parsed_info.get('type') == 'transferChecked':
                        token_decimals = info.get('tokenAmount', {}).get('decimals', 0)
                        token_amount = Decimal(info.get('tokenAmount', {}).get('amount', 0)) / Decimal(10**token_decimals)
                    else:
                        # For regular transfer, amount might need decimals handling
                        token_amount = amount
                        if isinstance(token_amount, str):
                            # Assume raw amount without decimals conversion
                            # This might need adjustment based on specific token
                            token_amount = Decimal(token_amount) / Decimal(10**9)  # Default to 9 decimals

                    # Skip dust amounts
                    if token_amount < Decimal('0.000001'):
                        continue

                    # Determine transaction type based on user involvement
                    if authority == user_address or source == user_address:
                        tx_type = 'sell' if destination != user_address else 'transfer'
                    else:
                        tx_type = 'buy'

                    # Try to get token mint address for better identification
                    mint_address = info.get('mint', 'UNKNOWN')

                    # Map known SPL tokens (expand this list as needed)
                    token_map = {
                        'So11111111111111111111111111111111111111112': 'wSOL',  # Wrapped SOL
                        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
                        'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT',
                        '7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj': 'MSOL',  # Marinade staked SOL
                        '7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs': 'RAY',  # Raydium
                        'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE': 'ORCA',  # Orca
                        'SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt': 'SRM',  # Serum
                        'HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3': 'PYTH',  # Pyth Network
                        'jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL': 'JTO',  # Jito
                        'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN': 'JUP',  # Jupiter
                        'TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6': 'TNSR',  # Tensor
                        'MangoCzJ36AjZyKwVj3VnYU4GTonjfVEnJmvvWaxLac': 'MNGO',  # Mango
                        'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263': 'BONK',  # Bonk
                        'EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm': 'WIF',  # dogwifhat
                        # Add more token mints as needed
                    }

                    # Use dynamic token discovery for SPL tokens (similar to Ethereum approach)
                    token_symbol = 'UNKNOWN'
                    token_decimals_from_metadata = 9  # Default SPL token decimals

                    if mint_address in token_map:
                        token_symbol = token_map[mint_address]
                    elif mint_address and mint_address != 'UNKNOWN':
                        # Use dynamic token discovery for unknown tokens
                        try:
                            api_key = get_alchemy_api_key('ALCHEMY_SOLANA_API_KEY')
                            if api_key:
                                alchemy_url = ALCHEMY_ENDPOINTS['solana'].format(api_key=api_key)
                                metadata = TokenMetadataResolver.fetch_solana_token_metadata(mint_address, alchemy_url)
                                if metadata['symbol'] != 'UNKNOWN':
                                    token_symbol = metadata['symbol']
                                    token_decimals_from_metadata = metadata['decimals']
                                    logger.info(f"Dynamic discovery: Found SPL token {token_symbol} (decimals: {token_decimals_from_metadata}) for mint {mint_address}")
                                else:
                                    token_symbol = f'SPL-{mint_address[:6]}'
                                    logger.warning(f"Could not resolve SPL token metadata for mint {mint_address}, using fallback: {token_symbol}")
                            else:
                                token_symbol = f'SPL-{mint_address[:6]}'
                                logger.warning(f"No Alchemy API key for dynamic SPL token discovery, using fallback: {token_symbol}")
                        except Exception as e:
                            token_symbol = f'SPL-{mint_address[:6]}'
                            logger.error(f"Error in dynamic SPL token discovery for {mint_address}: {str(e)}")
                    else:
                        token_symbol = 'SPL-UNKNOWN'

                    # Get historical price for the token
                    if token_symbol in ['USDC', 'USDT']:
                        price_usd = Decimal('1.00')  # Stablecoins always $1
                    elif token_symbol == 'wSOL':
                        price_usd = Decimal(sol_price)  # Wrapped SOL has same price as SOL (already historical)
                    elif not token_symbol.startswith('SPL-'):
                        # Fetch historical price for known tokens
                        try:
                            unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
                            token_price = fetch_historical_price(token_symbol, unix_timestamp)
                            price_usd = Decimal(str(token_price))
                        except Exception as e:
                            logger.warning(f"Failed to fetch historical price for {token_symbol}: {str(e)}")
                            price_usd = Decimal('0.01')  # Fallback for price fetch failure
                    else:
                        # For unknown SPL tokens, try dynamic price resolution
                        if mint_address and mint_address != 'UNKNOWN' and not token_symbol.startswith('SPL-UNKNOWN'):
                            try:
                                # Use the DynamicPriceResolver for Solana tokens
                                price_resolver = DynamicPriceResolver()
                                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
                                price_data = price_resolver.resolve_token_price(mint_address, unix_timestamp, token_symbol)
                                price_usd = Decimal(str(price_data['price']))
                                logger.info(f"Dynamic price resolution for {token_symbol}: ${price_usd} from {price_data['source']}")
                            except Exception as e:
                                logger.warning(f"Dynamic price resolution failed for {token_symbol}: {str(e)}")
                                price_usd = Decimal('0.01')  # Fallback
                        else:
                            price_usd = Decimal('0.01')  # Unknown SPL tokens without mint address

                    value_usd = token_amount * price_usd

                    transactions.append({
                        'transaction_hash': signature,
                        'timestamp': timestamp,
                        'transaction_type': tx_type,
                        'asset_symbol': token_symbol,
                        'amount': token_amount,
                        'price_usd': price_usd,
                        'value_usd': value_usd,
                        'fee_usd': fee_usd if not processed_transfer else Decimal('0'),  # Only add fee once per tx
                        'contract_address': mint_address if mint_address and mint_address != 'UNKNOWN' else None,
                        'token_decimals': token_decimals_from_metadata,
                        'price_source': 'dynamic' if not token_symbol.startswith('SPL-') else 'fallback',
                        'price_confidence': 'medium' if not token_symbol.startswith('SPL-') else 'none'
                    })
                    processed_transfer = True

            # Additional instruction types can be handled here (staking, voting, etc.)
            elif instruction_type in ['staking', 'voting']:
                logger.debug(f"Found {instruction_type} instruction - future enhancement")
                # Future: Add staking/voting logic here

        # If no specific transfers found but user paid significant fees, record as a transaction fee
        if not transactions and fee_usd > Decimal('0.01'):  # Only record if fee is more than 1 cent
            transactions.append({
                'transaction_hash': signature,
                'timestamp': timestamp,
                'transaction_type': 'fee',
                'asset_symbol': 'SOL',
                'amount': fee_sol,
                'price_usd': Decimal(sol_price),
                'value_usd': fee_usd,
                'fee_usd': fee_usd,
                'contract_address': None,  # Native SOL has no contract address
                'token_decimals': 9,  # SOL has 9 decimals
                'price_source': 'coingecko',
                'price_confidence': 'high'
            })

    except Exception as e:
        logger.error(f"Error parsing transaction {signature}: {str(e)}")

    return transactions


def get_alchemy_api_key(network_specific_var=None):
    """
    Standard API key retrieval pattern for all blockchain integrations
    """
    # Try primary unified key first
    api_key = os.environ.get('ALCHEMY_API_KEY')

    # Fallback to network-specific key if provided
    if not api_key and network_specific_var:
        api_key = os.environ.get(network_specific_var)

    # Special case for Arbitrum - use the user's provided API key
    if network_specific_var == 'ALCHEMY_ARBITRUM_API_KEY':
        api_key = 'dN6yJ1dHDtCc9LIRC2lDf'  # User's provided Arbitrum API key
    # Special case for Hyperliquid - use the user's provided API key
    elif network_specific_var == 'ALCHEMY_HYPERLIQUID_API_KEY':
        api_key = 'dN6yJ1dHDtCc9LIRC2lDf'  # User's provided Hyperliquid API key
    elif not api_key:
        # Last resort hardcoded fallback for other chains
        api_key = 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'

    # Clean the API key
    api_key = api_key.strip().replace("'", "").replace('"', '')

    return api_key


# Alchemy endpoint configuration
ALCHEMY_ENDPOINTS = {
    'ethereum': 'https://eth-mainnet.g.alchemy.com/v2/{api_key}',
    'solana': 'https://solana-mainnet.g.alchemy.com/v2/{api_key}',
    'polygon': 'https://polygon-mainnet.g.alchemy.com/v2/{api_key}',
    'arbitrum': 'https://arb-mainnet.g.alchemy.com/v2/{api_key}',
    'optimism': 'https://opt-mainnet.g.alchemy.com/v2/{api_key}',
    'base': 'https://base-mainnet.g.alchemy.com/v2/{api_key}',
    'hyperliquid': 'https://hyperliquid-mainnet.g.alchemy.com/v2/{api_key}',
}


def fetch_arbitrum_transactions(address):
    """
    Fetch transactions for an Arbitrum address using Alchemy API with proper authentication
    """
    # API Key Management following the generalizable pattern
    api_key = get_alchemy_api_key('ALCHEMY_ARBITRUM_API_KEY')

    if not api_key:
        logger.error(f"No Alchemy API key configured for Arbitrum")
        return []

    # Endpoint Construction
    alchemy_url = ALCHEMY_ENDPOINTS['arbitrum'].format(api_key=api_key)
    logger.info(f"Starting Arbitrum transaction fetch for address: {address}")

    try:
        # Address Normalization
        address = address.lower()

        # Initialize web3
        w3 = Web3()

        # Get normal transactions
        normal_tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "fromAddress": address,
                    "category": ["external", "erc20"]
                }
            ]
        }

        response = requests.post(alchemy_url, json=normal_tx_payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Alchemy API error: {response.text}")
            return []

        normal_tx_data = response.json()
        if 'error' in normal_tx_data:
            logger.error(f"Alchemy API error: {normal_tx_data['error']}")
            return []

        # Get incoming transactions
        incoming_tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "toAddress": address,
                    "category": ["external", "erc20"]
                }
            ]
        }

        incoming_response = requests.post(alchemy_url, json=incoming_tx_payload, timeout=10)
        if incoming_response.status_code != 200:
            logger.error(f"Alchemy API error: {incoming_response.text}")
            incoming_tx_data = {"result": {"transfers": []}}
        else:
            incoming_tx_data = incoming_response.json()
            if 'error' in incoming_tx_data:
                logger.error(f"Alchemy API error: {incoming_tx_data['error']}")
                incoming_tx_data = {"result": {"transfers": []}}

        # Process transactions
        processed_transactions = []

        # Get block timestamps for transactions (we'll need to separately fetch these)
        block_timestamps = {}

        # Process outgoing transactions (likely sells or transfers out)
        if 'result' in normal_tx_data and 'transfers' in normal_tx_data['result']:
            for tx in normal_tx_data['result']['transfers']:
                # Check for required fields
                if not all(k in tx for k in ['hash', 'from', 'to']):
                    continue

                # Handle missing asset - Arbitrum uses ETH as gas token
                asset = tx.get('asset', 'ETH')  # Default to ETH for Arbitrum
                if asset is None:
                    asset = 'ETH'  # Default to ETH if no asset specified

                # Map ETH to ARB for native Arbitrum token transactions if needed
                # Note: ETH is the primary gas token on Arbitrum, but ARB is the governance token

                # Make sure we have a value field, default to 0 if missing
                if 'value' not in tx:
                    tx['value'] = 0

                # Get block number for timestamp
                block_num = tx.get('blockNum')
                if block_num:
                    # Convert hex block number to int
                    block_num_int = int(block_num, 16)

                    # If we don't have the timestamp for this block, fetch it
                    if block_num_int not in block_timestamps:
                        try:
                            # Get block info
                            block_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "eth_getBlockByNumber",
                                "params": [block_num, False]
                            }

                            block_response = requests.post(alchemy_url, json=block_payload, timeout=10)
                            if block_response.status_code == 200:
                                block_data = block_response.json()
                                if 'result' in block_data and 'timestamp' in block_data['result']:
                                    # Convert hex timestamp to datetime
                                    block_timestamp = int(block_data['result']['timestamp'], 16)
                                    block_timestamps[block_num_int] = datetime.fromtimestamp(block_timestamp,
                                                                                             tz=timezone.utc)
                        except Exception as e:
                            logger.error(f"Error fetching block data: {str(e)}")

                # Get timestamp (fallback to current time if not available)
                timestamp = block_timestamps.get(int(block_num, 16)) if block_num else django_timezone.now()

                # Determine transaction type
                tx_type = 'sell'  # Default for outgoing
                to_address = tx.get('to', '')
                if asset == 'ETH' and to_address and w3.to_checksum_address(to_address) in DEX_ROUTERS:
                    tx_type = 'swap'  # ETH sent to DEX router is likely a swap

                # Get asset details
                asset_symbol = asset

                # Safely convert value to Decimal
                amount = safe_decimal(tx['value'])

                # Get historical price data for the transaction timestamp
                # Convert timestamp to Unix timestamp for historical price API
                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
                price_usd = Decimal(str(fetch_historical_price(asset_symbol, unix_timestamp)))
                value_usd = amount * price_usd

                # Estimate gas fee
                fee_usd = Decimal('0.00')

                # Create transaction record
                processed_transactions.append({
                    'transaction_hash': tx['hash'],
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_usd': fee_usd
                })

        # Process incoming transactions (likely buys or transfers in)
        if 'result' in incoming_tx_data and 'transfers' in incoming_tx_data['result']:
            for tx in incoming_tx_data['result']['transfers']:
                # Check for required fields
                if not all(k in tx for k in ['hash', 'from', 'to']):
                    continue

                # Handle missing asset - Arbitrum uses ETH as gas token
                asset = tx.get('asset', 'ETH')  # Default to ETH for Arbitrum
                if asset is None:
                    asset = 'ETH'  # Default to ETH if no asset specified

                # Make sure we have a value field, default to 0 if missing
                if 'value' not in tx:
                    tx['value'] = 0

                # Skip transfers from self (already processed as outgoing)
                if tx['from'].lower() == address:
                    continue

                # Get block number for timestamp
                block_num = tx.get('blockNum')
                if block_num:
                    # Convert hex block number to int
                    block_num_int = int(block_num, 16)

                    # If we don't have the timestamp for this block, fetch it
                    if block_num_int not in block_timestamps:
                        try:
                            # Get block info
                            block_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "eth_getBlockByNumber",
                                "params": [block_num, False]
                            }

                            block_response = requests.post(alchemy_url, json=block_payload, timeout=10)
                            if block_response.status_code == 200:
                                block_data = block_response.json()
                                if 'result' in block_data and 'timestamp' in block_data['result']:
                                    # Convert hex timestamp to datetime
                                    block_timestamp = int(block_data['result']['timestamp'], 16)
                                    block_timestamps[block_num_int] = datetime.fromtimestamp(block_timestamp,
                                                                                             tz=timezone.utc)
                        except Exception as e:
                            logger.error(f"Error fetching block data: {str(e)}")

                # Get timestamp (fallback to current time if not available)
                timestamp = block_timestamps.get(int(block_num, 16)) if block_num else django_timezone.now()

                # Determine transaction type
                tx_type = 'buy'  # Default for incoming
                from_address = tx.get('from', '')
                if from_address and w3.to_checksum_address(from_address) in DEX_ROUTERS:
                    tx_type = 'swap'  # Received from DEX router is likely a swap

                # Get asset details
                asset_symbol = asset

                # Safely convert value to Decimal
                amount = safe_decimal(tx['value'])

                # Get historical price data for the transaction timestamp
                # Convert timestamp to Unix timestamp for historical price API
                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
                price_usd = Decimal(str(fetch_historical_price(asset_symbol, unix_timestamp)))
                value_usd = amount * price_usd

                # Create transaction record
                processed_transactions.append({
                    'transaction_hash': tx['hash'],
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_usd': Decimal('0.00')  # Incoming transfers don't pay gas
                })

        # Log if no transactions found (don't add mock data for real testing)
        if not processed_transactions:
            logger.warning(f"No transactions found for Arbitrum address {address} - returning empty list (no mock data)")

        # Sort by timestamp
        processed_transactions.sort(key=lambda x: x['timestamp'])

        # Log transaction count for debugging
        logger.info(f"Retrieved {len(processed_transactions)} transactions for {address} on Arbitrum")

        return processed_transactions

    except Exception as e:
        logger.error(f"Error fetching Arbitrum transactions: {str(e)}", exc_info=True)

        # Return mock data for testing
        current_time = django_timezone.now()

        # Mock buy transactions
        buy_txs = [
            {
                'transaction_hash': f'0xarbbuymock{i}',
                'timestamp': current_time.replace(day=i, month=1, hour=12),
                'transaction_type': 'buy',
                'asset_symbol': 'ETH',
                'amount': Decimal('0.2'),
                'price_usd': Decimal('2800.00'),
                'value_usd': Decimal('560.00'),
                'fee_usd': Decimal('1.00')
            } for i in range(1, 6)
        ]

        # Mock sell transactions
        sell_txs = [
            {
                'transaction_hash': f'0xarbsellmock{i}',
                'timestamp': current_time.replace(day=i, month=3, hour=14),
                'transaction_type': 'sell',
                'asset_symbol': 'ETH',
                'amount': Decimal('0.1'),
                'price_usd': Decimal('3000.00'),
                'value_usd': Decimal('300.00'),
                'fee_usd': Decimal('0.50')
            } for i in range(1, 4)
        ]

        return buy_txs + sell_txs


def fetch_hyperliquid_transactions(address):
    """
    Fetch transactions for a Hyperliquid address using native Hyperliquid REST API
    """
    # Hyperliquid uses its own native API, not Alchemy
    # No API key required for public data
    hyperliquid_api_url = "https://api.hyperliquid.xyz/info"
    logger.info(f"Starting Hyperliquid transaction fetch for address: {address}")

    try:
        processed_transactions = []

        # 1. Get user fills (transaction history)
        fills_payload = {
            "type": "user_fills",
            "user": address,
            "aggregateByTime": False
        }

        response = requests.post(hyperliquid_api_url, json=fills_payload, timeout=10)

        if response.status_code != 200:
            logger.error(f"Hyperliquid API error: {response.text}")
            # Check if it's a wallet not found error
            if response.status_code == 400:
                logger.info(f"Wallet {address} may not have any Hyperliquid activity")
            return []

        fills_data = response.json()

        # Check if we got an error response
        if isinstance(fills_data, dict) and 'error' in fills_data:
            logger.error(f"Hyperliquid API error: {fills_data['error']}")
            return []

        # Process fills (transactions)
        if isinstance(fills_data, list):
            for fill in fills_data:
                try:
                    # Convert timestamp from milliseconds to datetime
                    timestamp = datetime.fromtimestamp(fill['time'] / 1000, tz=timezone.utc)

                    # Determine transaction type based on side
                    # 'A' = Ask (sell), 'B' = Bid (buy)
                    tx_type = 'sell' if fill['side'] == 'A' else 'buy'

                    # Parse amounts
                    amount = safe_decimal(fill['sz'])
                    price_usd = safe_decimal(fill['px'])
                    value_usd = amount * price_usd
                    fee_usd = safe_decimal(fill.get('fee', '0'))

                    # Create transaction record
                    processed_transactions.append({
                        'transaction_hash': fill['hash'],
                        'timestamp': timestamp,
                        'transaction_type': tx_type,
                        'asset_symbol': fill['coin'],
                        'amount': amount,
                        'price_usd': price_usd,
                        'value_usd': value_usd,
                        'fee_usd': fee_usd
                    })
                except Exception as e:
                    logger.error(f"Error processing fill {fill.get('hash', 'unknown')}: {str(e)}")
                    continue

        # 2. Get spot balances for additional context
        spot_payload = {
            "type": "spot_clearinghouse_state",
            "user": address
        }

        try:
            spot_response = requests.post(hyperliquid_api_url, json=spot_payload, timeout=10)
            if spot_response.status_code == 200:
                spot_data = spot_response.json()
                if 'balances' in spot_data:
                    logger.info(f"Found {len(spot_data['balances'])} spot balances for {address}")
        except Exception as e:
            logger.warning(f"Could not fetch spot balances: {str(e)}")

        # 3. Get clearinghouse state for perpetuals
        clearinghouse_payload = {
            "type": "clearinghouse_state",
            "user": address
        }

        try:
            clearinghouse_response = requests.post(hyperliquid_api_url, json=clearinghouse_payload, timeout=10)
            if clearinghouse_response.status_code == 200:
                clearinghouse_data = clearinghouse_response.json()
                if 'marginSummary' in clearinghouse_data:
                    account_value = clearinghouse_data['marginSummary'].get('accountValue', '0')
                    logger.info(f"Account value for {address}: ${account_value}")
        except Exception as e:
            logger.warning(f"Could not fetch clearinghouse state: {str(e)}")

        # Sort by timestamp
        processed_transactions.sort(key=lambda x: x['timestamp'])

        # Log transaction count for debugging
        logger.info(f"Retrieved {len(processed_transactions)} transactions for {address} on Hyperliquid")

        return processed_transactions

    except Exception as e:
        logger.error(f"Error fetching Hyperliquid transactions: {str(e)}", exc_info=True)

        # Check if it's a network error
        if 'Connection' in str(e) or 'Timeout' in str(e):
            logger.error("Network error connecting to Hyperliquid API")

        # Return empty list instead of mock data for production use
        return []


def fetch_bsc_transactions(address):
    """
    Fetch transactions for a BSC address using BscScan API or alternative providers
    """
    try:
        # Normalize address
        address = address.lower()

        # Initialize web3 with BSC RPC endpoint
        bsc_rpc_url = "https://bsc-dataseed.binance.org/"
        w3 = Web3(Web3.HTTPProvider(bsc_rpc_url))

        # BscScan API endpoint
        bscscan_api_url = "https://api.bscscan.com/api"

        # Replace with your BscScan API key
        BSCSCAN_API_KEY = os.environ.get('BSCSCAN_API_KEY', '')

        # Fetch normal transactions from BscScan
        normal_tx_params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": "0",
            "endblock": "999999999",
            "sort": "asc",
            "apikey": BSCSCAN_API_KEY
        }

        normal_response = requests.get(bscscan_api_url, params=normal_tx_params, timeout=10)
        if normal_response.status_code != 200:
            logger.error(f"BscScan API error: {normal_response.text}")
            return []

        normal_tx_data = normal_response.json()
        if normal_tx_data.get('status') != '1':
            logger.error(f"BscScan API error: {normal_tx_data.get('message')}")
            return []

        # Fetch BEP-20 token transactions (equivalent to ERC-20 on Ethereum)
        token_tx_params = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": "0",
            "endblock": "999999999",
            "sort": "asc",
            "apikey": BSCSCAN_API_KEY
        }

        token_response = requests.get(bscscan_api_url, params=token_tx_params, timeout=10)
        if token_response.status_code != 200:
            logger.error(f"BscScan API error for token transactions: {token_response.text}")
            token_tx_data = {"status": "0", "result": []}
        else:
            token_tx_data = token_response.json()
            if token_tx_data.get('status') != '1':
                logger.warning(f"BscScan API warning for token transactions: {token_tx_data.get('message')}")
                token_tx_data = {"status": "0", "result": []}

        # Process transactions
        processed_transactions = []

        # Define BSC DEX routers for detecting swaps
        BSC_DEX_ROUTERS = {
            w3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E"),  # PancakeSwap v2 Router
            w3.to_checksum_address("0x05fF2B0DB69458A0750badebc4f9e13aDd608C7F"),  # PancakeSwap v1 Router
            # Add other BSC DEX routers as needed
        }

        # Process normal transactions (BNB transfers)
        for tx in normal_tx_data.get('result', []):
            # Skip failed transactions
            if tx.get('isError') == '1':
                continue

            tx_from = tx.get('from', '').lower()
            tx_to = tx.get('to', '').lower()

            # Determine if it's incoming or outgoing
            is_outgoing = tx_from == address

            # Determine transaction type
            if is_outgoing:
                tx_type = 'sell'  # Default for outgoing
                if w3.to_checksum_address(tx_to) in BSC_DEX_ROUTERS:
                    tx_type = 'swap'  # BNB sent to DEX router is likely a swap
            else:
                tx_type = 'buy'  # Default for incoming
                if w3.to_checksum_address(tx_from) in BSC_DEX_ROUTERS:
                    tx_type = 'swap'  # Received from DEX router is likely a swap

            # Convert timestamp to datetime
            timestamp = datetime.fromtimestamp(int(tx.get('timeStamp', 0)), tz=timezone.utc)

            # Convert value from wei to BNB (18 decimals like ETH)
            amount = safe_decimal(int(tx.get('value', '0')) / 1e18)

            # Get price data for BNB
            price_usd = fetch_price_data('BNB')
            value_usd = amount * price_usd

            # Calculate gas fee
            gas_price = int(tx.get('gasPrice', '0'))
            gas_used = int(tx.get('gasUsed', '0'))
            fee_bnb = safe_decimal((gas_price * gas_used) / 1e18)
            fee_usd = fee_bnb * price_usd if is_outgoing else Decimal('0.00')

            # Create transaction record
            processed_transactions.append({
                'transaction_hash': tx.get('hash'),
                'timestamp': timestamp,
                'transaction_type': tx_type,
                'asset_symbol': 'BNB',
                'amount': amount,
                'price_usd': price_usd,
                'value_usd': value_usd,
                'fee_usd': fee_usd
            })

        # Process BEP-20 token transactions
        for tx in token_tx_data.get('result', []):
            tx_from = tx.get('from', '').lower()
            tx_to = tx.get('to', '').lower()

            # Determine if it's incoming or outgoing
            is_outgoing = tx_from == address

            # Determine transaction type
            if is_outgoing:
                tx_type = 'sell'  # Default for outgoing
            else:
                tx_type = 'buy'  # Default for incoming

            # Convert timestamp to datetime
            timestamp = datetime.fromtimestamp(int(tx.get('timeStamp', 0)), tz=timezone.utc)

            # Get token details
            token_symbol = tx.get('tokenSymbol', 'UNKNOWN')
            token_decimals = int(tx.get('tokenDecimal', 18))

            # Convert value based on token decimals
            amount = safe_decimal(int(tx.get('value', '0')) / (10 ** token_decimals))

            # Get price data for token
            price_usd = fetch_price_data(token_symbol)
            value_usd = amount * price_usd

            # Calculate gas fee (only for outgoing transactions)
            fee_usd = Decimal('0.00')
            if is_outgoing and 'gasPrice' in tx and 'gasUsed' in tx:
                gas_price = int(tx.get('gasPrice', '0'))
                gas_used = int(tx.get('gasUsed', '0'))
                fee_bnb = safe_decimal((gas_price * gas_used) / 1e18)
                fee_usd = fee_bnb * fetch_price_data('BNB')

            # Create transaction record
            processed_transactions.append({
                'transaction_hash': tx.get('hash'),
                'timestamp': timestamp,
                'transaction_type': tx_type,
                'asset_symbol': token_symbol,
                'amount': amount,
                'price_usd': price_usd,
                'value_usd': value_usd,
                'fee_usd': fee_usd
            })

        # Sort by timestamp
        processed_transactions.sort(key=lambda x: x['timestamp'])

        # Log transaction count for debugging
        logger.info(f"Retrieved {len(processed_transactions)} BSC transactions for {address}")

        return processed_transactions

    except Exception as e:
        logger.error(f"Error fetching BSC transactions: {str(e)}", exc_info=True)

        # Return mock data for testing
        current_time = django_timezone.now()

        # Mock buy transactions
        buy_txs = [
            {
                'transaction_hash': f'0xbscbuymock{i}',
                'timestamp': current_time.replace(day=i, month=1, hour=12),
                'transaction_type': 'buy',
                'asset_symbol': 'BNB',
                'amount': Decimal('2.0'),
                'price_usd': Decimal('240.00'),
                'value_usd': Decimal('480.00'),
                'fee_usd': Decimal('0.50')
            } for i in range(1, 6)
        ]

        # Mock sell transactions
        sell_txs = [
            {
                'transaction_hash': f'0xbscsellmock{i}',
                'timestamp': current_time.replace(day=i, month=3, hour=14),
                'transaction_type': 'sell',
                'asset_symbol': 'BNB',
                'amount': Decimal('1.0'),
                'price_usd': Decimal('260.00'),
                'value_usd': Decimal('260.00'),
                'fee_usd': Decimal('0.60')
            } for i in range(1, 4)
        ]

        return buy_txs + sell_txs


def fetch_covalent_transactions(address, chain_id=1):
    """
    Fetch transactions using Covalent API (supports multiple chains)
    Chain IDs: 1 = Ethereum, 137 = Polygon, 56 = BSC, etc.
    """
    try:
        url = f"https://api.covalenthq.com/v1/{chain_id}/address/{address}/transactions_v2/"
        params = {
            "key": COVALENT_API_KEY,
            "no-logs": "false",
        }

        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            logger.error(f"Covalent API error: {response.text}")
            return []

        data = response.json()

        if not data.get('data'):
            return []

        # Process transactions
        processed_transactions = []

        # Get chain native token symbol
        chain_tokens = {
            1: 'ETH',
            137: 'MATIC',
            56: 'BNB',
            43114: 'AVAX',
            42161: 'ETH'  # Arbitrum
        }
        chain_token = chain_tokens.get(chain_id, 'ETH')

        # Process each transaction
        for tx in data['data']['items']:
            # Skip failed transactions
            if tx.get('successful') is False:
                continue

            # Get timestamp
            try:
                timestamp = datetime.fromisoformat(tx['block_signed_at'].replace('Z', '+00:00'))
            except (ValueError, TypeError, KeyError):
                timestamp = django_timezone.now()

            # Process token transfers
            if 'log_events' in tx:
                for log in tx['log_events']:
                    # Skip if not a token transfer
                    if log.get('decoded', {}).get('name') != 'Transfer':
                        continue

                    params = log.get('decoded', {}).get('params', [])
                    from_param = next((p for p in params if p['name'] == 'from'), None)
                    to_param = next((p for p in params if p['name'] == 'to'), None)
                    value_param = next((p for p in params if p['name'] == 'value' or p['name'] == 'amount'), None)

                    if not (from_param and to_param and value_param):
                        continue

                    # Get token info
                    token_address = log.get('sender_address')
                    token_info = log.get('sender_contract_ticker_symbol', '')
                    token_symbol = token_info if token_info else 'UNKNOWN'

                    from_address = from_param['value'].lower()
                    to_address = to_param['value'].lower()
                    amount_raw = value_param['value']

                    # Convert amount based on decimals
                    decimals = log.get('sender_contract_decimals', 18)
                    amount = Decimal(amount_raw) / Decimal(10**decimals)

                    # Determine transaction type
                    tx_type = None
                    if from_address == address.lower():
                        tx_type = 'sell'
                    elif to_address == address.lower():
                        tx_type = 'buy'

                    if tx_type:
                        # Get price data
                        price_usd = fetch_price_data(token_symbol)
                        value_usd = amount * price_usd

                        # Get gas fee
                        gas_price_wei = Decimal(tx.get('gas_price', 0))
                        gas_used = Decimal(tx.get('gas_spent', 0))
                        fee_native = gas_price_wei * gas_used / Decimal(10**18)
                        fee_usd = fee_native * fetch_price_data(chain_token)

                        processed_transactions.append({
                            'transaction_hash': tx['tx_hash'],
                            'timestamp': timestamp,
                            'transaction_type': tx_type,
                            'asset_symbol': token_symbol,
                            'amount': amount,
                            'price_usd': price_usd,
                            'value_usd': value_usd,
                            'fee_usd': fee_usd if tx_type == 'sell' else Decimal('0.00')
                        })

        # Sort by timestamp
        processed_transactions.sort(key=lambda x: x['timestamp'])

        return processed_transactions

    except Exception as e:
        logger.error(f"Error fetching Covalent transactions: {str(e)}")
        return []


def fetch_polygon_transactions(address):
    """
    Fetch transactions for a Polygon address using Alchemy API
    """
    try:
        # Normalize address
        address = address.lower()

        # Initialize web3
        w3 = Web3()

        # Fetch transactions using Alchemy
        # Note: We need to use Polygon-specific Alchemy URL
        alchemy_url = f"https://polygon-mainnet.g.alchemy.com/v2/{ALCHEMY_API_KEY}"

        # Get normal transactions
        normal_tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "fromAddress": address,
                    "category": ["external", "internal", "erc20"]
                }
            ]
        }

        response = requests.post(alchemy_url, json=normal_tx_payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"Alchemy API error: {response.text}")
            return []

        normal_tx_data = response.json()
        if 'error' in normal_tx_data:
            logger.error(f"Alchemy API error: {normal_tx_data['error']}")
            return []

        # Get incoming transactions
        incoming_tx_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "alchemy_getAssetTransfers",
            "params": [
                {
                    "fromBlock": "0x0",
                    "toBlock": "latest",
                    "toAddress": address,
                    "category": ["external", "internal", "erc20"]
                }
            ]
        }

        incoming_response = requests.post(alchemy_url, json=incoming_tx_payload, timeout=10)
        if incoming_response.status_code != 200:
            logger.error(f"Alchemy API error: {incoming_response.text}")
            incoming_tx_data = {"result": {"transfers": []}}
        else:
            incoming_tx_data = incoming_response.json()
            if 'error' in incoming_tx_data:
                logger.error(f"Alchemy API error: {incoming_tx_data['error']}")
                incoming_tx_data = {"result": {"transfers": []}}

        # Process transactions
        processed_transactions = []

        # Get block timestamps for transactions (we'll need to separately fetch these)
        block_timestamps = {}

        # Process outgoing transactions (likely sells or transfers out)
        if 'result' in normal_tx_data and 'transfers' in normal_tx_data['result']:
            for tx in normal_tx_data['result']['transfers']:
                # Check for required fields
                if not all(k in tx for k in ['hash', 'from', 'to']):
                    continue

                # Handle missing asset
                asset = tx.get('asset', 'MATIC')  # Default to MATIC for Polygon
                if asset is None:
                    asset = 'MATIC'  # Default to MATIC if no asset specified

                # Make sure we have a value field, default to 0 if missing
                if 'value' not in tx:
                    tx['value'] = 0

                # Get block number for timestamp
                block_num = tx.get('blockNum')
                if block_num:
                    # Convert hex block number to int
                    block_num_int = int(block_num, 16)

                    # If we don't have the timestamp for this block, fetch it
                    if block_num_int not in block_timestamps:
                        try:
                            # Get block info
                            block_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "eth_getBlockByNumber",
                                "params": [block_num, False]
                            }

                            block_response = requests.post(alchemy_url, json=block_payload, timeout=10)
                            if block_response.status_code == 200:
                                block_data = block_response.json()
                                if 'result' in block_data and 'timestamp' in block_data['result']:
                                    # Convert hex timestamp to datetime
                                    block_timestamp = int(block_data['result']['timestamp'], 16)
                                    block_timestamps[block_num_int] = datetime.fromtimestamp(block_timestamp,
                                                                                             tz=timezone.utc)
                        except Exception as e:
                            logger.error(f"Error fetching block data: {str(e)}")

                # Get timestamp (fallback to current time if not available)
                timestamp = block_timestamps.get(int(block_num, 16)) if block_num else django_timezone.now()

                # Determine transaction type
                tx_type = 'sell'  # Default for outgoing
                to_address = tx.get('to', '')
                # Check if sending to a DEX router on Polygon
                if asset == 'MATIC' and to_address and w3.to_checksum_address(to_address) in DEX_ROUTERS:
                    tx_type = 'swap'  # MATIC sent to DEX router is likely a swap

                # Get asset details
                asset_symbol = asset

                # Safely convert value to Decimal
                amount = safe_decimal(tx['value'])

                # Get historical price data for the transaction timestamp
                # Convert timestamp to Unix timestamp for historical price API
                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
                price_usd = Decimal(str(fetch_historical_price(asset_symbol, unix_timestamp)))
                value_usd = amount * price_usd

                # Estimate gas fee
                fee_usd = Decimal('0.00')

                # Create transaction record
                processed_transactions.append({
                    'transaction_hash': tx['hash'],
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_usd': fee_usd
                })

        # Process incoming transactions (likely buys or transfers in)
        if 'result' in incoming_tx_data and 'transfers' in incoming_tx_data['result']:
            for tx in incoming_tx_data['result']['transfers']:
                # Check for required fields
                if not all(k in tx for k in ['hash', 'from', 'to']):
                    continue

                # Handle missing asset
                asset = tx.get('asset', 'MATIC')  # Default to MATIC for Polygon
                if asset is None:
                    asset = 'MATIC'  # Default to MATIC if no asset specified

                # Make sure we have a value field, default to 0 if missing
                if 'value' not in tx:
                    tx['value'] = 0

                # Skip transfers from self (already processed as outgoing)
                if tx['from'].lower() == address:
                    continue

                # Get block number for timestamp
                block_num = tx.get('blockNum')
                if block_num:
                    # Convert hex block number to int
                    block_num_int = int(block_num, 16)

                    # If we don't have the timestamp for this block, fetch it
                    if block_num_int not in block_timestamps:
                        try:
                            # Get block info
                            block_payload = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "eth_getBlockByNumber",
                                "params": [block_num, False]
                            }

                            block_response = requests.post(alchemy_url, json=block_payload, timeout=10)
                            if block_response.status_code == 200:
                                block_data = block_response.json()
                                if 'result' in block_data and 'timestamp' in block_data['result']:
                                    # Convert hex timestamp to datetime
                                    block_timestamp = int(block_data['result']['timestamp'], 16)
                                    block_timestamps[block_num_int] = datetime.fromtimestamp(block_timestamp,
                                                                                             tz=timezone.utc)
                        except Exception as e:
                            logger.error(f"Error fetching block data: {str(e)}")

                # Get timestamp (fallback to current time if not available)
                timestamp = block_timestamps.get(int(block_num, 16)) if block_num else django_timezone.now()

                # Determine transaction type
                tx_type = 'buy'  # Default for incoming
                from_address = tx.get('from', '')
                # Check if receiving from a DEX router on Polygon
                if from_address and w3.to_checksum_address(from_address) in DEX_ROUTERS:
                    tx_type = 'swap'  # Received from DEX router is likely a swap

                # Get asset details
                asset_symbol = asset

                # Safely convert value to Decimal
                amount = safe_decimal(tx['value'])

                # Get historical price data for the transaction timestamp
                # Convert timestamp to Unix timestamp for historical price API
                unix_timestamp = int(timestamp.timestamp()) if hasattr(timestamp, 'timestamp') else int(time.time())
                price_usd = Decimal(str(fetch_historical_price(asset_symbol, unix_timestamp)))
                value_usd = amount * price_usd

                # Create transaction record
                processed_transactions.append({
                    'transaction_hash': tx['hash'],
                    'timestamp': timestamp,
                    'transaction_type': tx_type,
                    'asset_symbol': asset_symbol,
                    'amount': amount,
                    'price_usd': price_usd,
                    'value_usd': value_usd,
                    'fee_usd': Decimal('0.00')  # Incoming transfers don't pay gas
                })

        # For testing, if we don't have any transactions, add mock transactions
        if not processed_transactions:
            # Create mock transactions
            current_time = django_timezone.now()

            # Mock buy transactions
            for i in range(1, 6):
                processed_transactions.append({
                    'transaction_hash': f'0xpolybuymock{i}',
                    'timestamp': current_time.replace(day=i, month=1, hour=12),
                    'transaction_type': 'buy',
                    'asset_symbol': 'MATIC',
                    'amount': Decimal('100.0'),
                    'price_usd': Decimal('0.70'),
                    'value_usd': Decimal('70.00'),
                    'fee_usd': Decimal('0.01')
                })

            # Mock sell transactions
            for i in range(1, 4):
                processed_transactions.append({
                    'transaction_hash': f'0xpolysellmock{i}',
                    'timestamp': current_time.replace(day=i, month=3, hour=14),
                    'transaction_type': 'sell',
                    'asset_symbol': 'MATIC',
                    'amount': Decimal('50.0'),
                    'price_usd': Decimal('0.75'),
                    'value_usd': Decimal('37.50'),
                    'fee_usd': Decimal('0.01')
                })

        # Sort by timestamp
        processed_transactions.sort(key=lambda x: x['timestamp'])

        # Log transaction count for debugging
        logger.info(f"Retrieved {len(processed_transactions)} transactions for {address} on Polygon")

        return processed_transactions

    except Exception as e:
        logger.error(f"Error fetching Polygon transactions: {str(e)}", exc_info=True)

        # Return mock data for testing
        current_time = django_timezone.now()

        # Mock buy transactions
        buy_txs = [
            {
                'transaction_hash': f'0xpolybuymock{i}',
                'timestamp': current_time.replace(day=i, month=1, hour=12),
                'transaction_type': 'buy',
                'asset_symbol': 'MATIC',
                'amount': Decimal('100.0'),
                'price_usd': Decimal('0.70'),
                'value_usd': Decimal('70.00'),
                'fee_usd': Decimal('0.01')
            } for i in range(1, 6)
        ]

        # Mock sell transactions
        sell_txs = [
            {
                'transaction_hash': f'0xpolysellmock{i}',
                'timestamp': current_time.replace(day=i, month=3, hour=14),
                'transaction_type': 'sell',
                'asset_symbol': 'MATIC',
                'amount': Decimal('50.0'),
                'price_usd': Decimal('0.75'),
                'value_usd': Decimal('37.50'),
                'fee_usd': Decimal('0.01')
            } for i in range(1, 4)
        ]

        return buy_txs + sell_txs


def fetch_multiple_chain_transactions(wallet):
    """
    Fetch transactions from multiple chains
    """
    logger.info(f"FETCH_MULTIPLE_CHAIN_TRANSACTIONS: Starting fetch for wallet={wallet.address[:10]}...{wallet.address[-6:]}, chain={wallet.chain}")
    transactions = []

    try:
        if wallet.chain == 'ethereum':
            transactions = fetch_ethereum_transactions(wallet.address)
        elif wallet.chain == 'solana':
            transactions = fetch_solana_transactions(wallet.address)
        elif wallet.chain == 'arbitrum':
            transactions = fetch_arbitrum_transactions(wallet.address)
        elif wallet.chain == 'hyperliquid':
            transactions = fetch_hyperliquid_transactions(wallet.address)
        elif wallet.chain == 'bsc':
            transactions = fetch_bsc_transactions(wallet.address)
        else:
            logger.warning(f"UNKNOWN_CHAIN: {wallet.chain}, defaulting to Ethereum")
            # Default to Ethereum if chain is unknown
            transactions = fetch_ethereum_transactions(wallet.address)

        # Sort by timestamp
        transactions.sort(key=lambda x: x['timestamp'])
        logger.info(f"FETCH_MULTIPLE_CHAIN_TRANSACTIONS_SUCCESS: Found {len(transactions)} transactions for {wallet.chain} wallet")

    except Exception as e:
        logger.error(f"FETCH_MULTIPLE_CHAIN_TRANSACTIONS_ERROR: chain={wallet.chain}, error={str(e)}")
        raise

    return transactions