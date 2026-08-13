"""OminiFlow HTTP client exceptions.

Messages shown to users must never include API keys or Authorization headers.
"""


class OminiFlowError(Exception):
    """Base error for the OminiFlow connector."""

    def __init__(self, message, *, http_status=None, payload=None):
        super().__init__(message)
        self.http_status = http_status
        self.payload = payload or {}

    @property
    def user_message(self):
        return str(self)


class OminiFlowConnectionError(OminiFlowError):
    """Network failure, DNS failure, or timeout."""


class OminiFlowAuthenticationError(OminiFlowError):
    """Invalid, expired, or missing API key."""


class OminiFlowAPIError(OminiFlowError):
    """Unexpected HTTP or JSON error from OminiFlow."""


class OminiFlowValidationError(OminiFlowError):
    """HTTP 400 / 409 / 422 or payload rejected by OminiFlow."""
