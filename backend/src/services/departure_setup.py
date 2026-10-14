"""Set up departure evidence once; sensor events never call vision providers."""
import json
from datetime import datetime, timezone

from .place_boundary import boundary_dict, satellite_card, stamp


def departure_policy(place):
    return {'version':2,'trigger':'exit','evidence_mode':'boundary_motion_wifi',
            'origin':{k:v for k,v in {'name':place['name'],'latitude':place['latitude'],
                'longitude':place['longitude'],'place_id':place.get('id')}.items() if v is not None}}


def cached_boundary(place, now=None):
    """Whether a successful estimate or bounded refusal is still fresh."""
    now = now or datetime.now(timezone.utc)
    try:
        cached = json.loads(place['boundary_json']) if isinstance(place.get('boundary_json'),str) else place.get('boundary_json') or {}
    except (ValueError,TypeError):
        cached = {}
    if not isinstance(cached,dict):
        cached = {}
    usable = boundary_dict(cached)
    checked = stamp(cached.get('estimated_at'))
    fresh = bool(checked and (usable or cached.get('analysis_version') == 3) and
                 0 <= (now-checked).total_seconds() < (7*86400 if usable else 6*3600))
    return fresh, usable


def ensure_boundary(db, uid, place, *, force=False):
    now = datetime.now(timezone.utc)
    fresh, usable = cached_boundary(place,now)
    if not force and fresh:
        return usable
    from .satellite_vision_service import SatelliteVisionService
    result = {}
    try:
        result = SatelliteVisionService().estimate_boundary(place['latitude'],place['longitude'],place_name=place['name'],uid=uid)
        boundary = boundary_dict(result.get('boundary'))
    except Exception:
        boundary = None
    if not isinstance(result,dict):
        result = {}
    stored = boundary or {'version':1,'source':'satellite_estimate','estimated_at':now.isoformat(),
        'analysis_version':3,
        'status':result.get('status') if result.get('status') in {'uncertain','unavailable'} else 'uncertain',
        'reason':str(result.get('reason') or 'outline_not_verified')[:80],
        'description':str(result.get('description') or 'No verified satellite boundary is available.')[:240],
        'attempts':result.get('attempts',[])[:2] if isinstance(result.get('attempts',[]),list) else []}
    if place.get('id'):
        db.update_place(uid,place['id'],{'boundary_json':stored})
        place['boundary_json'] = json.dumps(stored)
    return boundary


def place_card(place, boundary=None):
    return satellite_card(place['latitude'],place['longitude'],place['name'],place.get('id',''),boundary)
