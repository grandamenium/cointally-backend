import logging
import requests
import base64
import json
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, parse_qs
from django.conf import settings
from crypto_tax_api.models import ExchangeCredential

logger = logging.getLogger(__name__)


class CoinbaseOAuthService:
    """Service for handling Coinbase OAuth authentication"""
    
    def __init__(self):
        # OAuth endpoints (Updated to current Coinbase OAuth2 endpoints)
        self.auth_url = "https://login.coinbase.com/oauth2/auth"
        self.token_url = "https://login.coinbase.com/oauth2/token"
        self.revoke_url = "https://login.coinbase.com/oauth2/revoke"
        
        # API endpoints
        self.api_base_url = "https://api.coinbase.com/v2"
        
        # OAuth credentials (should be set in Django settings)
        self.client_id = getattr(settings, 'COINBASE_CLIENT_ID', None)
        self.client_secret = getattr(settings, 'COINBASE_CLIENT_SECRET', None)
        self.redirect_uri = getattr(settings, 'COINBASE_REDIRECT_URI', None)
        
        if not all([self.client_id, self.client_secret, self.redirect_uri]):
            raise ValueError("Coinbase OAuth credentials not properly configured in settings")

    def get_authorization_url(self, state=None, scope=None):
        """
        Generate the authorization URL for OAuth flow
        
        Args:
            state: Optional state parameter for CSRF protection
            scope: Permissions to request (default: wallet:accounts:read,wallet:transactions:read)
        
        Returns:
            Authorization URL string
        """
        if scope is None:
            # Include offline_access for refresh token capability
            scope = "wallet:accounts:read,wallet:transactions:read,wallet:buys:read,wallet:sells:read,wallet:deposits:read,wallet:withdrawals:read,offline_access"
        
        params = {
            'response_type': 'code',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'scope': scope,
        }
        
        if state:
            params['state'] = state
        
        query_string = urlencode(params)
        return f"{self.auth_url}?{query_string}"

    def exchange_code_for_token(self, authorization_code):
        """
        Exchange authorization code for access token
        
        Args:
            authorization_code: Code received from OAuth callback
        
        Returns:
            dict: Token response containing access_token, refresh_token, etc.
        """
        try:
            # Prepare request data
            data = {
                'grant_type': 'authorization_code',
                'code': authorization_code,
                'redirect_uri': self.redirect_uri,
            }
            
            # Create Basic Auth header
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            # Make token request
            response = requests.post(
                self.token_url,
                data=data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                raise Exception(f"Token exchange failed: {response.text}")
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during token exchange: {str(e)}")
            raise Exception(f"Network error during token exchange: {str(e)}")

    def refresh_access_token(self, refresh_token):
        """
        Refresh an expired access token
        
        Args:
            refresh_token: The refresh token
        
        Returns:
            dict: New token response
        """
        try:
            data = {
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
            }
            
            # Create Basic Auth header
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            response = requests.post(
                self.token_url,
                data=data,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.status_code} - {response.text}")
                raise Exception(f"Token refresh failed: {response.text}")
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during token refresh: {str(e)}")
            raise Exception(f"Network error during token refresh: {str(e)}")

    def revoke_token(self, access_token):
        """
        Revoke an access token
        
        Args:
            access_token: The access token to revoke
        """
        try:
            data = {
                'token': access_token,
            }
            
            # Create Basic Auth header
            credentials = f"{self.client_id}:{self.client_secret}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            headers = {
                'Authorization': f'Basic {encoded_credentials}',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            
            response = requests.post(
                self.revoke_url,
                data=data,
                headers=headers,
                timeout=30
            )
            
            return response.status_code == 200
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error revoking token: {str(e)}")
            return False

    def make_authenticated_request(self, access_token, method, endpoint, params=None, data=None):
        """
        Make an authenticated request to Coinbase API using OAuth token
        
        Args:
            access_token: OAuth access token
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., '/accounts')
            params: Query parameters
            data: Request body data
        
        Returns:
            Response JSON data
        """
        try:
            url = f"{self.api_base_url}{endpoint}"
            
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json',
            }
            
            # Make request
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                timeout=30
            )
            
            if response.status_code == 401:
                # Token might be expired
                raise Exception("Access token expired or invalid")
            elif response.status_code not in [200, 201]:
                logger.error(f"Coinbase API error {response.status_code}: {response.text}")
                raise Exception(f"Coinbase API error: {response.text}")
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            raise Exception(f"Request failed: {str(e)}")

    def test_connection(self, access_token):
        """
        Test the OAuth connection by fetching user info
        
        Args:
            access_token: OAuth access token
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            user_data = self.make_authenticated_request(access_token, 'GET', '/user')
            
            if user_data and 'data' in user_data:
                user_info = user_data['data']
                username = user_info.get('username', user_info.get('name', 'Unknown'))
                return True, f"Connected successfully as {username}"
            else:
                return False, "Failed to retrieve user information"
                
        except Exception as e:
            return False, str(e)

    def get_accounts(self, access_token):
        """
        Get user's Coinbase accounts
        
        Args:
            access_token: OAuth access token
        
        Returns:
            list: Account data
        """
        try:
            response = self.make_authenticated_request(access_token, 'GET', '/accounts')
            return response.get('data', [])
        except Exception as e:
            logger.error(f"Error fetching accounts: {str(e)}")
            raise

    def get_account_transactions(self, access_token, account_id, params=None):
        """
        Get transactions for a specific account
        
        Args:
            access_token: OAuth access token
            account_id: Coinbase account ID
            params: Additional query parameters
        
        Returns:
            list: Transaction data
        """
        try:
            endpoint = f"/accounts/{account_id}/transactions"
            response = self.make_authenticated_request(access_token, 'GET', endpoint, params=params)
            return response.get('data', [])
        except Exception as e:
            logger.error(f"Error fetching transactions for account {account_id}: {str(e)}")
            raise

    def store_oauth_credentials(self, user, token_data):
        """
        Store OAuth credentials for a user
        
        Args:
            user: Django user instance
            token_data: Token response from OAuth flow
        
        Returns:
            ExchangeCredential instance
        """
        # Calculate expiry time
        expires_in = token_data.get('expires_in', 7200)  # Default 2 hours
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        # Prepare credential data
        credential_data = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token'),
            'token_type': token_data.get('token_type', 'Bearer'),
            'expires_at': expires_at.isoformat(),
            'scope': token_data.get('scope'),
        }
        
        # Store as encrypted JSON in the api_key field (reusing existing structure)
        from cryptography.fernet import Fernet
        import time
        
        encryption_key = settings.ENCRYPTION_KEY
        fernet = Fernet(encryption_key)
        timestamp = str(int(time.time()))
        
        encrypted_data = fernet.encrypt(
            f"{timestamp}:{json.dumps(credential_data)}".encode()
        ).decode()
        
        # Create or update exchange credential
        credential, created = ExchangeCredential.objects.update_or_create(
            user=user,
            exchange='coinbase',
            defaults={
                'api_key': encrypted_data,  # Store OAuth tokens here
                'api_secret': 'oauth',  # Marker to indicate OAuth
                'api_passphrase': None,
                'is_active': True,
                'platform_type': 'cex',
            }
        )
        
        return credential

    def get_oauth_credentials(self, user):
        """
        Retrieve and decrypt OAuth credentials for a user
        
        Args:
            user: Django user instance
        
        Returns:
            dict: Decrypted OAuth credential data
        """
        try:
            credential = ExchangeCredential.objects.get(user=user, exchange='coinbase')
            
            # Check if this is an OAuth credential
            if credential.api_secret != 'oauth':
                raise ValueError("This is not an OAuth credential")
            
            # Decrypt the token data
            from cryptography.fernet import Fernet
            
            encryption_key = settings.ENCRYPTION_KEY
            fernet = Fernet(encryption_key)
            
            # Decrypt and parse the data
            decrypted = fernet.decrypt(credential.api_key.encode()).decode()
            
            # Split timestamp and data
            if ':' in decrypted:
                timestamp, json_data = decrypted.split(':', 1)
                credential_data = json.loads(json_data)
            else:
                # Legacy format without timestamp
                credential_data = json.loads(decrypted)
            
            return credential_data
            
        except ExchangeCredential.DoesNotExist:
            raise ValueError("No Coinbase OAuth credentials found for this user")
        except Exception as e:
            logger.error(f"Error retrieving OAuth credentials: {str(e)}")
            raise ValueError(f"Error retrieving OAuth credentials: {str(e)}")

    def is_token_expired(self, credential_data):
        """
        Check if the access token is expired
        
        Args:
            credential_data: Decrypted credential data
        
        Returns:
            bool: True if token is expired
        """
        expires_at_str = credential_data.get('expires_at')
        if not expires_at_str:
            return True  # Assume expired if no expiry data
        
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            # Add 5 minute buffer
            return datetime.now(timezone.utc) >= (expires_at - timedelta(minutes=5))
        except Exception:
            return True  # Assume expired if can't parse

    def ensure_valid_token(self, user):
        """
        Ensure the user has a valid access token, refreshing if necessary
        
        Args:
            user: Django user instance
        
        Returns:
            str: Valid access token
        """
        credential_data = self.get_oauth_credentials(user)
        
        if not self.is_token_expired(credential_data):
            return credential_data['access_token']
        
        # Token is expired, try to refresh
        refresh_token = credential_data.get('refresh_token')
        if not refresh_token:
            raise Exception("No refresh token available, user needs to re-authorize")
        
        try:
            # Refresh the token
            new_token_data = self.refresh_access_token(refresh_token)
            
            # Store the new token data
            self.store_oauth_credentials(user, new_token_data)
            
            return new_token_data['access_token']
            
        except Exception as e:
            logger.error(f"Failed to refresh token: {str(e)}")
            raise Exception("Token refresh failed, user needs to re-authorize")

    def get_all_accounts_with_pagination(self, access_token):
        """
        Get all user accounts with pagination support

        Returns:
            list: All account data
        """
        all_accounts = []
        starting_after = None

        while True:
            try:
                params = {'limit': 100}
                if starting_after:
                    params['starting_after'] = starting_after

                response = self.make_authenticated_request(access_token, 'GET', '/accounts', params=params)

                accounts = response.get('data', [])
                if not accounts:
                    break

                all_accounts.extend(accounts)

                # Check pagination
                pagination = response.get('pagination', {})
                if not pagination.get('next_uri'):
                    break

                # Extract starting_after from next_uri
                next_uri = pagination['next_uri']
                if 'starting_after=' in next_uri:
                    starting_after = next_uri.split('starting_after=')[1].split('&')[0]
                else:
                    break

            except Exception as e:
                logger.error(f"Error fetching accounts: {str(e)}")
                break

        return all_accounts

    def get_all_account_transactions_with_pagination(self, access_token, account_id):
        """
        Get all transactions for an account with pagination support

        Args:
            access_token: OAuth access token
            account_id: Coinbase account ID

        Returns:
            list: All transaction data for the account
        """
        all_transactions = []
        starting_after = None

        while True:
            try:
                params = {'limit': 100}
                if starting_after:
                    params['starting_after'] = starting_after

                endpoint = f"/accounts/{account_id}/transactions"
                response = self.make_authenticated_request(access_token, 'GET', endpoint, params=params)

                transactions = response.get('data', [])
                if not transactions:
                    break

                all_transactions.extend(transactions)

                # Check pagination
                pagination = response.get('pagination', {})
                if not pagination.get('next_uri'):
                    break

                # Extract starting_after from next_uri
                next_uri = pagination['next_uri']
                if 'starting_after=' in next_uri:
                    starting_after = next_uri.split('starting_after=')[1].split('&')[0]
                else:
                    break

            except Exception as e:
                logger.error(f"Error fetching transactions for account {account_id}: {str(e)}")
                break

        return all_transactions

    def sync_all_transaction_data(self, access_token):
        """
        Sync all transaction data from all accounts

        Returns:
            dict: Summary of sync operation
        """
        try:
            # Get all accounts
            accounts = self.get_all_accounts_with_pagination(access_token)

            total_transactions = 0
            accounts_processed = 0
            all_transactions = []

            for account in accounts:
                account_id = account['id']
                account_name = account.get('name', 'Unknown')

                logger.info(f"Syncing transactions for account: {account_name} ({account_id})")

                # Get all transactions for this account
                transactions = self.get_all_account_transactions_with_pagination(access_token, account_id)

                # Process each transaction
                for transaction in transactions:
                    # Convert to tax engine format
                    tax_transaction = self._convert_coinbase_transaction_to_tax_format(transaction, account)
                    if tax_transaction:
                        all_transactions.append(tax_transaction)
                        total_transactions += 1

                accounts_processed += 1

            return {
                'success': True,
                'accounts_processed': accounts_processed,
                'total_transactions': total_transactions,
                'transactions': all_transactions
            }

        except Exception as e:
            logger.error(f"Error syncing transaction data: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def _convert_coinbase_transaction_to_tax_format(self, coinbase_tx, account):
        """
        Convert Coinbase v2 transaction to tax engine format

        Args:
            coinbase_tx: Coinbase transaction data
            account: Account data for context

        Returns:
            dict: Transaction in tax engine format
        """
        try:
            # Extract basic transaction info
            tx_type = coinbase_tx.get('type')
            amount_data = coinbase_tx.get('amount', {})
            native_amount = coinbase_tx.get('native_amount', {})

            # Map Coinbase transaction types to tax types
            type_mapping = {
                'buy': 'buy',
                'sell': 'sell',
                'send': 'transfer_out',
                'receive': 'transfer_in',
                'trade': 'trade',
                'advanced_trade_fill': 'trade',
                'pro_deposit': 'deposit',
                'pro_withdrawal': 'withdrawal',
                'fiat_deposit': 'deposit',
                'fiat_withdrawal': 'withdrawal',
                'interest': 'staking_reward',
                'learning_reward': 'reward',
                'coinbase_earn': 'reward',
                'earn_payout': 'staking_reward',
                'mining_payout': 'mining_reward',
                'referral_bonus': 'reward'
            }

            mapped_type = type_mapping.get(tx_type, 'other')

            # Extract amounts
            amount = abs(float(amount_data.get('amount', 0)))
            currency = amount_data.get('currency', 'USD')

            # Extract USD value
            usd_value = abs(float(native_amount.get('amount', 0))) if native_amount.get('currency') == 'USD' else 0

            # Parse timestamp
            created_at = coinbase_tx.get('created_at')
            if created_at:
                from datetime import datetime
                timestamp = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                timestamp = datetime.now(timezone.utc)

            # Build tax transaction
            tax_transaction = {
                'user': None,  # Will be set by calling code
                'exchange': 'coinbase',
                'transaction_id': f"coinbase-oauth-{coinbase_tx['id']}",
                'transaction_type': mapped_type,
                'timestamp': timestamp,
                'asset_symbol': currency,
                'amount': amount,
                'price_usd': usd_value / amount if amount > 0 else 0,
                'value_usd': usd_value,
                'fee_amount': 0,  # v2 API doesn't provide detailed fee info
                'fee_asset': currency,
                'fee_usd': 0,
                'description': coinbase_tx.get('description', ''),
                'details': {
                    'coinbase_account_id': account['id'],
                    'coinbase_account_name': account.get('name'),
                    'original_transaction': coinbase_tx
                }
            }

            return tax_transaction

        except Exception as e:
            logger.error(f"Error converting Coinbase transaction: {str(e)}")
            return None 