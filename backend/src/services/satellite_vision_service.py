"""
Satellite Vision Service for Jarvis.

Fetches high-resolution satellite aerial imagery from Google Maps Static Maps API
and performs visual reasoning using multimodal LLMs (e.g. GLM-5.3-flash / Gemini via OpenRouter)
to inspect building layout, entrance gates, internal walking paths, and spatial geometry.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from ..settings import GOOGLE_PLACES_API_KEY, OPENROUTER_API_KEY, OPENROUTER_MODEL_TIER2

logger = logging.getLogger(__name__)


class SatelliteVisionService:
    """Fetches satellite aerial images and performs spatial visual inspection."""

    _instance: Optional[SatelliteVisionService] = None
    _cache: Dict[Tuple[float, float, str], Tuple[float, str]] = {}
    CACHE_TTL_SECONDS = 3600.0  # 1 hour cache per area

    def __new__(cls) -> SatelliteVisionService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def fetch_satellite_image(
        self,
        latitude: float,
        longitude: float,
        zoom: int = 19,
        size: str = "640x640",
    ) -> Optional[bytes]:
        """Fetch satellite aerial PNG image from Google Maps Static API."""
        if not GOOGLE_PLACES_API_KEY:
            logger.warning("GOOGLE_PLACES_API_KEY not configured for SatelliteVisionService")
            return None

        url = "https://maps.googleapis.com/maps/api/staticmap"
        params = {
            "center": f"{latitude},{longitude}",
            "zoom": str(zoom),
            "size": size,
            "scale": "2",  # 2x high resolution
            "maptype": "satellite",
            "key": GOOGLE_PLACES_API_KEY,
        }

        try:
            resp = httpx.get(url, params=params, timeout=15.0)
            if resp.status_code == 200 and "image" in resp.headers.get("content-type", ""):
                logger.info(
                    "Fetched satellite image for (%f, %f) at zoom %d (%d bytes)",
                    latitude,
                    longitude,
                    zoom,
                    len(resp.content),
                )
                return resp.content
            else:
                logger.warning(
                    "Failed to fetch satellite image (HTTP %d): %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None
        except Exception as e:
            logger.error("Error fetching satellite map image: %s", e)
            return None

    def analyze_aerial_geometry(
        self,
        image_bytes: bytes,
        latitude: float,
        longitude: float,
        place_name: str = "",
        focus: str = "gates and walking paths",
    ) -> str:
        """Call multimodal LLM to analyze the satellite image."""
        if not OPENROUTER_API_KEY:
            return "Error: OPENROUTER_API_KEY is not configured for aerial visual analysis."

        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        place_desc = f"named '{place_name}'" if place_name else "at current location"

        prompt = (
            f"You are inspecting a high-resolution satellite aerial image of the premises/complex {place_desc} "
            f"located at GPS coordinates ({latitude:.5f}, {longitude:.5f}).\n"
            f"The user is asking specifically about: '{focus}'.\n\n"
            "Please provide a grounded visual spatial analysis covering:\n"
            "1. Building Layout & Blocks: Visible building structures, rooftops, shape, and arrangement.\n"
            "2. Entrance / Gates: Where the main entrance/exit security gates, driveways, or access points connect to the main road or surrounding lanes.\n"
            "3. Walking / Open Space: Paved pathways, internal perimeter driveways, courtyards, or open areas suitable for walking or exercising.\n"
            "4. Distance & Geometry Estimate: Approximate walking distance from the main residential buildings to the entrance gates or perimeter.\n"
            "Keep the response natural, clear, and actionable for an assistant answering a user."
        )

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": OPENROUTER_MODEL_TIER2,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64_img}"},
                        },
                    ],
                }
            ],
            "temperature": 0.2,
        }

        try:
            logger.info("Submitting satellite image to OpenRouter (%s)...", OPENROUTER_MODEL_TIER2)
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=45.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip()
            else:
                logger.warning("OpenRouter vision call failed (%d): %s", resp.status_code, resp.text[:200])
                return f"Aerial visual analysis failed (HTTP {resp.status_code})."
        except Exception as e:
            logger.error("Error calling OpenRouter vision API: %s", e)
            return f"Error executing visual analysis: {e}"

    def inspect_satellite_geometry(
        self,
        latitude: float,
        longitude: float,
        place_name: str = "",
        focus: str = "gates and walking paths",
    ) -> str:
        """Fetch satellite image and analyze geometry with spatial caching."""
        cache_key = (round(latitude, 4), round(longitude, 4), focus.lower().strip())
        now = time.time()

        if cache_key in self._cache:
            ts, cached_result = self._cache[cache_key]
            if now - ts < self.CACHE_TTL_SECONDS:
                logger.info("Returning cached satellite visual inspection for %s", cache_key)
                return cached_result

        img_bytes = self.fetch_satellite_image(latitude, longitude, zoom=19)
        if not img_bytes:
            # Fallback to slightly wider zoom 18
            img_bytes = self.fetch_satellite_image(latitude, longitude, zoom=18)

        if not img_bytes:
            return f"Unable to fetch Google Maps satellite aerial image for ({latitude:.4f}, {longitude:.4f})."

        result = self.analyze_aerial_geometry(
            image_bytes=img_bytes,
            latitude=latitude,
            longitude=longitude,
            place_name=place_name,
            focus=focus,
        )

        if result and not result.startswith("Error"):
            self._cache[cache_key] = (now, result)

        return result
