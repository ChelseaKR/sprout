"""Pl@ntNet identification provider — the single allowlisted vision egress.

Pl@ntNet (https://my.plantnet.org/) is a plant-domain identification service with a
documented HTTP API (``POST /v2/identify/all``) that returns scored scientific names and
common names. We send only the uploaded image bytes to that one endpoint; no other
network egress is introduced. The API key is read from ``PLANTNET_API_KEY`` (environment
only, never config or logs).

Same fail-closed posture as every other network seam in Sprout: any error, missing key,
or malformed response yields an empty :class:`Identification`, so the photo path degrades
to the "type the plant's name" fallback rather than inventing a species. The response
parser lives in ``sprout.identify`` and is unit-tested offline; this module is the thin,
injectable HTTP shell and is excluded from coverage (requires a live key and network).
"""

from __future__ import annotations

import os
from typing import Any

from ..identify import Identification, parse_plantnet


class PlantNetIdentifier:
    """Identify a plant photo via the Pl@ntNet API, constrained to that one endpoint."""

    provider = "plantnet"

    def __init__(
        self,
        endpoint: str = "https://my-api.plantnet.org/v2/identify/all",
        *,
        top_k: int = 5,
        timeout_s: float = 30.0,
        client: Any = None,
        api_key: str | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._top_k = top_k
        self._timeout_s = timeout_s
        self._client = client
        self._api_key = api_key or os.environ.get("PLANTNET_API_KEY", "")

    def identify(self, image: bytes) -> Identification:
        if not image or not self._api_key:
            return Identification(provider=self.provider)
        try:
            payload = self._invoke(image)
        except Exception:
            return Identification(provider=self.provider)
        return parse_plantnet(payload, top_k=self._top_k, provider=self.provider)

    def _invoke(self, image: bytes) -> dict[str, Any]:
        client = self._client
        if client is None:
            import httpx

            # Cached rather than rebuilt per call; see TitanEmbedding.embed.
            client = httpx.Client(timeout=self._timeout_s)
            self._client = client
        resp = client.post(
            self._endpoint,
            params={"api-key": self._api_key},
            data={"organs": "auto"},
            files={"images": ("photo.jpg", image, "image/jpeg")},
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result
