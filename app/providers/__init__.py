"""External data & execution providers.

* ``dhan``         - broker market-data + order APIs (primary)
* ``openai_client``- LLM structured research (news / fundamental interpretation)
* ``news``         - news retrieval pipeline
* ``fundamentals`` - fundamental data retrieval
* ``universe``     - NSE constituent lists & Dhan security-id mapping

Every provider degrades gracefully: when credentials are missing it reports an
explicit *unavailable* state rather than fabricating data. Price/÷order data is
never invented.
"""


class ProviderError(Exception):
    """Base class for provider failures."""


class ProviderUnavailable(ProviderError):
    """Raised when a provider is not configured / offline."""


class ProviderDataError(ProviderError):
    """Raised when a provider returns malformed or insufficient data."""
