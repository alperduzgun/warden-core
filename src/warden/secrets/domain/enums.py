"""Secret source enumerations."""

from enum import Enum


class SecretSource(Enum):
    """Source of the secret value.

    Indicates where a secret was retrieved from in the provider chain.
    """

    ENVIRONMENT = "environment"  # From os.environ (includes GitHub Actions)
    DOTENV = "dotenv"  # From .env file
    AZURE_KEY_VAULT = "azure_keyvault"  # From Azure Key Vault
    CACHE = "cache"  # From in-memory cache
    NOT_FOUND = "not_found"  # Secret not found in any source
