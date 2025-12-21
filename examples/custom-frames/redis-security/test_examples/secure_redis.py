"""
Secure Redis usage examples - BEST PRACTICES

This file demonstrates secure Redis connection patterns.
Use these patterns in production.
"""

import os
import redis

# ✅ GOOD: Secure connection with SSL and env var password
secure_connection = redis.Redis(
    host='production-redis.example.com',
    port=6380,
    password=os.getenv('REDIS_PASSWORD'),
    ssl=True,
    ssl_cert_reqs='required',
    socket_timeout=5,
    socket_connect_timeout=5
)

# ✅ GOOD: Secure connection string (rediss://)
cache = redis.from_url(
    os.getenv('REDIS_URL', 'rediss://user@redis.example.com:6380/0')
)

# ✅ GOOD: Using SCAN instead of KEYS
def get_keys_safe(pattern='*'):
    """Safe way to iterate keys without blocking Redis."""
    client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        password=os.getenv('REDIS_PASSWORD'),
        ssl=True,
        socket_timeout=5
    )

    cursor = 0
    keys = []
    while True:
        cursor, partial_keys = client.scan(cursor, match=pattern, count=100)
        keys.extend(partial_keys)
        if cursor == 0:
            break
    return keys

# ✅ GOOD: Complete secure configuration
production_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', '6380')),
    password=os.getenv('REDIS_PASSWORD'),
    db=int(os.getenv('REDIS_DB', '0')),
    ssl=True,
    ssl_cert_reqs='required',
    socket_timeout=5,
    socket_connect_timeout=5,
    socket_keepalive=True,
    retry_on_timeout=True,
    health_check_interval=30
)
