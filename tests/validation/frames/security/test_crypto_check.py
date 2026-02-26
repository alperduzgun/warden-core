"""
Tests for WeakCryptoCheck - Weak Cryptography Detection.

Covers:
- MD5/SHA1 in password hashing context
- Safe MD5/SHA1 usage (checksums, cache keys) - should NOT flag
- DES, RC4 cipher usage
- ECB mode detection
- JavaScript crypto patterns
"""

import pytest

from warden.validation.domain.frame import CodeFile


@pytest.fixture
def SecurityFrame():
    from warden.validation.infrastructure.frame_registry import FrameRegistry
    registry = FrameRegistry()
    registry.discover_all()
    cls = registry.get_frame_by_id("security")
    if not cls:
        pytest.skip("SecurityFrame not found in registry")
    return cls


def _get_crypto_findings(findings):
    """Filter findings to only weak-crypto check results.

    Frame-level Finding objects use 'id' like 'security-weak-crypto-N'.
    We match on the 'weak-crypto' substring in the finding id.
    """
    return [f for f in findings if "weak-crypto" in f.id]


# =========================================================================
# MD5/SHA1 in password context
# =========================================================================

@pytest.mark.asyncio
async def test_md5_password_hashing_detected(SecurityFrame):
    """MD5 used for password hashing should be flagged."""
    code = '''
import hashlib

def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("CWE-328" in f.message for f in crypto_findings)


@pytest.mark.asyncio
async def test_sha1_password_hashing_detected(SecurityFrame):
    """SHA1 used for password hashing should be flagged."""
    code = '''
import hashlib

def verify_password(password, stored_hash):
    return hashlib.sha1(password.encode()).hexdigest() == stored_hash
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("CWE-328" in f.message for f in crypto_findings)


@pytest.mark.asyncio
async def test_md5_checksum_not_flagged(SecurityFrame):
    """MD5 used for file checksums should NOT be flagged."""
    code = '''
import hashlib

def compute_file_checksum(filepath):
    """Calculate MD5 checksum of a file for integrity verification."""
    h = hashlib.md5()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            h.update(chunk)
    return h.hexdigest()
'''
    code_file = CodeFile(path="utils.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) == 0


@pytest.mark.asyncio
async def test_md5_cache_key_not_flagged(SecurityFrame):
    """MD5 used for cache key generation should NOT be flagged."""
    code = '''
import hashlib

def get_cache_key(url):
    """Generate a cache key from URL."""
    return hashlib.md5(url.encode()).hexdigest()
'''
    code_file = CodeFile(path="cache.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) == 0


# =========================================================================
# Weak ciphers: DES, RC4, ECB
# =========================================================================

@pytest.mark.asyncio
async def test_ecb_mode_detected(SecurityFrame):
    """AES ECB mode usage should be flagged."""
    code = '''
from Crypto.Cipher import AES

def encrypt_data(key, data):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.encrypt(data)
'''
    code_file = CodeFile(path="crypto_utils.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("ECB" in f.message for f in crypto_findings)


@pytest.mark.asyncio
async def test_cipher_new_ecb_detected(SecurityFrame):
    """Cipher.new(key, AES.MODE_ECB) should be flagged."""
    code = '''
from Crypto.Cipher import AES

key = b'sixteen_byte_key'
cipher = Cipher.new(key, AES.MODE_ECB)
ciphertext = cipher.encrypt(b'secret data here')
'''
    code_file = CodeFile(path="encrypt.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("ECB" in f.message for f in crypto_findings)


@pytest.mark.asyncio
async def test_des_cipher_detected(SecurityFrame):
    """DES cipher usage should be flagged."""
    code = '''
from Crypto.Cipher import DES

def encrypt_with_des(key, data):
    cipher = DES.new(key, DES.MODE_CBC)
    return cipher.encrypt(data)
'''
    code_file = CodeFile(path="legacy_crypto.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("DES" in f.message for f in crypto_findings)


@pytest.mark.asyncio
async def test_rc4_cipher_detected(SecurityFrame):
    """RC4 (ARC4) cipher usage should be flagged."""
    code = '''
from Crypto.Cipher import ARC4

def encrypt_stream(key, data):
    cipher = ARC4.new(key)
    return cipher.encrypt(data)
'''
    code_file = CodeFile(path="stream_cipher.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("RC4" in f.message for f in crypto_findings)


# =========================================================================
# JavaScript patterns
# =========================================================================

@pytest.mark.asyncio
async def test_js_md5_password_detected(SecurityFrame):
    """JS crypto.createHash('md5') in password context should be flagged."""
    code = '''
const crypto = require('crypto');

function hashPassword(password) {
    return crypto.createHash('md5').update(password).digest('hex');
}
'''
    code_file = CodeFile(path="auth.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1


@pytest.mark.asyncio
async def test_js_des_cipher_detected(SecurityFrame):
    """JS crypto.createCipher('des',...) should be flagged."""
    code = '''
const crypto = require('crypto');

function encryptData(key, data) {
    const cipher = crypto.createCipher('des', key);
    return cipher.update(data, 'utf8', 'hex') + cipher.final('hex');
}
'''
    code_file = CodeFile(path="encrypt.js", content=code, language="javascript")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) >= 1
    assert any("DES" in f.message for f in crypto_findings)


# =========================================================================
# Clean code (no false positives)
# =========================================================================

@pytest.mark.asyncio
async def test_aes_gcm_not_flagged(SecurityFrame):
    """AES-GCM (strong crypto) should NOT be flagged."""
    code = '''
from Crypto.Cipher import AES

def encrypt_data(key, data, nonce):
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return ciphertext, tag
'''
    code_file = CodeFile(path="crypto_utils.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) == 0


@pytest.mark.asyncio
async def test_bcrypt_not_flagged(SecurityFrame):
    """bcrypt password hashing should NOT be flagged."""
    code = '''
import bcrypt

def hash_password(password):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt)

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed)
'''
    code_file = CodeFile(path="auth.py", content=code, language="python")
    frame = SecurityFrame()
    result = await frame.execute_async(code_file)
    crypto_findings = _get_crypto_findings(result.findings)
    assert len(crypto_findings) == 0
