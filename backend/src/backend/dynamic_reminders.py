"""Evaluate category reminders against the user's observed journey, without an LLM loop."""
import json
from datetime import datetime, timezone
from .session_manager import _haversine_m
from ..services.places_client import PlacesClient


SUPPORTED_CATEGORIES = frozenset("gas_station pharmacy supermarket grocery_store convenience_store restaurant cafe coffee_shop bakery bank atm hospital doctor dentist drugstore shopping_mall department_store clothing_store hardware_store home_goods_store electronics_store book_store pet_store gym park parking car_repair car_wash electric_vehicle_charging_station bus_station train_station airport post_office library school university hotel lodging movie_theater laundry hair_salon beauty_salon veterinary_care police fire_station store".split())


def policy_dict(value):
    return json.loads(value) if isinstance(value, str) and value else value or {}


class DynamicReminders:
    def __init__(self, db, cloud=None, places=None):
        self.db, self.cloud = db, cloud
        self.places = places or PlacesClient()

    def _state(self, uid, rid):
        if self.cloud:
            return self.cloud._user_collection(uid, 'dynamic_reminder_state').document(rid).get().to_dict() or {}
        with self.db._conn() as conn:
            row = conn.execute('SELECT payload FROM dynamic_reminder_state WHERE uid=? AND reminder_id=?', (uid, rid)).fetchone()
        return json.loads(row['payload']) if row else {}

    def _save(self, uid, rid, state):
        if self.cloud:
            self.cloud._user_collection(uid, 'dynamic_reminder_state').document(rid).set(state)
        else:
            with self.db._conn() as conn:
                conn.execute('INSERT OR REPLACE INTO dynamic_reminder_state VALUES (?,?,?)', (uid, rid, json.dumps(state)))

    def match(self, uid, reminder, event, now):
        policy = policy_dict(reminder.get('dynamic_policy'))
        if policy.get('version') != 1 or not policy.get('category'):
            return None
        loc = event.get('location') or event.get('gps') or {}
        if loc.get('latitude') is None or loc.get('longitude') is None or float(loc.get('accuracy_m', 999)) > 100:
            return None
        observed = datetime.fromisoformat(str(loc.get('timestamp') or event.get('occurred_at')).replace('Z', '+00:00'))
        if observed.tzinfo is None or not 0 <= (now - observed).total_seconds() <= 120:
            return None
        created = datetime.fromisoformat(str(reminder['created_at']).replace('Z', '+00:00'))
        if created.tzinfo is None: created = created.replace(tzinfo=timezone.utc)
        if now <= created: return None
        state = self._state(uid, reminder['id'])
        if state.get('at') and now.isoformat() <= state['at']: return None
        previous = state.get('location')
        state.update(at=now.isoformat(), location=loc)
        distance = lambda point: _haversine_m(loc['latitude'], loc['longitude'], point['latitude'], point['longitude'])
        origin, destination = policy.get('origin'), policy.get('destination')
        if origin and distance(origin) <= 200:
            state.update(origin_seen=now.isoformat(), journey_started=None)
        if destination and distance(destination) <= 150:
            state.pop('origin_seen', None)
            state.pop('journey_started', None)
            self._save(uid, reminder['id'], state)
            return None
        if origin:
            visited = state.get('origin_seen')
            if not visited or (now - datetime.fromisoformat(visited)).total_seconds() > 8 * 3600 or distance(origin) <= 250:
                self._save(uid, reminder['id'], state)
                return None
        # A named destination without an origin requires observed progress toward it.
        if destination and not origin:
            if not previous or distance(destination) >= _haversine_m(previous['latitude'], previous['longitude'], destination['latitude'], destination['longitude']) - 30:
                self._save(uid, reminder['id'], state)
                return None
        activity = str(event.get('activity', '')).upper()
        expected = {a.strip() for a in str(reminder.get('activity') or '').split(',') if a.strip()}
        matches_activity = activity in expected
        if 'CAR' in expected and activity == 'IN_VEHICLE':
            features = event.get('feature_summary') or {}
            matches_activity |= features.get('vehicle_class_hint') == 'CAR' and float(features.get('classification_confidence') or 0) >= 0.8
        for context in event.get('semantic_contexts', []):
            if context.get('state') not in expected or not context.get('active') or float(context.get('confidence', 0)) < 0.8:
                continue
            anchor = context.get('anchor')
            seen = context.get('last_observed_at')
            if anchor and seen:
                at = datetime.fromisoformat(str(seen).replace('Z', '+00:00'))
                matches_activity |= at.tzinfo is not None and 0 <= (now - at).total_seconds() <= 300 and distance(anchor) <= 200
        if expected and (not matches_activity or event.get('transition', 'ENTER') != 'ENTER'):
            self._save(uid, reminder['id'], state)
            return None
        if not state.get('journey_started'): state['journey_started'] = now.isoformat()
        # Bound provider calls; reuse nearby candidates while moving through the same area.
        search_origin = state.get('search_origin')
        age = (now - datetime.fromisoformat(state['searched_at'])).total_seconds() if state.get('searched_at') else 9999
        if not search_origin or distance(search_origin) > 500 or age > 300:
            candidates = self.places.search_nearby(loc['latitude'], loc['longitude'], radius_m=1000,
                uid=uid, max_results=20, included_types=[policy['category']])
            state.update(candidates=[p.model_dump() for p in candidates], search_origin=loc, searched_at=now.isoformat())
        self._save(uid, reminder['id'], state)
        radius = min(500, max(100, float(policy.get('radius_m', 350))))
        candidates = sorted(state.get('candidates', []), key=distance)
        for place in candidates:
            # Only a provider-verified category, never a display-name guess.
            if place.get('category') != policy['category']: continue
            dist = distance(place)
            if dist + float(loc.get('accuracy_m', 0)) > radius: continue
            if previous:
                old = _haversine_m(previous['latitude'], previous['longitude'], place['latitude'], place['longitude'])
                if dist > old + 40: continue  # already travelling away from it
            return place
        return None
