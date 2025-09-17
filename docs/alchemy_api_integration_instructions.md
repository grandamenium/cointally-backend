# Alchemy API Integration Instructions

## Overview
This document provides comprehensive instructions for integrating blockchain networks through Alchemy APIs. It covers the current implementations for Solana and Ethereum and provides a generalizable framework for adding new blockchain networks.

## Table of Contents
1. [API Key Management](#api-key-management)
2. [Endpoint Structure](#endpoint-structure)
3. [Current Implementations](#current-implementations)
4. [Generalizable Pattern](#generalizable-pattern)
5. [Adding New Blockchain Networks](#adding-new-blockchain-networks)
6. [Error Handling](#error-handling)
7. [Price Data Integration](#price-data-integration)
8. [Testing Strategy](#testing-strategy)

## API Key Management

### Environment Variables Structure
```bash
# Primary unified API key (works for multiple networks)
ALCHEMY_API_KEY='PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'

# Network-specific keys (optional fallbacks)
ALCHEMY_SOLANA_API_KEY='dN6yJ1dHDtCc9LIRIC2lDf'
ALCHEMY_ETHEREUM_API_KEY='network_specific_key_if_needed'
```

### API Key Priority Logic
All blockchain integration functions follow this priority pattern:
1. **Primary Key**: Try `ALCHEMY_API_KEY` (unified key that works across networks)
2. **Network-Specific Key**: Fallback to network-specific environment variable
3. **Hardcoded Fallback**: Use known working key as last resort
4. **Key Cleaning**: Strip quotes and extra spaces

```python
def get_alchemy_api_key(network_specific_var=None):
    """
    Standard API key retrieval pattern for all blockchain integrations
    """
    # Try primary unified key first
    api_key = os.environ.get('ALCHEMY_API_KEY')

    # Fallback to network-specific key if provided
    if not api_key and network_specific_var:
        api_key = os.environ.get(network_specific_var)

    # Last resort hardcoded fallback
    if not api_key:
        api_key = 'PHwvYViFcbMNwC8Tb_FI06AnU9LId5S9'

    # Clean the API key
    api_key = api_key.strip().replace("'", "").replace('"', '')

    return api_key
```

## Endpoint Structure

### Alchemy URL Pattern
All Alchemy endpoints follow this structure:
```
https://{network}-{environment}.g.alchemy.com/v2/{api_key}
```

### Network-Specific Endpoints
```python
ALCHEMY_ENDPOINTS = {
    'ethereum': 'https://eth-mainnet.g.alchemy.com/v2/{api_key}',
    'solana': 'https://solana-mainnet.g.alchemy.com/v2/{api_key}',
    'polygon': 'https://polygon-mainnet.g.alchemy.com/v2/{api_key}',
    'arbitrum': 'https://arb-mainnet.g.alchemy.com/v2/{api_key}',
    'optimism': 'https://opt-mainnet.g.alchemy.com/v2/{api_key}',
    'base': 'https://base-mainnet.g.alchemy.com/v2/{api_key}',
}
```

## Current Implementations

### Solana Implementation (`fetch_solana_transactions`)

**Key Features:**
- Uses `getSignaturesForAddress` to get transaction signatures
- Implements pagination with `before` parameter
- Uses `getTransaction` with `jsonParsed` encoding for SPL token parsing
- Handles native SOL and SPL token transfers
- Supports staking, unstaking, and reward transactions

**API Methods Used:**
```python
# Get transaction signatures
"method": "getSignaturesForAddress"
"params": [address, {"limit": 1000, "before": pagination_signature}]

# Get transaction details
"method": "getTransaction"
"params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
```

**Transaction Types Detected:**
- Native SOL transfers
- SPL token transfers (USDC, USDT, wSOL)
- Staking operations
- Rewards
- DeFi interactions

### Ethereum Implementation (`fetch_ethereum_transactions`)

**Key Features:**
- Uses `alchemy_getAssetTransfers` for comprehensive transfer detection
- Handles ETH and ERC-20 token transfers
- Fetches block timestamps for accurate dating
- Detects DEX interactions through router addresses

**API Methods Used:**
```python
# Get asset transfers (outgoing)
"method": "alchemy_getAssetTransfers"
"params": [{
    "fromBlock": "0x0",
    "toBlock": "latest",
    "fromAddress": address,
    "category": ["external", "internal", "erc20", "erc721", "erc1155"]
}]

# Get asset transfers (incoming)
"method": "alchemy_getAssetTransfers"
"params": [{
    "fromBlock": "0x0",
    "toBlock": "latest",
    "toAddress": address,
    "category": ["external", "internal", "erc20"]
}]

# Get block timestamps
"method": "eth_getBlockByNumber"
"params": [block_number, False]
```

**Transaction Types Detected:**
- Native ETH transfers
- ERC-20 token transfers
- DEX swaps (detected via router addresses)
- NFT transfers (ERC-721, ERC-1155)

## Generalizable Pattern

### Standard Function Template
```python
def fetch_{network}_transactions(address):
    """
    Fetch transactions for a {Network} address using Alchemy API with proper authentication
    """
    # 1. API Key Management
    api_key = get_alchemy_api_key('ALCHEMY_{NETWORK}_API_KEY')

    if not api_key:
        logger.error(f"No Alchemy API key configured for {network}")
        return []

    # 2. Endpoint Construction
    alchemy_url = ALCHEMY_ENDPOINTS['{network}'].format(api_key=api_key)
    logger.info(f"Starting {network} transaction fetch for address: {address}")

    try:
        # 3. Address Normalization
        address = normalize_address(address, network='{network}')

        # 4. Transaction Fetching (network-specific)
        transactions = fetch_{network}_specific_logic(address, alchemy_url)

        # 5. Transaction Processing
        processed_transactions = []
        for tx in transactions:
            processed_tx = process_{network}_transaction(tx, address)
            if processed_tx:
                processed_transactions.append(processed_tx)

        # 6. Sorting and Logging
        processed_transactions.sort(key=lambda x: x['timestamp'])
        logger.info(f"Successfully processed {len(processed_transactions)} {network} transactions for address {address}")

        return processed_transactions

    except Exception as e:
        logger.error(f"Critical error in fetch_{network}_transactions: {str(e)}", exc_info=True)
        return []
```

### Standard Transaction Format
All blockchain integrations should return transactions in this standardized format:
```python
{
    'transaction_hash': str,      # Unique transaction identifier
    'timestamp': datetime,        # UTC timestamp
    'transaction_type': str,      # 'buy', 'sell', 'swap', 'stake', 'unstake', 'reward', 'transfer'
    'asset_symbol': str,          # Token symbol (ETH, SOL, USDC, etc.)
    'amount': Decimal,           # Token amount (normalized for decimals)
    'price_usd': Decimal,        # USD price at time of transaction
    'value_usd': Decimal,        # Total USD value (amount * price_usd)
    'fee_usd': Decimal          # Transaction fee in USD
}
```

## Adding New Blockchain Networks

### Step 1: Add Network Configuration
```python
# In blockchain_apis.py
ALCHEMY_ENDPOINTS['new_network'] = 'https://new-network-mainnet.g.alchemy.com/v2/{api_key}'

# In .env
ALCHEMY_NEW_NETWORK_API_KEY='network_specific_key_if_needed'
```

### Step 2: Implement Network-Specific Function
```python
def fetch_new_network_transactions(address):
    """
    Fetch transactions for a New Network address using Alchemy API
    """
    # Follow the generalizable pattern above
    api_key = get_alchemy_api_key('ALCHEMY_NEW_NETWORK_API_KEY')
    # ... implement network-specific logic
```

### Step 3: Add to Router Function
```python
def fetch_multiple_chain_transactions(wallet):
    """
    Fetch transactions from multiple chains
    """
    if wallet.chain == 'new_network':
        transactions = fetch_new_network_transactions(wallet.address)
    # ... existing chains
```

### Step 4: Research Network-Specific APIs
Each network may have different Alchemy API methods:

**EVM-Compatible Networks** (Ethereum, Polygon, Arbitrum, Optimism):
- Use `alchemy_getAssetTransfers`
- Use `eth_getBlockByNumber` for timestamps
- Similar transaction structures

**Non-EVM Networks** (Solana):
- Use network-specific methods (`getSignaturesForAddress`, `getTransaction`)
- Different transaction parsing logic
- Network-specific address formats

## Error Handling

### Standard Error Handling Pattern
```python
def fetch_network_transactions(address):
    try:
        # Main logic here
        return processed_transactions

    except requests.exceptions.Timeout:
        logger.warning(f"Timeout fetching {network} transactions for {address}")
        return []

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error fetching {network} transactions: {str(e)}")
        return []

    except Exception as e:
        logger.error(f"Critical error in fetch_{network}_transactions: {str(e)}", exc_info=True)
        return mock_transactions_for_testing()  # Optional fallback
```

### API Response Validation
```python
def validate_alchemy_response(response, method_name):
    """
    Standard validation for Alchemy API responses
    """
    if response.status_code != 200:
        logger.error(f"Alchemy API error for {method_name}: {response.text}")
        return False

    data = response.json()
    if 'error' in data:
        logger.error(f"Alchemy RPC error for {method_name}: {data['error']}")
        return False

    return True
```

## Price Data Integration

### Price Fetching Strategy
All networks use the same price fetching logic through `fetch_price_data()`:

```python
def fetch_price_data(symbol, force_refresh=False):
    """
    Fetch current price data for any cryptocurrency using multiple APIs
    """
    # 1. Check cache first
    # 2. Try multiple APIs (CoinGecko, CryptoCompare, Binance)
    # 3. Use fallback prices for known tokens
    # 4. Cache results for 5 minutes
```

### Token Symbol Mapping
Each network should maintain token mappings:
```python
# Ethereum
ETH_TOKEN_MAP = {
    '0xA0b86a33E6632B173998bce86D2ccD6bcD6edf49': 'USDC',
    '0xdAC17F958D2ee523a2206206994597C13D831ec7': 'USDT',
    # ... more mappings
}

# Solana
SOL_TOKEN_MAP = {
    'So11111111111111111111111111111111111111112': 'wSOL',
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
    # ... more mappings
}
```

## Testing Strategy

### Unit Testing Template
```python
def test_fetch_network_transactions():
    """
    Test network transaction fetching
    """
    # Test with known address
    address = "known_test_address"
    transactions = fetch_network_transactions(address)

    # Validate response format
    assert isinstance(transactions, list)
    if transactions:
        tx = transactions[0]
        required_fields = ['transaction_hash', 'timestamp', 'transaction_type',
                          'asset_symbol', 'amount', 'price_usd', 'value_usd', 'fee_usd']
        for field in required_fields:
            assert field in tx
```

### Integration Testing
```python
def test_network_api_connectivity():
    """
    Test API connectivity and authentication
    """
    api_key = get_alchemy_api_key()
    url = ALCHEMY_ENDPOINTS['network'].format(api_key=api_key)

    # Test basic API call
    payload = {"jsonrpc": "2.0", "id": 1, "method": "test_method"}
    response = requests.post(url, json=payload, timeout=10)

    assert response.status_code == 200
    data = response.json()
    assert 'error' not in data or data['error']['code'] != -32600  # Auth error
```

### Manual Testing Script Template
```python
def test_network_manual():
    """
    Manual testing script for new network integration
    """
    test_addresses = [
        "active_address_1",
        "active_address_2",
        "empty_address"
    ]

    for address in test_addresses:
        print(f"Testing {network} address: {address}")
        transactions = fetch_network_transactions(address)
        print(f"Found {len(transactions)} transactions")

        if transactions:
            print("Sample transaction:")
            print(json.dumps(transactions[0], indent=2, default=str))
```

## Security Considerations

### API Key Security
1. **Never log API keys** in plain text
2. **Use environment variables** for all keys
3. **Implement key rotation** capabilities
4. **Monitor API usage** for anomalies

### Rate Limiting
1. **Implement delays** between API calls
2. **Use exponential backoff** for retries
3. **Cache responses** appropriately
4. **Monitor rate limits** per network

### Data Validation
1. **Validate all addresses** before API calls
2. **Sanitize transaction data** before processing
3. **Implement bounds checking** on amounts
4. **Verify transaction signatures** when possible

## Conclusion

This framework provides a solid foundation for integrating any blockchain network through Alchemy APIs. The key principles are:

1. **Consistent API key management**
2. **Standardized transaction format**
3. **Robust error handling**
4. **Comprehensive logging**
5. **Proper testing strategy**

By following these patterns, new blockchain networks can be integrated quickly and reliably while maintaining code quality and consistency across the entire platform.