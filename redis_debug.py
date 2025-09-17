import redis
import zlib
import pickle

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, db=0)

def read_cache_value(key):
    """Read a value from Redis, handling Django's cache format"""
    value = r.get(key)
    if value:
        try:
            # First decompress
            decompressed = zlib.decompress(value)
            # Then unpickle
            unpickled = pickle.loads(decompressed)
            return unpickled
        except (zlib.error, pickle.UnpicklingError):
            # If not compressed/pickled, return as is
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return value
    return None

# Read progress
progress_key = 'crypto_tax:1:exchange_sync_progress_2'
status_key = 'crypto_tax:1:exchange_sync_status_2'
error_key = 'crypto_tax:1:exchange_sync_error_2'

print("\nCurrent Redis values:")
print(f"Progress: {read_cache_value(progress_key)}")
print(f"Status: {read_cache_value(status_key)}")
print(f"Error: {read_cache_value(error_key)}")

# Let's also monitor all keys for this exchange
print("\nAll keys for exchange 2:")
for key in r.keys('crypto_tax:1:exchange_sync_*_2'):
    print(f"\nKey: {key.decode('utf-8')}")
    print(f"Value: {read_cache_value(key.decode('utf-8'))}") 