"""
Google Places API (New) — server-side POI enrichment.

Called only when a decision needs a resolved place and the current
session/context doesn't already have one. Enforces per-user daily budget.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..settings import GOOGLE_PLACES_API_KEY, PLACES_DAILY_BUDGET_PER_USER
from ..models.schemas import POICandidate

logger = logging.getLogger(__name__)

# Simple in-memory budget tracker (per-instance).
# For multi-instance Cloud Run, move to Firestore counters.
_daily_budgets: dict[str, int] = {}


class PlacesClient:
    """
    Google Places API (New) — Nearby Search.

    Uses a tight radius and minimal field mask to keep cost and
    attribution requirements manageable.
    """

    NEARBY_SEARCH_URL = "https://places.googleapis.com/v1/places:searchNearby"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or GOOGLE_PLACES_API_KEY

    def search_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 100.0,
        uid: str = "",
        max_results: int = 5,
    ) -> list[POICandidate]:
        """
        Search for nearby places around ``(latitude, longitude)``.

        Returns a list of POICandidate objects, or an empty list if
        the API key is not configured, the budget is exhausted, or
        an error occurs.
        """
        if not self._api_key:
            logger.warning(
                "Places API key not configured — skipping POI enrichment")
            return []

        # Budget check
        if not self._check_budget(uid):
            logger.info("Places API daily budget exhausted for uid=%s", uid)
            return []

        try:
            response = httpx.post(
                self.NEARBY_SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": (
                        "places.id,places.displayName,"
                        "places.primaryType,places.location,"
                        "places.shortFormattedAddress"
                    ),
                },
                json={
                    "locationRestriction": {
                        "circle": {
                            "center": {
                                "latitude": latitude,
                                "longitude": longitude,
                            },
                            "radius": radius_m,
                        },
                    },
                    "maxResultCount": max_results,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()

            self._record_usage(uid)

            return self._parse_results(data, latitude, longitude)

        except httpx.HTTPStatusError as e:
            logger.error("Places API HTTP error: %s", e)
            return []
        except Exception as e:
            logger.error("Places API error: %s", e)
            return []

    # ── Budget management ────────────────────────────────────────────────

    def _check_budget(self, uid: str) -> bool:
        """Check if the user still has Places API budget remaining."""
        if not uid:
            return True
        used = _daily_budgets.get(uid, 0)
        return used < PLACES_DAILY_BUDGET_PER_USER

    def _record_usage(self, uid: str) -> None:
        """Record a Places API call against the user's daily budget."""
        if uid:
            _daily_budgets[uid] = _daily_budgets.get(uid, 0) + 1

    @staticmethod
    def reset_budgets() -> None:
        """Reset all daily budgets (call from a daily cron)."""
        _daily_budgets.clear()

    # ── Response parsing ─────────────────────────────────────────────────

    @staticmethod
    def _parse_results(
        data: dict[str, Any],
        origin_lat: float,
        origin_lon: float,
    ) -> list[POICandidate]:
        """Parse Google Places API (New) response into POICandidate list."""
        candidates: list[POICandidate] = []

        for place in data.get("places", []):
            location = place.get("location", {})
            lat = location.get("latitude", 0.0)
            lon = location.get("longitude", 0.0)

            # Approximate distance in meters
            from ..backend.session_manager import _haversine_m
            distance = _haversine_m(origin_lat, origin_lon, lat, lon)

            display_name = place.get("displayName", {})
            name = display_name.get("text", "") if isinstance(
                display_name, dict) else str(display_name)

            candidates.append(POICandidate(
                name=name,
                category=place.get("primaryType", "unknown"),
                place_id=place.get("id"),
                latitude=lat,
                longitude=lon,
                distance_m=round(distance, 1),
                # closer = more confident
                confidence=max(0.0, 1.0 - distance / 200.0),
            ))

        # Sort by distance
        candidates.sort(key=lambda c: c.distance_m)
        return candidates
