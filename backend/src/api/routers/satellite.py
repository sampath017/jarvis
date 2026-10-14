"""Transient Google satellite imagery for the phone's read-only map card."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from ..auth import get_current_user
from ..rate_limiter import TokenBudgetGuard
from ...services.satellite_vision_service import SatelliteVisionService

router = APIRouter(prefix='/mobile', tags=['satellite'])


class SatelliteMapRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    latitude: float = Field(ge=-85, le=85)
    longitude: float = Field(ge=-180, le=180)
    zoom: int = Field(default=19, ge=18, le=21, strict=True)


@router.post('/satellite-map')
def satellite_map(request: SatelliteMapRequest,
                  uid: Annotated[str, Depends(get_current_user)]):
    TokenBudgetGuard().check_request_rate(uid)
    image = SatelliteVisionService().fetch_satellite_image(request.latitude,request.longitude,request.zoom)
    if not image:
        raise HTTPException(503,'Google satellite imagery is unavailable. Try again later.')
    # Return the complete provider image, including Google logo and attribution.
    return Response(image, media_type='image/png', headers={
        'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})
