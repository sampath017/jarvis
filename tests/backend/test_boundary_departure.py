"""Departure evidence is smaller than a neighbourhood and stronger than GPS drift."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from src.backend.context_automation import ContextAutomationService
from src.backend.dynamic_reminders import DynamicReminders
from src.services.database import DatabaseService
from src.services.mobile_scope import MobileScope, current
from src.services.place_boundary import append_satellite_cards, boundary_dict, satellite_card, signed_distance
from src.services.record_store import RecordStore


NOW = datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)
UID = 'boundary-user'
HOME = 'saved-home'
WIFI = 'synthetic-home-network'


def footprint(**patch):
    """A synthetic ~40 m square, deliberately much smaller than 200 m."""
    return {
        'version': 1, 'source': 'satellite_estimate',
        'estimated_at': (NOW-timedelta(minutes=30)).isoformat(),
        'confidence': 0.95, 'uncertainty_m': 10,
        'polygon': [
            {'latitude': 11.99982, 'longitude': 79.999816},
            {'latitude': 11.99982, 'longitude': 80.000184},
            {'latitude': 12.00018, 'longitude': 80.000184},
            {'latitude': 12.00018, 'longitude': 79.999816},
        ], **patch,
    }


def place(boundary=True):
    return {
        'id': HOME, 'name': 'Home', 'latitude': 12.0, 'longitude': 80.0,
        'created_at': (NOW-timedelta(days=1)).isoformat(),
        'updated_at': (NOW-timedelta(days=1)).isoformat(),
        'boundary_json': json.dumps(footprint()) if boundary else None,
    }


def reminder():
    return {
        'id': 'departure', 'title': 'Drink water before going out',
        'created_at': (NOW-timedelta(hours=1)).isoformat(),
        'updated_at': (NOW-timedelta(hours=1)).isoformat(),
        'status': 'ACTIVE', 'delivery_mode': 'in_app_call',
        'dynamic_policy': {'version': 2, 'trigger': 'exit',
            'origin': {'name': 'Home', 'place_id': HOME,
                       'latitude': 12.0, 'longitude': 80.0}},
    }


def observation(seconds, *, latitude=12.0, accuracy=5, activity='WALKING',
                wifi=WIFI, wifi_status='available', evidence='android_transition',
                gps_seconds=None, event_type='ACTIVITY_ENTER'):
    at = NOW+timedelta(seconds=seconds)
    gps_at = NOW+timedelta(seconds=gps_seconds if gps_seconds is not None else seconds)
    network = {'status': wifi_status, 'nearby': []}
    if wifi is not None:
        network['connected'] = {'id': wifi, 'age_ms': 0}
    return {
        'event_id': f'event-{seconds}', 'event_type': event_type,
        'occurred_at': at.isoformat(), 'activity': activity,
        'activity_evidence': evidence, 'activity_confidence': 97,
        'transition': 'ENTER',
        'ambient_context': {'collected_at': at.isoformat(), 'wifi': network},
        'location': {'latitude': latitude, 'longitude': 80.0,
                     'accuracy_m': accuracy, 'timestamp': gps_at.isoformat()},
    }, at


def matcher(tmp_path, *, boundary=True):
    db = DatabaseService(tmp_path/'boundary.db')
    db.create_place(UID, place(boundary))
    saved = db.create_reminder(UID, reminder())
    return db, saved, DynamicReminders(db)


def test_footprint_distance_is_to_edge_not_home_center():
    boundary = boundary_dict(footprint())
    assert boundary is not None
    assert -21 < signed_distance({'latitude': 12.0, 'longitude': 80.0}, boundary) < -19
    assert 34 < signed_distance({'latitude': 12.0005, 'longitude': 80.0}, boundary) < 37


@pytest.mark.parametrize('patch', [
    {'source': 'model_guess'}, {'confidence': 0.4}, {'uncertainty_m': -1},
    {'estimated_at': 'not-a-time'},
    {'polygon': [{'latitude': float('nan'), 'longitude': 80.0}]*3},
])
def test_unusable_boundary_is_not_promoted_to_geometric_evidence(patch):
    assert boundary_dict(footprint(**patch)) is None


def test_crossing_polygon_and_walking_wifi_fires_once_inside_200m(tmp_path):
    db, saved, _ = matcher(tmp_path)
    service = ContextAutomationService(db)
    assert service.process_context_event(UID, observation(0)[0]) == []
    assert service.process_context_event(UID, observation(30, latitude=12.0005, wifi=None)[0]) == []
    notices = service.process_context_event(UID, observation(40, latitude=12.0006, wifi=None)[0])
    assert len(notices) == 1
    assert service.process_context_event(UID, observation(50, latitude=12.0007, wifi=None)[0]) == []
    assert db.get_reminder(UID, saved['id'])['status'] == 'COMPLETED'
    notice, = db.list_notifications(UID)
    assert notice['trigger_type'] == 'GEOFENCE_EXIT'
    assert notice['payload']['delivery_mode'] == 'in_app_call'


@pytest.mark.parametrize('boundary', [True, False])
def test_reused_gps_fix_cannot_confirm_departure(tmp_path, boundary):
    _, saved, m = matcher(tmp_path, boundary=boundary)
    assert m.match(UID, saved, *observation(0)) is None
    for second in (30, 40, 50):
        assert m.match(UID, saved, *observation(second, latitude=12.0006, gps_seconds=30, wifi=None)) is None


def test_wifi_loss_and_walking_inside_does_not_fire(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    for second in (30, 40, 50):
        assert m.match(UID, saved, *observation(second, latitude=12.00004, wifi=None)) is None


def test_uncertainty_overlapping_footprint_cannot_fire_without_wifi_displacement(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0, wifi=None)) is None
    for second in (30, 40, 50):
        # 33 m from center, uncertainty reaches well inside the 20 m footprint.
        assert m.match(UID, saved, *observation(second, latitude=12.0003, accuracy=30, wifi=None)) is None


def test_boundary_crossing_without_walk_evidence_does_not_fire(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0, activity='STILL')) is None
    for second in (30, 40, 50):
        assert m.match(UID, saved, *observation(second, latitude=12.0006, wifi=None, activity='UNKNOWN', evidence='cached_state')) is None


def test_stale_walking_does_not_confirm_departure(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    for second in (180, 190, 200):
        assert m.match(UID, saved, *observation(second, latitude=12.0006, wifi=None, activity='UNKNOWN', evidence='cached_state')) is None


@pytest.mark.parametrize('wifi_status', ['unavailable', 'disabled', 'location_permission_required'])
def test_unknown_wifi_is_not_a_disconnect(tmp_path, wifi_status):
    _, saved, m = matcher(tmp_path, boundary=False)
    assert m.match(UID, saved, *observation(0)) is None
    for second in (30, 40, 50):
        assert m.match(UID, saved, *observation(second, latitude=12.0006, wifi=None, wifi_status=wifi_status)) is None


def test_home_network_connection_blocks_false_departure(tmp_path):
    _, saved, m = matcher(tmp_path, boundary=False)
    assert m.match(UID, saved, *observation(0)) is None
    for second in (30, 40, 50):
        assert m.match(UID, saved, *observation(second, latitude=12.0006)) is None


def test_home_wifi_reaching_outdoors_does_not_veto_three_clear_polygon_fixes(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006)) is None
    assert m.match(UID, saved, *observation(35, latitude=12.00065)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0007))['trigger'] == 'exit'


def test_small_clear_footprint_crossing_is_not_recalibrated_as_home_wifi_anchor(tmp_path):
    db, saved, m = matcher(tmp_path)
    small = footprint(polygon=[
        {'latitude':11.999955,'longitude':79.999954},
        {'latitude':11.999955,'longitude':80.000046},
        {'latitude':12.000045,'longitude':80.000046},
        {'latitude':12.000045,'longitude':79.999954},
    ])
    db.update_place(UID,HOME,{'boundary_json':small})
    assert m.match(UID, saved, *observation(0)) is None
    # All points remain <30 m from the saved center and on home Wi-Fi, but the
    # estimate plus its uncertainty shows they crossed the small footprint.
    assert m.match(UID, saved, *observation(30, latitude=12.00021, accuracy=1)) is None
    assert m.match(UID, saved, *observation(35, latitude=12.00022, accuracy=1)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.00023, accuracy=1))['trigger'] == 'exit'


def test_without_footprint_home_wifi_walk_and_independent_displacement_can_confirm(tmp_path):
    _, saved, m = matcher(tmp_path, boundary=False)
    assert m.match(UID, saved, *observation(0)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, wifi=None)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0007, wifi=None))['trigger'] == 'exit'


def test_without_home_network_requires_three_independent_polygon_fixes(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0, wifi=None)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, wifi=None)) is None
    assert m.match(UID, saved, *observation(35, latitude=12.00065, wifi=None)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0007, wifi=None))['trigger'] == 'exit'


def test_no_footprint_or_home_network_cannot_infer_departure(tmp_path):
    _, saved, m = matcher(tmp_path, boundary=False)
    assert m.match(UID, saved, *observation(0, wifi=None)) is None
    for second in (30, 40, 50):
        assert m.match(UID, saved, *observation(second, latitude=12.0006, wifi=None)) is None


def test_less_accurate_home_fix_does_not_erase_better_departure_anchor(tmp_path):
    _, saved, m = matcher(tmp_path, boundary=False)
    assert m.match(UID, saved, *observation(0, accuracy=5)) is None
    # Both observations establish home presence. The later estimate is noisier;
    # it should refresh presence without replacing the better spatial reference.
    assert m.match(UID, saved, *observation(10, accuracy=20)) is None
    anchor = m._state(UID,saved['id'])['inside_location']
    assert anchor['accuracy_m'] == 5
    assert m.match(UID, saved, *observation(30, latitude=12.0006, accuracy=8, wifi=None)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0004, accuracy=8, wifi=None))['trigger'] == 'exit'


def test_out_of_order_observation_cannot_rewind_departure_evidence(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, wifi=None)) is None
    before = m._state(UID,saved['id'])
    assert m.match(UID, saved, *observation(20)) is None
    assert m._state(UID,saved['id']) == before
    assert m.match(UID, saved, *observation(40, latitude=12.0007, wifi=None))['trigger'] == 'exit'


def test_older_gps_cannot_count_as_a_second_independent_outside_fix(tmp_path):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, gps_seconds=35, wifi=None)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0006, gps_seconds=34, wifi=None)) is None
    assert m._state(UID,saved['id'])['outside_candidate']['count'] == 1
    assert m.match(UID, saved, *observation(50, latitude=12.0007, gps_seconds=50, wifi=None))['trigger'] == 'exit'


def test_replacing_boundary_requires_new_inside_observation(tmp_path):
    db, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, wifi=None)) is None
    revised = footprint(estimated_at=(NOW+timedelta(seconds=35)).isoformat())
    revised['polygon'][0]['longitude'] -= 0.00002
    db.update_place(UID, HOME, {'boundary_json': revised})
    assert m.match(UID, saved, *observation(40, latitude=12.0007, wifi=None)) is None
    assert not m._state(UID,saved['id']).get('origin_seen')


def test_equivalent_timezone_offsets_do_not_reject_newer_observations(tmp_path):
    _, saved, m = matcher(tmp_path)
    event, at = observation(0)
    local_at = at.astimezone(timezone(timedelta(hours=5,minutes=30)))
    event['occurred_at'] = local_at.isoformat()
    assert m.match(UID, saved, event, local_at) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, wifi=None)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0007, wifi=None))['trigger'] == 'exit'


def test_old_high_quality_anchor_expires_despite_recent_home_presence(tmp_path):
    _, saved, m = matcher(tmp_path, boundary=False)
    assert m.match(UID, saved, *observation(0, accuracy=5)) is None
    assert m.match(UID, saved, *observation(1200, accuracy=20)) is None
    assert m._state(UID,saved['id'])['inside_location']['accuracy_m'] == 5
    assert m.match(UID, saved, *observation(1801, accuracy=20)) is None
    state = m._state(UID,saved['id'])
    assert state['inside_location']['accuracy_m'] == 20
    assert state['inside_anchor_at'] == (NOW+timedelta(seconds=1801)).isoformat()


@pytest.mark.parametrize('wifi_status',['unavailable','disabled'])
def test_calibrated_wifi_becoming_unknown_allows_stronger_polygon_confirmation(tmp_path,wifi_status):
    _, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0)) is None
    assert m.match(UID, saved, *observation(30, latitude=12.0006, wifi=None, wifi_status=wifi_status)) is None
    assert m.match(UID, saved, *observation(35, latitude=12.00065, wifi=None, wifi_status=wifi_status)) is None
    assert m.match(UID, saved, *observation(40, latitude=12.0007, wifi=None, wifi_status=wifi_status))['trigger'] == 'exit'


@pytest.mark.parametrize('offset', [-120, -1, 0, 1, 5, 120])
def test_fresh_gps_can_precede_or_follow_its_transition(tmp_path, offset):
    db = DatabaseService(tmp_path/'timing.db')
    r = db.create_reminder(UID, {**reminder(), 'dynamic_policy': {
        'version': 1, 'trigger': 'exit', 'radius_m': 200,
        'origin': {'name': 'Synthetic origin', 'latitude': 12.0, 'longitude': 80.0}}})
    m = DynamicReminders(db)
    assert m.match(UID, r, *observation(0, gps_seconds=offset)) is None
    assert m._state(UID,r['id']).get('origin_seen') == NOW.isoformat()


@pytest.mark.parametrize('offset', [-121, 121])
def test_gps_outside_event_window_cannot_advance_inside_state(tmp_path, offset):
    db, saved, m = matcher(tmp_path)
    assert m.match(UID, saved, *observation(0, gps_seconds=offset)) is None
    assert not m._state(UID,saved['id']).get('origin_seen')


@contextmanager
def mobile_workspace():
    scope = MobileScope()
    token = current.set(scope)
    try:
        yield scope
    finally:
        current.reset(token)
        scope.release()


def test_boundary_and_evidence_survive_separate_phone_sql_requests():
    uid = 'jarvis_local_user'
    r = reminder()
    seed = {'records': {'reminders': [r], 'places': [place()]}}
    observations = [observation(0), observation(30, latitude=12.0006, wifi=None),
                    observation(40, latitude=12.0007, wifi=None)]
    for index, (event, at) in enumerate(observations):
        with mobile_workspace() as scope:
            scope.seed(deepcopy(seed))
            m = DynamicReminders(DatabaseService(), RecordStore())
            result = m.match(uid,r,event,at)
            assert bool(result) == (index == 2)
            seed['agent'] = {'records': scope.snapshot()['state_records']}
            if index == 0:
                state = m._state(uid,r['id'])
                assert state.get('home_wifi_id') == WIFI
                assert state.get('origin_seen')
            assert scope.changes()['records']['places'] == []


@pytest.mark.parametrize('tool_name',['inspect_satellite_view','create_reminder'])
def test_actual_satellite_tool_card_survives_model_prose_summary(tool_name):
    from langchain_core.messages import ToolMessage
    card = satellite_card(12.0,80.0,'Home',HOME,footprint())
    result = append_satellite_cards('I checked the satellite view.',[
        ToolMessage(name=tool_name,tool_call_id='map-call',content='Provider description\n'+card)])
    assert result.startswith('I checked the satellite view.')
    assert card in result
    assert result.count('```satellite-map') == 1


def test_unrelated_tool_user_and_assistant_cannot_supply_image_cards():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    card = satellite_card(12.0,80.0,'Home',HOME)
    reply = 'No map was requested.'
    assert append_satellite_cards(reply,[
        ToolMessage(name='search_web',tool_call_id='web-call',content=card),
        HumanMessage(content=card),AIMessage(content=card)]) == reply


def test_satellite_card_is_not_duplicated_in_reply_or_repeated_tool_results():
    from langchain_core.messages import ToolMessage
    card = satellite_card(12.0,80.0,'Home',HOME)
    messages = [ToolMessage(name='inspect_satellite_view',tool_call_id=str(i),content=card) for i in range(2)]
    assert append_satellite_cards('Map:\n'+card,messages).count('```satellite-map') == 1
    assert append_satellite_cards('Map:',messages).count('```satellite-map') == 1


@pytest.mark.parametrize('metadata',[
    'not JSON', 'null', '[]', '{}',
    '{"latitude":NaN,"longitude":80}',
    '{"latitude":12,"longitude":181}',
    '{"latitude":86,"longitude":80}',
])
def test_invalid_tool_map_metadata_does_not_append_card(metadata):
    from langchain_core.messages import ToolMessage
    card = '```satellite-map\n'+metadata+'\n```'
    assert append_satellite_cards('Summary',[
        ToolMessage(name='inspect_satellite_view',tool_call_id='map-call',content=card)]) == 'Summary'


def test_tool_card_retains_only_validated_boundary_and_two_recent_views():
    from langchain_core.messages import ToolMessage
    messages = [ToolMessage(name='inspect_satellite_view',tool_call_id=str(i),
        content=satellite_card(12.0+i*0.001,80.0,'Place '+str(i),str(i),{'source':'untrusted'})) for i in range(3)]
    result = append_satellite_cards('Maps',messages)
    assert result.count('```satellite-map') == 2
    assert 'Place 0' not in result
    assert 'Place 1' in result and 'Place 2' in result
    assert 'untrusted' not in result
