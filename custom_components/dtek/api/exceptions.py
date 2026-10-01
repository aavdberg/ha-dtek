"""Exceptions for the DTEK API client."""

from __future__ import annotations


class DtekError(Exception):
    """Base exception for all DTEK API errors."""


class DtekConnectionError(DtekError):
    """Exception raised when connection to DTEK portal fails."""


class DtekRateLimitError(DtekError):
    """Exception raised when rate limit or WAF challenge is encountered (HTTP 429)."""


class DtekCsrfError(DtekError):
    """Exception raised when CSRF token cannot be extracted."""


class DtekResponseError(DtekError):
    """Exception raised when DTEK returns an invalid or error response."""


class DtekAddressNotFoundError(DtekError):
    """Exception raised when an address or house number is not found."""
