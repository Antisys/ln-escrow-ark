"""
Settings storage for runtime-configurable values
"""
import fcntl
import json
from pathlib import Path
from typing import Optional
from backend.config import CONFIG

# Settings file path (in project data directory)
SETTINGS_FILE = Path(__file__).parent.parent.parent / "data" / "settings.json"


def _load_settings() -> dict:
    """Load settings from file"""
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _locked_read_modify_write(modify_fn) -> dict:
    """
    Atomically read-modify-write the settings file under an exclusive flock.
    modify_fn receives the current settings dict and must return the updated dict.
    """
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, 'a+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        content = f.read()
        settings = json.loads(content) if content.strip() else {}
        settings = modify_fn(settings)
        f.seek(0)
        f.truncate()
        f.write(json.dumps(settings, indent=2))
    return settings


def get_limits() -> dict:
    """
    Get current amount limits.
    Returns operational limits (what users see) within absolute bounds.
    """
    settings = _load_settings()
    limits = settings.get("limits", {})

    # Get values with defaults from config
    min_sats = limits.get("min_sats", CONFIG.limits.default_min_sats)
    max_sats = limits.get("max_sats", CONFIG.limits.default_max_sats)

    # Ensure within absolute bounds
    min_sats = max(min_sats, CONFIG.limits.absolute_min_sats)
    max_sats = min(max_sats, CONFIG.limits.absolute_max_sats)

    # Enforce hard test-phase cap (cannot be overridden by admin)
    test_cap = CONFIG.limits.test_phase_max_sats
    if test_cap > 0:
        max_sats = min(max_sats, test_cap)

    return {
        "min_sats": min_sats,
        "max_sats": max_sats,
        "absolute_min_sats": CONFIG.limits.absolute_min_sats,
        "absolute_max_sats": CONFIG.limits.absolute_max_sats,
        "test_phase_max_sats": test_cap,
    }


def set_limits(min_sats: Optional[int] = None, max_sats: Optional[int] = None) -> dict:
    """
    Set operational limits (admin only).
    Values must be within absolute bounds.
    Returns the new limits.
    """
    def _modify(settings):
        limits = settings.get("limits", {})

        if min_sats is not None:
            if min_sats < CONFIG.limits.absolute_min_sats:
                raise ValueError(f"min_sats cannot be below {CONFIG.limits.absolute_min_sats}")
            if min_sats > CONFIG.limits.absolute_max_sats:
                raise ValueError(f"min_sats cannot exceed {CONFIG.limits.absolute_max_sats}")
            limits["min_sats"] = min_sats

        if max_sats is not None:
            if max_sats < CONFIG.limits.absolute_min_sats:
                raise ValueError(f"max_sats cannot be below {CONFIG.limits.absolute_min_sats}")
            if max_sats > CONFIG.limits.absolute_max_sats:
                raise ValueError(f"max_sats cannot exceed {CONFIG.limits.absolute_max_sats}")
            limits["max_sats"] = max_sats

        # Ensure min <= max
        current_min = limits.get("min_sats", CONFIG.limits.default_min_sats)
        current_max = limits.get("max_sats", CONFIG.limits.default_max_sats)
        if current_min > current_max:
            raise ValueError(f"min_sats ({current_min}) cannot exceed max_sats ({current_max})")

        settings["limits"] = limits
        return settings

    _locked_read_modify_write(_modify)
    return get_limits()


def get_fees() -> dict:
    """
    Get current fee settings.
    Returns service fee percent and chain fee reserve.
    """
    settings = _load_settings()
    fees = settings.get("fees", {})
    return {
        "service_fee_percent": fees.get("service_fee_percent", 0),
        "chain_fee_sats": fees.get("chain_fee_sats", 100),
    }


def set_fees(service_fee_percent: Optional[float] = None, chain_fee_sats: Optional[int] = None) -> dict:
    """
    Set fee configuration (admin only).
    Returns the new fee settings.
    """
    def _modify(settings):
        fees = settings.get("fees", {})

        if service_fee_percent is not None:
            if service_fee_percent < 0 or service_fee_percent > 10:
                raise ValueError("service_fee_percent must be between 0 and 10")
            fees["service_fee_percent"] = service_fee_percent

        if chain_fee_sats is not None:
            if chain_fee_sats < 0 or chain_fee_sats > 10000:
                raise ValueError("chain_fee_sats must be between 0 and 10000")
            fees["chain_fee_sats"] = chain_fee_sats

        settings["fees"] = fees
        return settings

    _locked_read_modify_write(_modify)
    return get_fees()
