from datetime import datetime, timezone, timedelta
from unittest.mock import Mock
import json
import pytest
from src.backend.dynamic_reminders import DynamicReminders
from src.services.database import DatabaseService
from src.models.schemas import POICandidate
from src.cloud.agent_tools import build_agent_tools

NOW = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)

def event(lat, minute, activity='IN_VEHICLE', accuracy=5):
    now = NOW + timedelta(minutes=minute)
    return {'event_id': str(minute), 'occurred_at': now.isoformat(), 'activity': activity,
        'transition': 'ENTER', 'location': {'latitude': lat, 'longitude': 80.0,
        'accuracy_m': accuracy, 'timestamp': now.isoformat()}}, now

@pytest.mark.parametrize('category,activity', [('gas_station','IN_VEHICLE'), ('pharmacy','WALKING'), ('supermarket','ON_BICYCLE')])
def test_dynamic_categories_require_origin_then_departure_and_match_real_place(tmp_path, category, activity):
    db = DatabaseService(tmp_path / 'dynamic.db')
    policy = {'version': 1, 'category': category, 'origin': {'latitude':12., 'longitude':80.},
        'destination': {'latitude':12.02, 'longitude':80.}}
    reminder = db.create_reminder('u', {'title':'Errand', 'created_at':NOW.isoformat(), 'activity':activity,'dynamic_policy':policy})
    assert db.get_reminder('u', reminder['id'])['dynamic_policy']
    places = Mock()
    places.search_nearby.return_value = [POICandidate(name='Actual place', category=category,
        latitude=12.004, longitude=80., distance_m=110, confidence=1)]
    matcher = DynamicReminders(db, places=places)
    assert matcher.match('u', reminder, *event(12.003, 1, activity)) is None
    assert matcher.match('u', reminder, *event(12., 2, activity)) is None
    match = matcher.match('u', reminder, *event(12.003, 3, activity))
    assert match['name'] == 'Actual place'
    assert places.search_nearby.call_args.kwargs['included_types'] == [category]
    assert matcher.match('u', reminder, *event(12.003, 3, activity)) is None  # duplicate
    assert matcher.match('u', reminder, *event(12.02, 4, activity)) is None  # home closes journey
    assert matcher.match('u', reminder, *event(12.003, 5, activity)) is None  # no new gym visit

def test_stale_inaccurate_wrong_activity_and_wrong_category_do_not_fire(tmp_path):
    db=DatabaseService(tmp_path/'dynamic.db'); places=Mock()
    places.search_nearby.return_value=[POICandidate(name='Petrol pharmacy', category='pharmacy', latitude=12., longitude=80., distance_m=0, confidence=1)]
    m=DynamicReminders(db, places=places)
    r=db.create_reminder('u', {'title':'Fuel','created_at':NOW.isoformat(),'activity':'IN_VEHICLE','dynamic_policy':{'version':1,'category':'gas_station'}})
    e,t=event(12.,1)
    assert m.match('u',r,e,t+timedelta(minutes=10)) is None
    assert m.match('u',r,*event(12.,2, accuracy=200)) is None
    assert m.match('u',r,*event(12.,3, activity='STILL')) is None
    assert not places.search_nearby.called
    assert m.match('u',r,*event(12.,4)) is None

def test_dynamic_tool_does_not_save_midpoint(tmp_path):
    db=DatabaseService(tmp_path/'tool.db')
    tool=next(t for t in build_agent_tools(db,'u') if t.name=='create_reminder')
    result=tool.invoke({'title':'Buy milk','place_category':'supermarket','activity':'WALKING'})
    assert 'Saved dynamic reminder' in result
    saved=db.list_reminders('u')[0]
    assert saved['latitude'] is None and saved['longitude'] is None
    assert 'supermarket' in saved['dynamic_policy']
    before=len(db.list_reminders('u'))
    result=tool.invoke({'title':'Fuel','location_name':'gym to home route','latitude':12.,'longitude':80.})
    assert json.loads(result)['code'] == 'invalid_journey'
    assert json.loads(result)['saved'] is False
    assert len(db.list_reminders('u'))==before


def test_invalid_dynamic_time_is_not_saved(tmp_path):
    db=DatabaseService(tmp_path/'time.db')
    tool=next(t for t in build_agent_tools(db,'u') if t.name=='create_reminder')
    result=tool.invoke({'title':'Errand','place_category':'pharmacy','due_at':'sometime later'})
    assert json.loads(result)['code'] == 'invalid_time'
    assert json.loads(result)['saved'] is False
    assert db.list_reminders('u') == []


def test_dynamic_parked_policy_needs_fresh_nearby_parking_evidence(tmp_path):
    db=DatabaseService(tmp_path/'semantic.db'); places=Mock()
    places.search_nearby.return_value=[POICandidate(name='Pharmacy',category='pharmacy',latitude=12.,longitude=80.,distance_m=0,confidence=1)]
    matcher=DynamicReminders(db,places=places)
    r=db.create_reminder('u',{'title':'Collect medicine','created_at':NOW.isoformat(),'activity':'PARKED','dynamic_policy':{'version':1,'category':'pharmacy'}})
    e,t=event(12.,1,activity='STILL')
    e['semantic_contexts']=[{'state':'PARKED','active':True,'confidence':1,'anchor':{'latitude':12.,'longitude':80.},'last_observed_at':t.isoformat()}]
    assert matcher.match('u',r,e,t)['name']=='Pharmacy'
    e,t=event(12.02,2,activity='STILL')
    e['semantic_contexts']=[{'state':'PARKED','active':True,'confidence':1,'anchor':{'latitude':12.,'longitude':80.},'last_observed_at':t.isoformat()}]
    assert matcher.match('u',r,e,t) is None


def departure(db):
    return db.create_reminder('u', {'title': 'Buy milk', 'created_at': NOW.isoformat(),
        'delivery_mode': 'in_app_call', 'dynamic_policy': {'version': 1, 'trigger': 'exit',
        'origin': {'name': 'Gym', 'latitude': 12., 'longitude': 80.}, 'radius_m': 200}})


def test_departure_only_needs_real_inside_to_outside_no_shop_or_movement(tmp_path):
    from src.backend.context_automation import ContextAutomationService
    db = DatabaseService(tmp_path/'exit.db')
    r = departure(db)
    service = ContextAutomationService(db)
    assert not service.process_context_event('u', event(12.004, 1, 'STILL')[0])
    assert not service.process_context_event('u', event(12., 2, 'STILL')[0])
    assert not service.process_context_event('u', event(12.002, 3, 'STILL', accuracy=80)[0])
    assert service.process_context_event('u', event(12.004, 4, 'STILL')[0])
    assert not service.process_context_event('u', event(12.004, 5, 'STILL')[0])
    saved = db.get_reminder('u', r['id'])
    notice, = db.list_notifications('u')
    assert saved['status'] == 'COMPLETED'
    assert notice['trigger_type'] == 'GEOFENCE_EXIT'
    assert notice['payload']['delivery_mode'] == 'in_app_call'
    assert 'You left Gym' in notice['body']


def test_departure_ignores_stale_inaccurate_duplicate_and_out_of_order_samples(tmp_path):
    db=DatabaseService(tmp_path/'fresh-exit.db'); r=departure(db); places=Mock()
    matcher=DynamicReminders(db,places=places)
    e,t=event(12.,1)
    assert matcher.match('u',r,e,t+timedelta(minutes=5)) is None
    assert matcher.match('u',r,*event(12.,2,accuracy=200)) is None
    assert matcher.match('u',r,*event(12.004,3)) is None
    assert matcher.match('u',r,*event(12.,4)) is None
    assert matcher.match('u',r,*event(12.004,3)) is None
    assert matcher.match('u',r,*event(12.004,5))['trigger']=='exit'
    assert matcher.match('u',r,*event(12.004,5)) is None
    assert matcher.match('u',r,*event(12.004,600)) is None
    places.search_nearby.assert_not_called()


def test_tools_create_and_edit_departure_without_delete_or_confirmation(tmp_path):
    db=DatabaseService(tmp_path/'departure-tool.db')
    db.create_place('u', {'name':'Gym','latitude':12.,'longitude':80.})
    tools={t.name:t for t in build_agent_tools(db,'u')}
    result=tools['create_reminder'].invoke({'title':'Buy milk','journey_origin':'Gym','delivery_mode':'in_app_call'})
    assert 'Saved departure reminder' in result
    r,=db.list_reminders('u')
    assert json.loads(r['dynamic_policy'])['trigger']=='exit' and r['activity'] is None
    assert r['delivery_mode']=='in_app_call'
    db.update_reminder('u',r['id'],{'dynamic_policy':{'version':1,'category':'supermarket'},'activity':'WALKING'})
    result=tools['update_reminder'].invoke({'reminder_id':r['id'],'journey_origin':'Gym','delivery_mode':'in_app_call'})
    assert 'Successfully updated' in result
    edited,=db.list_reminders('u')
    assert edited['id']==r['id'] and edited['status']=='ACTIVE' and edited['activity'] is None
    assert 'category' not in json.loads(edited['dynamic_policy'])
