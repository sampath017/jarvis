"""
Tier 1 LangChain Agent Tools.

Provides callable LangChain @tool wrappers for physical context resolution,
including Google Places lookup, vibration signature matching for Royal Enfield Hunter 350,
and user geofence evaluation.
"""

from __future__ import annotations

import logging
import math
from typing import Any
from langchain_core.tools import tool

from ..services.database import DatabaseService

logger = logging.getLogger(__name__)


def build_tier1_tools(db: DatabaseService, uid: str) -> list[Any]:
    """Build a list of LangChain tools for Tier 1 Context Reasoner Agent."""

    @tool
    def lookup_nearby_places(
        lat: float = 0.0,
        lon: float = 0.0,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> str:
        """Resolve GPS coordinates to a nearby named place via Google Places or the local cache.
        Args:
            lat: GPS latitude coordinate.
            lon: GPS longitude coordinate.
            latitude: Optional alias for lat.
            longitude: Optional alias for lon.
        """
        effective_lat = latitude if latitude is not None else lat
        effective_lon = longitude if longitude is not None else lon

        try:
            from ..services.places_client import PlacesClient
            client = PlacesClient()
            pois = client.search_nearby(latitude=effective_lat, longitude=effective_lon, uid=uid)
            if not pois:
                return "No nearby POIs found within search radius."
            lines = [f"• {p.name} ({p.category}) - Confidence: {p.confidence:.2f}" for p in pois[:5]]
            return "Nearby Places:\n" + "\n".join(lines)
        except Exception as e:
            return f"Places lookup error: {e}"

    @tool
    def match_vibration_signature(
        features: str | dict | None = None,
        dominant_frequency_hz: float = 0.0,
        rms_energy: float = 0.0,
        spectral_entropy: float = 0.0,
    ) -> str:
        """Match IMU/vibration features against the known Hunter 350 spectral signature to confirm ride context.
        Args:
            features: Optional dictionary or text description of IMU features.
            dominant_frequency_hz: Primary vibration frequency in Hz.
            rms_energy: Root Mean Square energy of accelerometer.
            spectral_entropy: Spectral randomness of vibration.
        """
        # If features dict was passed
        if isinstance(features, dict):
            dominant_frequency_hz = features.get("dominant_frequency_hz", dominant_frequency_hz)
            rms_energy = features.get("rms_energy", rms_energy)
            spectral_entropy = features.get("spectral_entropy", spectral_entropy)

        # Hunter 350 J-series engine baseline:
        # Idle / low speed: 18 - 25 Hz
        # Cruising (30-70 km/h): 28 - 42 Hz with moderate RMS (0.8 - 2.5 g)
        # Car / Bus: Low frequency < 15 Hz with low RMS < 0.4 g
        # Walking: 1.5 - 3 Hz rhythmic footsteps
        if 20.0 <= dominant_frequency_hz <= 45.0 and rms_energy >= 0.5:
            confidence = 0.92 if 25.0 <= dominant_frequency_hz <= 38.0 else 0.78
            return (
                f"MATCH: Royal Enfield Hunter 350 signature detected. "
                f"Dominant frequency {dominant_frequency_hz:.1f} Hz matches single-cylinder 349cc J-series characteristics. "
                f"RMS energy {rms_energy:.2f}g confirms motorcycle chassis resonance. Confidence: {confidence:.2f}"
            )
        elif dominant_frequency_hz < 15.0 and rms_energy < 0.5:
            return (
                f"MATCH: Enclosed vehicle (Car / Bus). "
                f"Dominant frequency {dominant_frequency_hz:.1f} Hz is well below motorcycle engine harmonic. "
                f"RMS energy {rms_energy:.2f}g indicates smooth cabin isolation. Confidence: 0.85"
            )
        elif dominant_frequency_hz <= 4.0:
            return (
                f"MATCH: Pedestrian movement (Walking / Running). "
                f"Dominant frequency {dominant_frequency_hz:.1f} Hz matches bipedal stride rate. Confidence: 0.90"
            )
        else:
            return (
                f"INCONCLUSIVE: Dominant frequency {dominant_frequency_hz:.1f} Hz with RMS {rms_energy:.2f}g "
                f"does not distinctly match Hunter 350 or car baselines."
            )

    @tool
    def check_saved_geofences(
        lat: float = 0.0,
        lon: float = 0.0,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> str:
        """Check distance to the user's saved places (Home, Gym, Office).
        Args:
            lat: GPS latitude.
            lon: GPS longitude.
            latitude: Optional alias for lat.
            longitude: Optional alias for lon.
        """
        effective_lat = latitude if latitude is not None else lat
        effective_lon = longitude if longitude is not None else lon

        try:
            places = db.list_places(uid)
            if not places:
                return "User has no saved places defined."
            matches = []
            for p in places:
                plat = p.get("latitude") or 0.0
                plon = p.get("longitude") or 0.0
                radius = p.get("radius_m") or 150.0
                # Haversine distance in meters
                dlat = math.radians(effective_lat - plat)
                dlon = math.radians(effective_lon - plon)
                a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(plat)) * math.cos(math.radians(effective_lat)) * math.sin(dlon / 2) ** 2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                dist_m = 6371000 * c
                if dist_m <= radius:
                    matches.append(f"INSIDE GEOFENCE: '{p.get('name')}' ({p.get('category')}), {dist_m:.0f}m from center.")
                elif dist_m <= radius * 3:
                    matches.append(f"NEARBY GEOFENCE: '{p.get('name')}' ({p.get('category')}), {dist_m:.0f}m away.")
            if matches:
                return "\n".join(matches)
            return "GPS is not currently within any saved user geofence."
        except Exception as e:
            return f"Geofence check error: {e}"

    @tool
    def check_user_geofences(
        latitude: float = 0.0,
        longitude: float = 0.0,
        lat: float | None = None,
        lon: float | None = None,
    ) -> str:
        """Alias for check_saved_geofences."""
        eff_lat = lat if lat is not None else latitude
        eff_lon = lon if lon is not None else longitude
        return check_saved_geofences.invoke({"lat": eff_lat, "lon": eff_lon})

    return [
        lookup_nearby_places,
        match_vibration_signature,
        check_saved_geofences,
        check_user_geofences,
    ]
