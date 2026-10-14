"""Uncertain satellite footprints and independent departure evidence."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def boundary_dict(value):
    try:
        value = json.loads(value) if isinstance(value, str) else value
        if not isinstance(value, dict) or value.get('version') != 1 or value.get('source') != 'satellite_estimate':
            return None
        confidence, uncertainty = float(value.get('confidence',0)), float(value.get('uncertainty_m',0))
        if not math.isfinite(confidence) or not 0.8 <= confidence <= 1 or not math.isfinite(uncertainty) or not 10 <= uncertainty <= 100:
            return None
        points = value.get('polygon')
        if not isinstance(points, list) or not 3 <= len(points) <= 64 or not stamp(value.get('estimated_at')):
            return None
        coords = [(float(p['latitude']), float(p['longitude'])) for p in points]
        if any(not math.isfinite(a) or not math.isfinite(b) or abs(a) > 85 or abs(b) > 180 for a, b in coords):
            return None
        if len(set(coords)) != len(coords):
            return None
        lat, lon = coords[0]
        xy = [_xy(a, b, lat, lon) for a, b in coords]
        if max(math.hypot(x, y) for x, y in xy) > 1000:
            return None
        area = abs(sum(xy[i][0]*xy[(i+1)%len(xy)][1] - xy[(i+1)%len(xy)][0]*xy[i][1] for i in range(len(xy)))) / 2
        if not 20 <= area <= 500_000:
            return None
        def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        for i in range(len(xy)):
            for j in range(i+1, len(xy)):
                if j == i+1 or (i == 0 and j == len(xy)-1):
                    continue
                a,b,c,d = xy[i],xy[(i+1)%len(xy)],xy[j],xy[(j+1)%len(xy)]
                # Touching/crossing non-adjacent edges are not a simple footprint.
                if cross(a,b,c)*cross(a,b,d) <= 0 and cross(c,d,a)*cross(c,d,b) <= 0 and max(min(a[0],b[0]),min(c[0],d[0])) <= min(max(a[0],b[0]),max(c[0],d[0])) and max(min(a[1],b[1]),min(c[1],d[1])) <= min(max(a[1],b[1]),max(c[1],d[1])):
                    return None
        return value
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _xy(lat, lon, lat0, lon0):
    return (math.radians(lon-lon0)*6_371_000*math.cos(math.radians(lat0)),
            math.radians(lat-lat0)*6_371_000)


def signed_distance(location, boundary):
    """Metres to closest footprint edge; positive outside, negative inside."""
    xy = [_xy(float(p['latitude']),float(p['longitude']),float(location['latitude']),float(location['longitude']))
          for p in boundary['polygon']]
    inside, nearest = False, float('inf')
    for i,(x,y) in enumerate(xy):
        xx,yy = xy[(i+1)%len(xy)]
        if (y > 0) != (yy > 0) and 0 < x+(xx-x)*(-y)/(yy-y):
            inside = not inside
        dx,dy = xx-x,yy-y
        t = max(0,min(1,-(x*dx+y*dy)/(dx*dx+dy*dy))) if dx*dx+dy*dy else 0
        nearest = min(nearest,math.hypot(x+t*dx,y+t*dy))
    return -nearest if inside else nearest


def evaluate_departure(state, boundary, event, location, now, origin=None):
    """Mutate scoped continuity only. Reused fixes and Wi-Fi loss alone cannot fire."""
    at = now.isoformat()
    state.update(at=at, location=location)
    reason = 'uncertain_boundary'
    def done(matched=False):
        state['last_evaluation'] = {'at':at,'reason':reason,'matched':matched}
        return matched
    accuracy = float(location.get('accuracy_m',999))
    if not math.isfinite(accuracy) or not 0 <= accuracy <= 100:
        reason = 'location_accuracy_required'
        return done()
    gap = signed_distance(location,boundary) if boundary else None
    outline_uncertainty = float(boundary['uncertainty_m']) if boundary else 0
    boundary_crossed = gap is not None and gap-accuracy-outline_uncertainty >= 3
    state['boundary_distance_m'] = round(gap,2) if gap is not None else None
    ambient = event.get('ambient_context') or {}
    captured = stamp(ambient.get('collected_at'))
    wifi = ambient.get('wifi') or {}
    wifi_fresh = captured is not None and abs((now-captured).total_seconds()) <= 30 and wifi.get('status') == 'available'
    connection = wifi.get('connected') or {}
    connected = connection.get('id') if wifi_fresh and float(connection.get('age_ms',99999)) <= 15000 else None
    activity = str(event.get('activity','')).upper()
    physical = event.get('event_type') in {'ACTIVITY_ENTER','ACTIVITY_TRANSITION','ACTIVITY_SAMPLE'}
    verified = event.get('activity_evidence') == 'android_transition' or (event.get('activity_evidence') == 'repeated_android_samples' and float(event.get('activity_confidence') or 0) >= 80)
    if physical and verified and event.get('transition') == 'ENTER' and activity in {'WALKING','ON_FOOT','RUNNING'}:
        state['walking_at'] = at
    # Initial home presence needs a confident footprint observation OR an
    # accurate fix at the saved home anchor plus connected-network evidence.
    origin_distance = math.hypot(*_xy(float(location['latitude']),float(location['longitude']),
        float(origin['latitude']),float(origin['longitude']))) if origin else float('inf')
    inside = gap is not None and gap + accuracy + outline_uncertainty <= 0
    anchored = connected and origin_distance + accuracy <= 30 and not boundary_crossed
    if inside or anchored:
        state['origin_seen'] = at
        # A poorer indoor fix must not degrade the calibrated home anchor.
        # Presence time still refreshes independently from measurement quality.
        previous_anchor = state.get('inside_location') or {}
        anchor_at = stamp(state.get('inside_anchor_at'))
        if not previous_anchor or not anchor_at or not 0 <= (now-anchor_at).total_seconds() <= 1800 or accuracy <= float(previous_anchor.get('accuracy_m',999)):
            state['inside_location'] = location
            state['inside_anchor_at'] = at
        if connected:
            state['home_wifi_id'] = connected
        state.pop('outside_candidate',None)
        reason = 'observed_inside_boundary' if inside else 'observed_home_anchor_and_wifi'
        return done()
    seen = stamp(state.get('origin_seen'))
    if not seen or not 0 <= (now-seen).total_seconds() <= 8*3600:
        reason = 'inside_observation_required'
        return done()
    if state.get('home_wifi_id') and connected == state['home_wifi_id'] and not boundary_crossed:
        state.pop('outside_candidate',None)
        reason = 'home_wifi_still_connected'
        return done()
    walking = stamp(state.get('walking_at'))
    anchor = state.get('inside_location')
    displacement = 0
    if anchor:
        displacement = math.hypot(*_xy(float(location['latitude']),float(location['longitude']),float(anchor['latitude']),float(anchor['longitude']))) - accuracy - float(anchor.get('accuracy_m',100))
    state['departure_evidence'] = {'boundary_crossed':boundary_crossed,
        'conservative_displacement_m':round(displacement,2),'walking':bool(walking and 0 <= (now-walking).total_seconds() <= 120)}
    position_support = boundary_crossed or (bool(state.get('home_wifi_id')) and displacement >= 20)
    if not position_support or not walking or not 0 <= (now-walking).total_seconds() <= 120:
        state.pop('outside_candidate',None)
        reason = 'uncertain_departure_position' if not position_support else 'fresh_walking_required'
        return done()
    # A missing/disabled Wi-Fi reading is not a disconnect. With no calibrated
    # home network, require a longer sequence of three independent fixes.
    home = state.get('home_wifi_id')
    wifi_away = bool(home and wifi_fresh and (not wifi.get('connected') or connected and connected != home))
    if home and not wifi_away and not boundary_crossed:
        state.pop('outside_candidate',None)
        reason = 'fresh_wifi_evidence_required'
        return done()
    fix_at = stamp(location.get('timestamp'))
    candidate = state.get('outside_candidate') or {}
    first = stamp(candidate.get('first_at'))
    if not first or not 0 <= (now-first).total_seconds() <= 90:
        candidate = {'first_at':at,'count':0}
    if fix_at and (not stamp(candidate.get('fix_at')) or fix_at > stamp(candidate['fix_at'])):
        candidate.update(count=candidate.get('count',0)+1,fix_at=fix_at.isoformat())
    state['outside_candidate'] = candidate
    required = 2 if wifi_away else 3
    elapsed = (now-stamp(candidate['first_at'])).total_seconds()
    matched = candidate.get('count',0) >= required and elapsed >= (5 if wifi_away else 10)
    reason = ('confirmed_boundary_departure' if boundary_crossed else 'confirmed_wifi_walking_displacement') if matched else 'confirming_outside_fixes'
    return done(matched)


def satellite_card(latitude, longitude, place_name='', place_id='', boundary=None):
    """Small data-only card; provider credentials and imagery never enter chat."""
    zoom = (boundary or {}).get('imagery',{}).get('zoom',19)
    zoom = zoom if type(zoom) is int and 18 <= zoom <= 21 else 19
    return '```satellite-map\n' + json.dumps({'latitude':latitude,'longitude':longitude,
        'place_name':place_name,'place_id':place_id,'zoom':zoom,
        **({'boundary':boundary} if boundary else {})},separators=(',',':')) + '\n```'


def append_satellite_cards(reply, messages):
    """Keep actual tool-produced image cards even if the model summarizes prose."""
    cards = []
    for message in messages:
        if getattr(message,'type','') != 'tool' or getattr(message,'name','') not in {'inspect_satellite_view','create_reminder'}:
            continue
        for match in re.finditer(r'```satellite-map\n([^`]{1,24000})\n```',str(message.content)):
            try:
                data = json.loads(match[1])
                lat,lon = float(data['latitude']),float(data['longitude'])
                if not math.isfinite(lat) or not math.isfinite(lon) or not -85 <= lat <= 85 or not -180 <= lon <= 180:
                    continue
                card = satellite_card(lat,lon,str(data.get('place_name',''))[:200],str(data.get('place_id',''))[:200],boundary_dict(data.get('boundary')))
                if card not in cards:
                    cards.append(card)
            except (ValueError,TypeError,KeyError):
                continue
    for card in cards[-2:]:
        # Compare metadata, not whitespace chosen by a language model.
        if card not in reply and card.split('\n')[1] not in reply:
            reply += '\n\n' + card
    return reply
