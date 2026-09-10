"""HTTP client vers `mcp.oto.cx` — façade unique pour le CLI."""
from .client import NinjaClient, NinjaError

__all__ = ["NinjaClient", "NinjaError"]
