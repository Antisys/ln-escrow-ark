"""
Configuration for Lightning Escrow Service.

Ark + Lightning only. All settings loaded from environment variables.
"""
import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / '.env')

VERSION = "0.2.0"

# Known dev oracle keys — used to warn when running with test keys in production
DEV_ORACLE_KEYS = frozenset({
    "031b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f",
    "024d4b6cd1361032ca9bd2aeb9d900aa4d45d9ead80ac9423374c451a7254d0766",
    "02531fe6068134503d2723133227c867ac8fa6c83c537e9a44c3c5bdbdcb1fe337",
})


@dataclass
class LimitsConfig:
    """Deal amount limits."""
    absolute_min_sats: int = 1
    absolute_max_sats: int = 100_000_000

    default_min_sats: int = 1
    default_max_sats: int = 10_000_000

    # Hard cap during test phase. Set to 0 to disable.
    # Only changeable via TEST_PHASE_MAX_SATS env var + restart.
    test_phase_max_sats: int = 10_000


@dataclass
class EscrowConfig:
    """Main service configuration."""
    admin_api_key: Optional[str] = None
    admin_pubkeys: list[str] = field(default_factory=list)

    external_url: Optional[str] = None
    frontend_url: Optional[str] = None
    lnurl_base_url: Optional[str] = None

    limits: Optional[LimitsConfig] = None

    def __post_init__(self):
        if self.limits is None:
            self.limits = LimitsConfig(
                default_min_sats=int(os.getenv('MIN_DEAL_SATS', '10000')),
                default_max_sats=int(os.getenv('MAX_DEAL_SATS', '10000000')),
                test_phase_max_sats=int(os.getenv('TEST_PHASE_MAX_SATS', '10000')),
            )


def get_config() -> EscrowConfig:
    """Load configuration from environment variables."""
    return EscrowConfig(
        admin_api_key=os.getenv("ADMIN_API_KEY"),
        admin_pubkeys=[
            p.strip()
            for p in os.getenv("ADMIN_PUBKEYS", "").split(",")
            if p.strip()
        ],
        external_url=os.getenv("EXTERNAL_URL"),
        frontend_url=os.getenv("FRONTEND_URL"),
        lnurl_base_url=os.getenv("LNURL_BASE_URL"),
    )


CONFIG = get_config()
