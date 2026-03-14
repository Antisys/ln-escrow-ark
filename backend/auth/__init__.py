"""
Authentication module for trustMeBro-ARK Escrow

Provides LNURL-auth for wallet-based authentication and
deterministic ephemeral key derivation.
"""
from backend.auth.lnurl_auth import (
    LNURLAuthManager,
    AuthChallenge,
    get_auth_manager,
)

__all__ = [
    'LNURLAuthManager',
    'AuthChallenge',
    'get_auth_manager',
]
