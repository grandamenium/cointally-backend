# Alchemy Solana API Integration Guide

## AI Agent Implementation Instructions

You are implementing Alchemy Solana API integration for comprehensive crypto tax calculations and P&L tracking. Follow these precise instructions to build a robust Solana transaction parser that captures ALL transaction types required for accurate tax reporting.

### Prerequisites
- Required dependencies: `axios@^1.6.0`, `@solana/web3.js@^1.87.0` (optional for additional parsing)
- Required credentials: Alchemy API key
- Environment variables:
  - `ALCHEMY_SOLANA_API_KEY` - Your Alchemy API key
  - `ALCHEMY_SOLANA_NETWORK` - Network (mainnet-beta, devnet, testnet)
- Configuration files: None required beyond environment variables

### Authentication Setup
Alchemy uses API key authentication passed in the URL endpoint. No additional headers required.

```typescript
const ALCHEMY_BASE_URL = `https://solana-${process.env.ALCHEMY_SOLANA_NETWORK}.g.alchemy.com/v2/${process.env.ALCHEMY_SOLANA_API_KEY}`;

const alchemyClient = axios.create({
    baseURL: ALCHEMY_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
    timeout: 60000,
});
```

### Core Implementation

#### Initialization
```typescript
interface AlchemySolanaConfig {
    apiKey: string;
    network: 'mainnet-beta' | 'devnet' | 'testnet';
    maxRetries: number;
    retryDelay: number;
}

class AlchemySolanaService {
    private client: AxiosInstance;
    private config: AlchemySolanaConfig;

    constructor(config: AlchemySolanaConfig) {
        this.config = config;
        this.client = axios.create({
            baseURL: `https://solana-${config.network}.g.alchemy.com/v2/${config.apiKey}`,
            headers: { 'Content-Type': 'application/json' },
            timeout: 60000,
        });
    }
}
```

#### Primary Methods/Endpoints

##### 1. Get Transaction Signatures for Address
- Purpose: Retrieve all transaction signatures for a wallet address (essential for tax tracking)
- Parameters:
  - `address` (string): Base-58 encoded wallet address
  - `limit` (number, optional): Max signatures to return (default: 1000, max: 1000)
  - `before` (string, optional): Start searching backwards from this transaction signature
  - `until` (string, optional): Search until this transaction signature
- Response format: Array of signature objects with signature, slot, err, memo, blockTime, confirmationStatus
- Example usage:
```typescript
async getSignaturesForAddress(
    address: string,
    options: {
        limit?: number;
        before?: string;
        until?: string;
        commitment?: 'processed' | 'confirmed' | 'finalized';
    } = {}
): Promise<TransactionSignature[]> {
    try {
        const response = await this.client.post('/', {
            jsonrpc: '2.0',
            id: 1,
            method: 'getSignaturesForAddress',
            params: [
                address,
                {
                    limit: options.limit || 1000,
                    before: options.before,
                    until: options.until,
                    commitment: options.commitment || 'finalized'
                }
            ]
        });

        return response.data.result;
    } catch (error) {
        console.error('Error fetching signatures:', error);
        throw error;
    }
}
```

##### 2. Get Parsed Transaction Details
- Purpose: Retrieve full transaction details with automatic SPL token parsing
- Parameters:
  - `signature` (string): Transaction signature
  - `encoding` (string): Use 'jsonParsed' for automatic SPL token parsing
  - `maxSupportedTransactionVersion` (number): Set to 0 for versioned transactions
- Response format: Detailed transaction object with parsed instructions, account changes, fees
- Example usage:
```typescript
async getParsedTransaction(signature: string): Promise<ParsedTransaction> {
    try {
        const response = await this.client.post('/', {
            jsonrpc: '2.0',
            id: 1,
            method: 'getTransaction',
            params: [
                signature,
                {
                    encoding: 'jsonParsed',
                    maxSupportedTransactionVersion: 0,
                    commitment: 'finalized'
                }
            ]
        });

        return response.data.result;
    } catch (error) {
        console.error('Error fetching transaction:', error);
        throw error;
    }
}
```

##### 3. Get Token Balances (Enhanced API)
- Purpose: Retrieve all SPL token balances for tax basis calculations
- Parameters:
  - `address` (string): Wallet address
  - `pageKey` (string, optional): For pagination
- Response format: Array of token balances with mint addresses, amounts, decimals
- Example usage:
```typescript
async getTokenBalances(
    address: string,
    pageKey?: string
): Promise<TokenBalanceResponse> {
    try {
        const response = await this.client.post('/', {
            jsonrpc: '2.0',
            id: 1,
            method: 'getTokenAccountsByOwner',
            params: [
                address,
                { programId: 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' },
                { encoding: 'jsonParsed' }
            ]
        });

        return response.data.result;
    } catch (error) {
        console.error('Error fetching token balances:', error);
        throw error;
    }
}
```

##### 4. Get Assets by Owner (DAS API)
- Purpose: Comprehensive asset retrieval including NFTs and compressed assets for tax reporting
- Parameters:
  - `ownerAddress` (string): Wallet address
  - `page` (number): Pagination
  - `limit` (number): Items per page
  - `displayOptions` (object): Metadata display preferences
- Response format: Complete asset list with metadata, ownership, and value data
- Example usage:
```typescript
async getAssetsByOwner(
    ownerAddress: string,
    options: {
        page?: number;
        limit?: number;
        before?: string;
        after?: string;
        sortBy?: 'created' | 'updated';
        sortDirection?: 'asc' | 'desc';
    } = {}
): Promise<AssetResponse> {
    try {
        const response = await this.client.post('/', {
            jsonrpc: '2.0',
            id: 1,
            method: 'getAssetsByOwner',
            params: {
                ownerAddress,
                page: options.page || 1,
                limit: options.limit || 1000,
                displayOptions: {
                    showFungible: true,
                    showNativeBalance: true,
                    showInscriptions: false,
                    showCollectionMetadata: true,
                    showUnverifiedCollections: true
                },
                ...options
            }
        });

        return response.data.result;
    } catch (error) {
        console.error('Error fetching assets:', error);
        throw error;
    }
}
```

##### 5. Batch Transaction Processing for Tax Calculations
- Purpose: Process multiple transactions efficiently for comprehensive tax analysis
- Parameters: Multiple transaction signatures
- Response format: Array of parsed transactions
- Example usage:
```typescript
async batchGetParsedTransactions(
    signatures: string[],
    batchSize: number = 100
): Promise<ParsedTransaction[]> {
    const results: ParsedTransaction[] = [];

    for (let i = 0; i < signatures.length; i += batchSize) {
        const batch = signatures.slice(i, i + batchSize);

        try {
            const batchPromises = batch.map(signature =>
                this.getParsedTransaction(signature)
            );

            const batchResults = await Promise.allSettled(batchPromises);

            batchResults.forEach((result, index) => {
                if (result.status === 'fulfilled' && result.value) {
                    results.push(result.value);
                } else {
                    console.error(`Failed to fetch transaction ${batch[index]}:`, result);
                }
            });

            // Rate limiting delay
            await new Promise(resolve => setTimeout(resolve, 1000));

        } catch (error) {
            console.error(`Error processing batch starting at index ${i}:`, error);
        }
    }

    return results;
}
```

### Transaction Type Parsing for Tax Calculations

#### Parse Transaction Types
```typescript
interface TaxTransaction {
    signature: string;
    blockTime: number;
    type: 'transfer' | 'swap' | 'stake' | 'unstake' | 'nft_trade' | 'defi' | 'unknown';
    from?: string;
    to?: string;
    amount?: number;
    token?: string;
    fee: number;
    rawTransaction: any;
}

parseTaxTransaction(transaction: ParsedTransaction): TaxTransaction {
    const baseTransaction: TaxTransaction = {
        signature: transaction.transaction.signatures[0],
        blockTime: transaction.blockTime || 0,
        type: 'unknown',
        fee: transaction.meta?.fee || 0,
        rawTransaction: transaction
    };

    // Parse different instruction types
    const instructions = transaction.transaction.message.instructions;

    for (const instruction of instructions) {
        if (instruction.program === 'spl-token') {
            // SPL Token transfer
            const parsed = instruction.parsed;
            if (parsed?.type === 'transfer') {
                baseTransaction.type = 'transfer';
                baseTransaction.from = parsed.info.source;
                baseTransaction.to = parsed.info.destination;
                baseTransaction.amount = parseFloat(parsed.info.amount);
                baseTransaction.token = parsed.info.mint;
            }
        } else if (instruction.program === 'system') {
            // Native SOL transfer
            const parsed = instruction.parsed;
            if (parsed?.type === 'transfer') {
                baseTransaction.type = 'transfer';
                baseTransaction.from = parsed.info.source;
                baseTransaction.to = parsed.info.destination;
                baseTransaction.amount = parsed.info.lamports / 1e9; // Convert to SOL
                baseTransaction.token = 'SOL';
            }
        }
        // Add more program parsing for Jupiter, Raydium, etc.
    }

    return baseTransaction;
}
```

### Error Handling
Common error codes and handling strategies:

```typescript
interface AlchemyError {
    code: number;
    message: string;
    data?: any;
}

async handleApiCall<T>(apiCall: () => Promise<T>): Promise<T> {
    let retries = 0;

    while (retries < this.config.maxRetries) {
        try {
            return await apiCall();
        } catch (error: any) {
            const alchemyError = error.response?.data?.error as AlchemyError;

            if (alchemyError) {
                switch (alchemyError.code) {
                    case -32005: // Node is behind
                        console.warn('Node is behind, retrying...');
                        break;
                    case -32004: // Transaction not found
                        console.warn('Transaction not found:', alchemyError.message);
                        throw error; // Don't retry
                    case 429: // Rate limit
                        const delay = Math.pow(2, retries) * 1000; // Exponential backoff
                        await new Promise(resolve => setTimeout(resolve, delay));
                        break;
                    default:
                        console.error('Alchemy API error:', alchemyError);
                        throw error;
                }
            }

            retries++;
            if (retries >= this.config.maxRetries) {
                throw error;
            }

            await new Promise(resolve =>
                setTimeout(resolve, this.config.retryDelay * retries)
            );
        }
    }

    throw new Error('Max retries exceeded');
}
```

### Rate Limiting & Best Practices
- Rate limits:
  - Growth plan: ~16 million CUs per month (≈100 requests/10 seconds for standard calls)
  - Enterprise: Custom limits based on plan
- Retry strategy: Exponential backoff starting at 1 second, max 3 retries
- Caching recommendations:
  - Cache transaction data for 24 hours (immutable once confirmed)
  - Cache token metadata for 1 hour
  - Cache price data for 5 minutes

```typescript
// Implement caching for frequently accessed data
const transactionCache = new Map<string, ParsedTransaction>();
const TOKEN_METADATA_CACHE_TTL = 3600000; // 1 hour
const TRANSACTION_CACHE_TTL = 86400000; // 24 hours

async getCachedTransaction(signature: string): Promise<ParsedTransaction> {
    const cached = transactionCache.get(signature);
    if (cached) return cached;

    const transaction = await this.getParsedTransaction(signature);
    transactionCache.set(signature, transaction);

    // Clear cache after TTL
    setTimeout(() => {
        transactionCache.delete(signature);
    }, TRANSACTION_CACHE_TTL);

    return transaction;
}
```

### Historical Price Data Integration
Integrate with price oracle services for accurate tax calculations:

```typescript
// Integration with CoinGecko for historical prices
async getHistoricalPrice(
    tokenMint: string,
    timestamp: number
): Promise<number> {
    try {
        const date = new Date(timestamp * 1000).toISOString().split('T')[0];

        // First try to get Solana token price from CoinGecko
        const response = await axios.get(
            `https://api.coingecko.com/api/v3/coins/solana/history`,
            {
                params: {
                    date: date,
                    localization: false
                }
            }
        );

        return response.data.market_data.current_price.usd;
    } catch (error) {
        console.error('Error fetching historical price:', error);
        // Fallback to Pyth or other oracle
        return this.getPythHistoricalPrice(tokenMint, timestamp);
    }
}

// Integration with Pyth Network for on-chain price data
async getPythHistoricalPrice(
    tokenMint: string,
    timestamp: number
): Promise<number> {
    // Implementation for Pyth historical price fetching
    // Note: Pyth provides real-time data, historical may be limited
    // Consider using Jupiter API or other DEX aggregators for historical data
    return 0; // Placeholder
}
```

### Comprehensive Transaction Fetching for Tax Purposes
```typescript
async getAllTransactionsForTaxes(
    address: string,
    startDate?: Date,
    endDate?: Date
): Promise<TaxTransaction[]> {
    const allTransactions: TaxTransaction[] = [];
    let before: string | undefined;

    try {
        while (true) {
            const signatures = await this.getSignaturesForAddress(address, {
                limit: 1000,
                before: before
            });

            if (signatures.length === 0) break;

            // Filter by date range if provided
            const filteredSignatures = signatures.filter(sig => {
                if (!sig.blockTime) return true;
                const txDate = new Date(sig.blockTime * 1000);

                if (startDate && txDate < startDate) return false;
                if (endDate && txDate > endDate) return false;

                return true;
            });

            // If we've gone past the start date, stop fetching
            if (startDate && signatures.length > 0) {
                const oldestTx = signatures[signatures.length - 1];
                if (oldestTx.blockTime && new Date(oldestTx.blockTime * 1000) < startDate) {
                    break;
                }
            }

            // Batch process transactions
            const transactions = await this.batchGetParsedTransactions(
                filteredSignatures.map(sig => sig.signature)
            );

            const taxTransactions = transactions
                .filter(tx => tx !== null)
                .map(tx => this.parseTaxTransaction(tx));

            allTransactions.push(...taxTransactions);

            // Update before pointer for pagination
            before = signatures[signatures.length - 1]?.signature;

            // Rate limiting
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    } catch (error) {
        console.error('Error fetching all transactions:', error);
        throw error;
    }

    return allTransactions;
}
```

### Testing Checklist
- [ ] Authentication successful with API key
- [ ] Basic transaction fetching works for known addresses
- [ ] SPL token transfers parsed correctly
- [ ] Native SOL transfers parsed correctly
- [ ] NFT transactions identified and parsed
- [ ] DeFi protocol interactions captured
- [ ] Staking/unstaking transactions detected
- [ ] Error handling catches rate limits and retries appropriately
- [ ] Pagination works for addresses with many transactions
- [ ] Historical price integration functional
- [ ] Fee calculations accurate for tax purposes

### Common Pitfalls to Avoid
1. **Rate Limiting**: Don't exceed 100 requests per 10 seconds without proper delays
2. **Transaction Parsing**: Always use 'jsonParsed' encoding for automatic SPL token parsing
3. **Pagination**: Implement proper pagination using 'before' parameter to get all transactions
4. **Failed Transactions**: Include failed transactions in tax calculations for fee tracking
5. **Versioned Transactions**: Set maxSupportedTransactionVersion: 0 for modern transactions
6. **Timestamp Handling**: Solana blockTime is in seconds, not milliseconds
7. **Token Decimals**: Always account for token decimals when calculating amounts
8. **Compressed NFTs**: Use DAS API for compressed NFT detection
9. **Program-Specific Parsing**: Different DeFi protocols require custom instruction parsing
10. **Historical Data Limitations**: Alchemy doesn't store full historical data indefinitely

### Advanced DeFi Protocol Parsing
```typescript
// Enhanced parsing for major Solana DeFi protocols
parseDefiTransaction(transaction: ParsedTransaction): TaxTransaction | null {
    const instructions = transaction.transaction.message.instructions;

    for (const instruction of instructions) {
        const programId = instruction.programId;

        // Jupiter aggregator swaps
        if (programId === 'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4') {
            return this.parseJupiterSwap(instruction, transaction);
        }

        // Raydium AMM
        if (programId === 'RVKd61ztZW9GUwhRbbLoYVRE5Xf1B2tVscKqwZqXgEr') {
            return this.parseRaydiumSwap(instruction, transaction);
        }

        // Orca AMM
        if (programId === 'DjVE6JNiYqPL2QXyCUUh8rNjHrbz9hXHNYt99MQ59qw1') {
            return this.parseOrcaSwap(instruction, transaction);
        }

        // Marinade staking
        if (programId === '8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC') {
            return this.parseMarinadeStaking(instruction, transaction);
        }
    }

    return null;
}
```

### Reference Links
- Official documentation: https://docs.alchemy.com/reference/solana-api-quickstart
- API reference: https://docs.alchemy.com/reference/solana-api-endpoints
- DAS API documentation: https://www.alchemy.com/docs/reference/alchemy-das-apis-for-solana
- SDK repository: https://github.com/alchemyplatform/alchemy-sdk-js
- Solana RPC specification: https://solana.com/docs/rpc
- Rate limiting documentation: https://docs.alchemy.com/reference/throughput
- Enhanced APIs: https://www.alchemy.com/enhanced-apis