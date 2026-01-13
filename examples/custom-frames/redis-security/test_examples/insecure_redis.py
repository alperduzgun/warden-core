"""
Insecure Redis usage examples - FOR TESTING ONLY

This file contains intentionally insecure Redis code
to test the Redis Security Frame validator.

DO NOT use these patterns in production!
"""

import redis

# ❌ CRITICAL: No SSL/TLS
insecure_connection = redis.Redis(
    host='production-redis.example.com',
    port=6379,
    password='MySecretPassword123'  # ❌ CRITICAL: Hardcoded password
)

# ❌ CRITICAL: Insecure connection string
cache = redis.from_url('redis://user:password@redis.example.com:6379/0')

# ❌ HIGH: No authentication
no_auth_connection = redis.Redis(
    host='localhost',
    port=6379
)

# ❌ HIGH: Dangerous command usage
def flush_all_data():
    """Dangerous function - deletes ALL data!"""
    client = redis.Redis(host='localhost')
    client.FLUSHALL()  # ❌ Catastrophic data loss!

# ❌ HIGH: Using KEYS instead of SCAN
def get_all_keys():
    client = redis.Redis(host='localhost')
    all_keys = client.KEYS('*')  # ❌ Blocks Redis in production!
    return all_keys

# ❌ MEDIUM: No timeout configuration
no_timeout = redis.Redis(
    host='remote-server.com',
    port=6379
)

# ❌ Multiple issues in one connection
worst_case = redis.Redis(
    host='production-db.com',
    port=6379,
    password='admin123',  # ❌ Hardcoded
    # No SSL
    # No timeout
)
