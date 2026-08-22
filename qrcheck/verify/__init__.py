"""Stage 3b - resolve a decoded URL and prove it renders a live merchant profile.

The package is platform-pluggable: `get_verifier(platform)` returns a Verifier.
Today only Carousell is implemented, but the interface (resolve -> render ->
extract username/liveness) is platform-agnostic.
"""
from __future__ import annotations

from .base import Verifier, VerifierConfig
from .carousell import CarousellVerifier


def get_verifier(platform: str = "carousell", **kwargs) -> Verifier:
    platform = (platform or "carousell").lower()
    if platform == "carousell":
        return CarousellVerifier(**kwargs)
    raise ValueError(f"No verifier registered for platform {platform!r}")


__all__ = ["Verifier", "VerifierConfig", "CarousellVerifier", "get_verifier"]
