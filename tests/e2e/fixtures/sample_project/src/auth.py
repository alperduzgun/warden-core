"""Authentication module with moderate complexity."""
import hashlib
import hmac

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()

def verify_token(token: str, secret: str) -> bool:
    parts = token.split('.')
    if len(parts) != 3:
        return False
    payload = parts[1]
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, parts[2])
