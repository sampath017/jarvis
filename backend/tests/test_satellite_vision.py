"""
Integration test for Satellite Vision Tool and Tier 2 ReAct agent.
"""

import pytest
from src.services.database import DatabaseService
from src.cloud.tier2_agent_tools import build_tier2_tools
from src.services.satellite_vision_service import SatelliteVisionService


def test_build_tier2_tools_has_satellite_tool():
    db = DatabaseService()
    tools = build_tier2_tools(db, "test_user")
    tool_names = [t.name for t in tools]
    assert "inspect_satellite_view" in tool_names


def test_satellite_vision_service_direct():
    service = SatelliteVisionService()
    # Coordinates for Navalur / Creations Valencia
    lat, lon = 12.8450, 80.2260
    img = service.fetch_satellite_image(lat, lon, zoom=18)
    assert img is not None
    assert len(img) > 10000

    analysis = service.inspect_satellite_geometry(
        latitude=lat,
        longitude=lon,
        place_name="Creations Valencia",
        focus="gates and walking space",
    )
    assert analysis is not None
    assert len(analysis) > 50
    assert "building" in analysis.lower() or "road" in analysis.lower() or "gate" in analysis.lower()
    print("\n[PASS] Satellite vision direct test passed! Analysis preview:\n", analysis[:200])


if __name__ == "__main__":
    print("Testing build_tier2_tools...")
    test_build_tier2_tools_has_satellite_tool()
    print("[PASS] inspect_satellite_view is registered in build_tier2_tools.")

    print("Testing satellite vision direct...")
    test_satellite_vision_service_direct()
    print("[ALL TESTS PASSED SUCCESSFULLY]")
