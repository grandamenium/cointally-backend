# Regional API Configuration Guide

This guide explains how to configure the crypto tax application to use the appropriate regional API endpoints for optimal performance and compliance.

## Overview

The application supports regional API endpoints for better performance, compliance with local regulations, and improved reliability. You can configure these via environment variables.

## Binance Configuration

### Environment Variables

- `BINANCE_REGION`: Specifies which Binance region to use
  - `GLOBAL` (default): Global Binance (https://api.binance.com)
  - `US`: Binance.US (https://api.binance.us)
  - `JP`: Binance Japan (https://api.binance.co.jp)
  - `TR`: Binance Turkey (https://api.binance.tr)

### Example Configuration

```bash
# For US users
export BINANCE_REGION=US

# For Japanese users
export BINANCE_REGION=JP

# For Turkish users
export BINANCE_REGION=TR

# For global users (default)
export BINANCE_REGION=GLOBAL
```

### API Endpoints Used

| Region | Spot API | Futures API |
|--------|----------|-------------|
| GLOBAL | https://api.binance.com | https://fapi.binance.com |
| US | https://api.binance.us | https://fapi.binance.us |
| JP | https://api.binance.co.jp | https://fapi.binance.co.jp |
| TR | https://api.binance.tr | https://fapi.binance.tr |

## Coinbase Configuration

### Environment Variables

- `COINBASE_REGION`: Specifies the regional compliance
  - `US` (default): United States
  - `EU`: Europe
  - `UK`: United Kingdom
  - `CA`: Canada
  - `SG`: Singapore

- `COINBASE_PRODUCT`: Specifies which Coinbase product to use
  - `RETAIL` (default): Retail Coinbase
  - `PRO` or `ADVANCED`: Coinbase Advanced Trade

### Example Configuration

```bash
# For US retail users
export COINBASE_REGION=US
export COINBASE_PRODUCT=RETAIL

# For European Advanced Trade users
export COINBASE_REGION=EU
export COINBASE_PRODUCT=ADVANCED

# For UK users
export COINBASE_REGION=UK
export COINBASE_PRODUCT=RETAIL

# For Canadian users
export COINBASE_REGION=CA
export COINBASE_PRODUCT=RETAIL

# For Singapore users
export COINBASE_REGION=SG
export COINBASE_PRODUCT=RETAIL
```

### API Endpoints Used

| Product | v2 API | v3 API |
|---------|--------|--------|
| All Regions | https://api.coinbase.com/v2 | https://api.coinbase.com/api/v3 |

*Note: Coinbase uses the same API endpoints globally but applies regional compliance rules based on the region setting.*

## Bybit Configuration

### Environment Variables

- `BYBIT_REGION`: Specifies which Bybit region to use
  - `GLOBAL` (default): Global Bybit (https://api.bybit.com)
  - `ASIA`: Asia-Pacific optimized routing
  - `EU`: Europe optimized routing
  - `US`: US optimized routing
- `BYBIT_TESTNET`: Set to `true` for testnet environment

### Example Configuration

```bash
# For European users
export BYBIT_REGION=EU

# For testing
export BYBIT_TESTNET=true
```

### API Endpoints Used

| Environment | Endpoint |
|-------------|----------|
| Production | https://api.bybit.com |
| Testnet | https://api-testnet.bybit.com |

*Note: Production endpoint is the same but routing is optimized based on region.*

## Kraken Configuration

### Environment Variables

- `KRAKEN_REGION`: Specifies which Kraken region to use
  - `GLOBAL` (default): Global Kraken (https://api.kraken.com)
  - `US`: US-optimized routing
  - `EU`: Europe-optimized routing
  - `ASIA`: Asia-Pacific-optimized routing
- `KRAKEN_TESTNET`: Set to `true` for demo/testing environment

### Example Configuration

```bash
# For US users
export KRAKEN_REGION=US

# For European users
export KRAKEN_REGION=EU

# For Asia-Pacific users
export KRAKEN_REGION=ASIA

# For demo/testing
export KRAKEN_TESTNET=true
```

## Hyperliquid Configuration

Hyperliquid is a decentralized perpetual futures exchange built on its own L1 blockchain. While it uses a global endpoint, you can configure regional optimization for better performance.

### Environment Variables

Set these environment variables for Hyperliquid configuration:

```bash
# Region Configuration (Optional - for optimization)
export HYPERLIQUID_REGION="GLOBAL"  # Options: GLOBAL, US, EU, ASIA

# Network Configuration
export HYPERLIQUID_TESTNET="false"  # Set to "true" for testnet

# Authentication (Required)
export HYPERLIQUID_PRIVATE_KEY="your_private_key_here"
export HYPERLIQUID_WALLET_ADDRESS="0x..."
```

### Regional Settings

#### Global (Default)
```bash
export HYPERLIQUID_REGION="GLOBAL"
```
- **Mainnet API**: `https://api.hyperliquid.xyz`
- **Testnet API**: `https://api.hyperliquid-testnet.xyz`
- **Best for**: Universal access, all regions

#### US Optimized
```bash
export HYPERLIQUID_REGION="US"
```
- **Mainnet API**: `https://api.hyperliquid.xyz` (same endpoint, regionally optimized routing)
- **Best for**: United States users
- **Features**: Optimized CDN routing for US-based users

#### Europe Optimized
```bash
export HYPERLIQUID_REGION="EU"
```
- **Mainnet API**: `https://api.hyperliquid.xyz` (same endpoint, regionally optimized routing)
- **Best for**: European users
- **Features**: Optimized CDN routing for European users

#### Asia Optimized
```bash
export HYPERLIQUID_REGION="ASIA"
```
- **Mainnet API**: `https://api.hyperliquid.xyz` (same endpoint, regionally optimized routing)
- **Best for**: Asian users
- **Features**: Optimized CDN routing for Asian users

### Authentication Setup

Hyperliquid uses wallet-based authentication with private key signing:

1. **Create or Import Wallet**
   - Generate a new wallet or use existing private key
   - Ensure wallet has appropriate permissions

2. **Set Private Key**
   ```bash
   export HYPERLIQUID_PRIVATE_KEY="your_64_character_private_key"
   ```

3. **Set Wallet Address**
   ```bash
   export HYPERLIQUID_WALLET_ADDRESS="0x1234567890123456789012345678901234567890"
   ```

### API Features

#### Available Endpoints
- **Info Endpoint**: `/info` - Market data, user information
- **Exchange Endpoint**: `/exchange` - Trading operations (requires authentication)

#### Supported Operations
- User fills and trade history
- Position management
- Account balances (spot and perpetual)
- Funding payment history
- Transfer operations (deposits/withdrawals via bridge)

### Network Configuration

#### Mainnet
```bash
export HYPERLIQUID_TESTNET="false"
```
- Full production environment
- Real money trading
- Complete API access

#### Testnet
```bash
export HYPERLIQUID_TESTNET="true"
```
- Testing environment
- Testnet tokens only
- Same API structure as mainnet

### Example Configuration Files

#### Development Environment (.env.development)
```bash
# Hyperliquid Development Configuration
HYPERLIQUID_REGION=GLOBAL
HYPERLIQUID_TESTNET=true
HYPERLIQUID_PRIVATE_KEY=your_testnet_private_key
HYPERLIQUID_WALLET_ADDRESS=0x_your_testnet_address
```

#### Production Environment (.env.production)
```bash
# Hyperliquid Production Configuration
HYPERLIQUID_REGION=US  # or EU, ASIA based on your location
HYPERLIQUID_TESTNET=false
HYPERLIQUID_PRIVATE_KEY=your_mainnet_private_key
HYPERLIQUID_WALLET_ADDRESS=0x_your_mainnet_address
```

### Security Considerations

1. **Private Key Security**
   - Store private keys securely (use environment variables or secure key management)
   - Never commit private keys to version control
   - Use different keys for testing and production

2. **Network Security**
   - Ensure HTTPS connections
   - Verify SSL certificates
   - Use secure networks for API calls

3. **Access Control**
   - Limit API access to necessary operations only
   - Monitor account activity regularly
   - Use subaccounts for different strategies if needed

### Integration Notes

1. **Unique Features**
   - Decentralized exchange (no traditional API keys)
   - Uses EIP-712 signing for authentication
   - Spot assets use @ prefix notation (e.g., @0, @107)
   - Built-in bridge for deposits/withdrawals

2. **Rate Limiting**
   - Hyperliquid has built-in rate limiting
   - Adjust request frequency based on network conditions
   - Use appropriate delays between requests

3. **Asset Handling**
   - Perpetual assets: Regular symbol names (BTC, ETH, SOL)
   - Spot assets: Index notation (@0, @1, @107, etc.)
   - Asset mapping may be required for proper display

### Troubleshooting

#### Common Issues

1. **Authentication Failures**
   ```
   Error: Invalid signature
   Solution: Verify private key format and signing implementation
   ```

2. **Network Timeouts**
   ```
   Error: Request timeout
   Solution: Check network connectivity and try different region
   ```

3. **Asset Not Found**
   ```
   Error: Unknown asset symbol
   Solution: Verify asset mapping for spot vs perpetual assets
   ```

#### Debug Steps

1. **Verify Configuration**
   ```bash
   echo $HYPERLIQUID_REGION
   echo $HYPERLIQUID_TESTNET
   # Do NOT echo private keys in production
   ```

2. **Test Connection**
   ```bash
   python test_hyperliquid_integration.py
   ```

3. **Check Logs**
   - Monitor application logs for API responses
   - Check for rate limiting messages
   - Verify successful authentication

### Support Resources

- **Hyperliquid Documentation**: https://hyperliquid.gitbook.io/hyperliquid-docs
- **Python SDK**: https://github.com/hyperliquid-dex/hyperliquid-python-sdk
- **Discord Community**: Official Hyperliquid Discord
- **API Status**: Check Hyperliquid status page for service updates

## Configuration Examples

### Docker Environment File (.env)

```bash
# Binance Configuration
BINANCE_REGION=US

# Coinbase Configuration
COINBASE_REGION=US
COINBASE_PRODUCT=ADVANCED

# Bybit Configuration
BYBIT_REGION=US
BYBIT_TESTNET=false
```

### Docker Compose Configuration

```yaml
version: '3.8'
services:
  crypto-tax-backend:
    environment:
      - BINANCE_REGION=US
      - COINBASE_REGION=US
      - COINBASE_PRODUCT=ADVANCED
      - BYBIT_REGION=US
      - BYBIT_TESTNET=false
```

### Systemd Service Configuration

```ini
[Unit]
Description=Crypto Tax API
After=network.target

[Service]
Type=simple
User=crypto-tax
WorkingDirectory=/opt/crypto-tax-app
Environment=BINANCE_REGION=US
Environment=COINBASE_REGION=US
Environment=COINBASE_PRODUCT=ADVANCED
Environment=BYBIT_REGION=US
Environment=BYBIT_TESTNET=false
ExecStart=/opt/crypto-tax-app/venv/bin/python manage.py runserver
Restart=always

[Install]
WantedBy=multi-user.target
```

## Regional Recommendations

### United States
```bash
export BINANCE_REGION=US
export COINBASE_REGION=US
export BYBIT_REGION=US
```

### Europe
```bash
export BINANCE_REGION=GLOBAL
export COINBASE_REGION=EU
export BYBIT_REGION=EU
```

### Asia-Pacific
```bash
export BINANCE_REGION=GLOBAL
export COINBASE_REGION=SG
export BYBIT_REGION=ASIA
```

### Japan
```bash
export BINANCE_REGION=JP
export COINBASE_REGION=US
export BYBIT_REGION=ASIA
```

### Canada
```bash
export BINANCE_REGION=GLOBAL
export COINBASE_REGION=CA
export BYBIT_REGION=US
```

### United Kingdom
```bash
export BINANCE_REGION=GLOBAL
export COINBASE_REGION=UK
export BYBIT_REGION=EU
```

## Performance Optimization Tips

1. **Choose the closest region** to your geographic location for better latency
2. **Use testnet** during development to avoid rate limits on production APIs
3. **Monitor API response times** and switch regions if performance degrades
4. **Check regulatory compliance** requirements for your jurisdiction

## Troubleshooting

### Common Issues

1. **API Key Mismatch**: Ensure your API keys are created for the correct region
2. **Rate Limiting**: Different regions may have different rate limits
3. **Feature Availability**: Some features may not be available in all regions
4. **Time Zone Issues**: Ensure your system time is correctly configured

### Error Messages

- `Invalid API endpoint`: Check that your region configuration is correct
- `Access denied`: Verify your API keys are valid for the selected region
- `Rate limit exceeded`: Consider switching to a less congested region

### Debug Logging

Enable debug logging to see which endpoints are being used:

```python
import logging
logging.getLogger('crypto_tax_api.services.exchange_services').setLevel(logging.DEBUG)
```

## Security Considerations

1. **Never commit** environment variables containing API keys to version control
2. **Use different API keys** for different environments (dev, staging, prod)
3. **Regularly rotate** API keys for security
4. **Monitor API usage** for unusual activity
5. **Implement proper secrets management** in production

## Support

If you encounter issues with regional configuration:

1. Check the application logs for detailed error messages
2. Verify your API keys are valid for the selected region
3. Test with a simple connection test first
4. Contact the exchange support if API access issues persist

## Updates

This configuration guide is updated regularly. Check for the latest version when:
- New exchanges are added
- New regions become available
- API endpoints change
- Regulatory requirements change 