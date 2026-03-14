"""
Security Middleware and Utilities

Implements:
1. Security headers (CSP, X-Frame-Options, etc.)
2. Rate limiting
3. Input sanitization
"""

import logging
import re
import time
from collections import defaultdict
from typing import Optional, Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ============================================================
# SECURITY HEADERS MIDDLEWARE
# ============================================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only add CSP to HTML responses (not API JSON responses)
        # CSP on API responses can cause browsers to block cross-origin fetches
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self'; "
                "connect-src 'self' https://blockstream.info wss:; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # XSS Protection (legacy, but still useful for older browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer Policy - don't leak referrer to third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions Policy - disable unnecessary browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(self)"
        )

        return response


# ============================================================
# RATE LIMITING MIDDLEWARE
# ============================================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiting.

    Limits:
    - General API: 100 requests/minute per IP
    - Deal creation: 10/minute per IP
    - Auth endpoints: 20/minute per IP
    """

    _CLEANUP_INTERVAL = 1000  # Sweep stale entries every N requests

    def __init__(self, app):
        super().__init__(app)
        self.requests: dict[str, list[float]] = defaultdict(list)
        self._cleanup_counter = 0
        self.limits = {
            "default": (100, 60),       # 100 requests per 60 seconds
            "deals_create": (10, 60),   # 10 deal creations per 60 seconds
            "auth": (20, 60),           # 20 auth attempts per 60 seconds
            "token_lookup": (10, 60),   # 10 token lookups per 60 seconds (prevent enumeration)
            "admin": (60, 60),          # 60 admin requests per 60 seconds
        }

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP, considering proxies."""
        # CF-Connecting-IP is set by Cloudflare and cannot be spoofed by the client
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            return cf_ip.strip()
        # Fallback for local dev: X-Forwarded-For
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        # Fall back to direct connection IP
        return request.client.host if request.client else "unknown"

    def _get_rate_limit_key(self, request: Request) -> tuple[str, str]:
        """Determine rate limit category and key."""
        ip = self._get_client_ip(request)
        path = request.url.path
        method = request.method

        # Deal creation
        if path == "/deals" and method == "POST":
            return f"deals_create:{ip}", "deals_create"

        # Auth endpoints (exclude read-only status polling)
        if "/auth/" in path and "/status/" not in path:
            return f"auth:{ip}", "auth"
        # Auth status polling (read-only, high frequency) — use default limit
        if "/auth/" in path and "/status/" in path:
            return f"default:{ip}", "default"

        # Deal token lookup (prevent enumeration)
        if "/deals/token/" in path and method == "GET":
            return f"token_lookup:{ip}", "token_lookup"

        # Admin endpoints
        if "/admin" in path:
            return f"admin:{ip}", "admin"

        # Default
        return f"default:{ip}", "default"

    def _is_rate_limited(self, key: str, category: str) -> bool:
        """Check if request should be rate limited."""
        max_requests, window_seconds = self.limits.get(category, self.limits["default"])
        now = time.time()
        window_start = now - window_seconds

        # Clean old entries for this key
        self.requests[key] = [t for t in self.requests[key] if t > window_start]

        # Periodic full sweep to prevent unbounded memory growth from many unique IPs
        self._cleanup_counter += 1
        if self._cleanup_counter >= self._CLEANUP_INTERVAL:
            self._cleanup_counter = 0
            max_window = max(w for _, w in self.limits.values())
            cutoff = now - max_window
            stale_keys = [k for k, timestamps in self.requests.items()
                          if not timestamps or timestamps[-1] < cutoff]
            for k in stale_keys:
                del self.requests[k]

        # Check limit
        if len(self.requests[key]) >= max_requests:
            return True

        # Record this request
        self.requests[key].append(now)
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        key, category = self._get_rate_limit_key(request)

        if self._is_rate_limited(key, category):
            max_requests, window = self.limits[category]
            logger.warning("Rate limit hit: %s (%s: %d/%ds)", key, category, max_requests, window)
            return Response(
                content=f'{{"detail":"Rate limit exceeded. Max {max_requests} requests per {window} seconds."}}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(window),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Reset": str(int(time.time()) + window),
                }
            )

        response = await call_next(request)

        # Add rate limit headers to response
        max_requests, window = self.limits[category]
        remaining = max_requests - len(self.requests[key])
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))

        return response


# ============================================================
# INPUT SANITIZATION
# ============================================================

def sanitize_for_display(text: Optional[str]) -> Optional[str]:
    """
    Sanitize text for display, removing potentially dangerous content
    while preserving readability.
    """
    if text is None:
        return None

    # Remove null bytes
    text = text.replace("\x00", "")

    # Remove other control characters (except newlines/tabs)
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    return text


def strip_html_tags(text: Optional[str]) -> Optional[str]:
    """
    Remove all HTML tags from text.

    Use this for fields that should never contain HTML.
    """
    if text is None:
        return None

    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', text)

    # Also remove null bytes and control chars
    clean = sanitize_for_display(clean)

    return clean


def validate_length(text: Optional[str], max_length: int, field_name: str = "field") -> str:
    """Validate and truncate text to maximum length."""
    if text is None:
        return ""

    if len(text) > max_length:
        # Truncate with indicator
        return text[:max_length - 3] + "..."

    return text


# ============================================================
# INPUT VALIDATION HELPERS
# ============================================================

# Maximum field lengths
MAX_LENGTHS = {
    "title": 200,
    "description": 5000,
    "seller_id": 100,
    "buyer_id": 100,
    "tracking_number": 100,
    "shipping_notes": 1000,
    "dispute_reason": 2000,
}


