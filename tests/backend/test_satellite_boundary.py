"""Provider-contract and map-projection tests; no real imagery/LLM calls."""
import json
import struct
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.services import satellite_vision_service as satellite
from src.api.routers import satellite as route

LAT,LON = 12.83713,80.2256
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00'*8 + struct.pack('>II',1280,1280) + b'provider-attribution-kept'


def estimate(**patch):
    return {'boundary_visible':True,'boundary_kind':'building','confidence':0.9,'uncertainty_m':12,
            'polygon_pixels':[{'x':480,'y':480},{'x':800,'y':480},{'x':800,'y':800},{'x':480,'y':800}],
            'description':'A clearly visible roof.',**patch}


def test_mercator_center_and_scaled_pixel_offsets():
    center = satellite.pixel_to_coordinate(640,640,LAT,LON)
    assert center['latitude'] == pytest.approx(LAT,abs=1e-10)
    assert center['longitude'] == pytest.approx(LON,abs=1e-10)
    east = satellite.pixel_to_coordinate(840,640,LAT,LON)
    assert east['latitude'] == pytest.approx(LAT,abs=1e-10)
    assert east['longitude']-LON == pytest.approx(100/(256*2**19)*360)
    north = satellite.pixel_to_coordinate(640,440,LAT,LON)
    assert north['latitude'] > LAT
    assert north['longitude'] == pytest.approx(LON)


def test_visible_polygon_becomes_georeferenced_estimate_with_uncertainty():
    result = satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON)
    assert result['source'] == 'satellite_estimate'
    assert result['confidence'] == 0.9 and result['uncertainty_m'] == 12
    assert 'estimated_at' in result and 'confirmed_at' not in result
    assert result['imagery'] == {'center_latitude':LAT,'center_longitude':LON,'zoom':19,'size':640,'scale':2}
    assert result['polygon'][0]['latitude'] > LAT
    assert result['polygon'][0]['longitude'] < LON


@pytest.mark.parametrize('patch',[
    {'boundary_visible':False}, {'boundary_visible':'true'}, {'confidence':0.79},
    {'confidence':float('nan')}, {'confidence':2}, {'uncertainty_m':0},
    {'uncertainty_m':float('inf')}, {'boundary_kind':'neighborhood'},
    {'polygon_pixels':[{'x':640,'y':640}]},
    {'polygon_pixels':[{'x':0,'y':0},{'x':900,'y':400},{'x':900,'y':900}]},
    {'polygon_pixels':[{'x':500,'y':1230},{'x':800,'y':1230},{'x':800,'y':800}]},
    {'polygon_pixels':[{'x':200,'y':200},{'x':300,'y':200},{'x':300,'y':300},{'x':200,'y':300}]},
    {'polygon_pixels':[{'x':480,'y':480},{'x':800,'y':800},{'x':800,'y':480},{'x':480,'y':800}]},
    {'polygon_pixels':[{'x':480,'y':480},{'x':800,'y':480},{'x':800,'y':480},{'x':480,'y':800}]},
])
def test_unclear_unbounded_wrong_anchor_or_malformed_geometry_is_not_saved(patch):
    assert satellite.parse_boundary_estimate(json.dumps(estimate(**patch)),LAT,LON) is None


@pytest.mark.parametrize('content',['narrative only','[]','{"boundary_visible":true}','```json\n{}\n```'])
def test_non_geometry_responses_fail_closed(content):
    assert satellite.parse_boundary_estimate(content,LAT,LON) is None


def test_vision_json_fence_is_supported():
    result = satellite.parse_boundary_estimate('```json\n'+json.dumps(estimate())+'\n```',LAT,LON)
    assert result is not None


def test_provider_image_keeps_google_attribution_and_key_stays_on_server(monkeypatch):
    monkeypatch.setattr(satellite,'GOOGLE_PLACES_API_KEY','server-only-key')
    get = Mock(return_value=Mock(status_code=200,headers={'content-type':'image/png'},content=PNG))
    monkeypatch.setattr(satellite.httpx,'get',get)
    image = satellite.SatelliteVisionService().fetch_satellite_image(LAT,LON)
    assert image == PNG
    args,kwargs = get.call_args
    assert args[0] == 'https://maps.googleapis.com/maps/api/staticmap'
    assert kwargs['params']['key'] == 'server-only-key'
    assert kwargs['params']['maptype'] == 'satellite'
    assert kwargs['params']['scale'] == '2'
    assert kwargs['params']['format'] == 'png'


@pytest.mark.parametrize('status,mime,body',[(403,'text/plain',b'key rejected'),
    (200,'text/html',b'<html>error</html>'),(200,'image/png',b'not-a-png')])
def test_failed_or_non_image_provider_response_is_not_displayed(monkeypatch,status,mime,body):
    monkeypatch.setattr(satellite,'GOOGLE_PLACES_API_KEY','test-key')
    monkeypatch.setattr(satellite.httpx,'get',Mock(return_value=Mock(status_code=status,headers={'content-type':mime},content=body)))
    assert satellite.SatelliteVisionService().fetch_satellite_image(LAT,LON) is None


def test_estimation_does_not_invent_boundary_on_bad_viewport_or_provider_failure(monkeypatch):
    service = satellite.SatelliteVisionService()
    vision = Mock()
    monkeypatch.setattr(service,'_boundary_vision_request',vision)
    monkeypatch.setattr(service,'fetch_satellite_image',lambda *a,**k: b'not-verifiable')
    assert service.estimate_boundary(LAT,LON)['status'] == 'unavailable'
    vision.assert_not_called()
    monkeypatch.setattr(service,'fetch_satellite_image',lambda *a,**k: None)
    assert service.estimate_boundary(LAT,LON)['status'] == 'unavailable'
    vision.assert_not_called()


def test_estimation_returns_estimate_without_persisting_image_or_shared_cache(monkeypatch):
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    monkeypatch.setattr(service,'fetch_satellite_image',lambda *a,**k: PNG)
    call = Mock(return_value=json.dumps(estimate()))
    monkeypatch.setattr(service,'_boundary_vision_request',call)
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['status'] == 'ok'
    assert result['boundary']['source'] == 'satellite_estimate'
    assert 'image' not in result and not hasattr(service,'_cache')
    assert call.call_args.args[0] == PNG


def test_vision_request_reserves_and_settles_actual_scoped_usage(monkeypatch):
    from src.api import rate_limiter
    guard = Mock()
    guard.check_and_reserve_tokens.return_value = ('day','reservation')
    monkeypatch.setattr(rate_limiter,'TokenBudgetGuard',lambda:guard)
    monkeypatch.setattr(satellite,'OPENROUTER_MODEL_MULTIMODAL','google/gemini-3.8-flash')
    response = Mock(status_code=200)
    response.json.return_value = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(estimate())}}],
        'usage':{'prompt_tokens':1200,'completion_tokens':450,'cost':0.001}}
    post = Mock(return_value=response)
    monkeypatch.setattr(satellite.httpx,'post',post)
    result = satellite.SatelliteVisionService()._boundary_vision_request(PNG,'inspect this','u')
    assert json.loads(result)['boundary_visible'] is True
    assert guard.check_and_reserve_tokens.call_args.args == ('u',38192)
    assert guard.check_and_reserve_tokens.call_args.kwargs['max_output_tokens'] == 8192
    assert guard.record_llm_usage.call_args.args == ('u',1200,450)
    assert guard.record_llm_usage.call_args.kwargs['reservation'] == ('day','reservation')
    assert guard.check_and_reserve_tokens.call_args.kwargs['model'] == 'google/gemini-3.8-flash'
    assert guard.record_llm_usage.call_args.kwargs['model'] == 'google/gemini-3.8-flash'
    assert post.call_args.kwargs['json']['model'] == 'google/gemini-3.8-flash'
    assert post.call_args.kwargs['json']['max_tokens'] == 8192
    assert post.call_args.kwargs['json']['reasoning'] == {'effort':'low'}
    assert post.call_args.kwargs['json']['response_format'] == {'type':'json_object'}
    assert post.call_args.kwargs['json']['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')


def test_map_endpoint_serves_uncropped_png_without_cache_or_credentials(monkeypatch):
    app = FastAPI()
    app.include_router(route.router)
    monkeypatch.setattr(route.TokenBudgetGuard,'check_request_rate',lambda *a:None)
    monkeypatch.setattr(route.SatelliteVisionService,'fetch_satellite_image',lambda *a,**k:PNG)
    with TestClient(app) as client:
        response = client.post('/mobile/satellite-map',json={'latitude':LAT,'longitude':LON,'zoom':19})
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-type'] == 'image/png'
    assert 'key' not in dict(response.headers)


@pytest.mark.parametrize('patch',[{'latitude':91},{'longitude':181},{'zoom':22},
    {'zoom':19.5},{'url':'https://untrusted.example/image'}])
def test_map_endpoint_rejects_unbounded_input(patch):
    with pytest.raises(ValidationError):
        route.SatelliteMapRequest.model_validate({'latitude':LAT,'longitude':LON,'zoom':19,**patch})


@pytest.fixture
def setup_scope():
    from src.services.mobile_scope import MobileScope,current
    scope = MobileScope()
    token = current.set(scope)
    try:
        yield scope
    finally:
        current.reset(token)
        scope.release()


def place_row(identifier='home', **patch):
    return {'id':identifier,'name':identifier.title(),'latitude':LAT,'longitude':LON,
            'created_at':'2026-01-01T00:00:00+00:00','updated_at':'2026-02-01T00:00:00+00:00',
            'address':'Synthetic address','notes':'Keep the east door note',
            'tags':['personal'],'alias':'My flat','radius_m':150,'phone_revision':'phone-17',**patch}


def reminder_row(identifier='leave-home', place='home', **patch):
    return {'id':identifier,'title':'Drink water','created_at':'2026-01-02T00:00:00+00:00',
            'updated_at':'2026-02-02T00:00:00+00:00','status':'ACTIVE','body':'Original body',
            'delivery_mode':'in_app_call','one_shot':False,'due_at':'2026-11-01T09:00:00+00:00',
            'last_fired_at':'2026-02-01T09:00:00+00:00','activity':None,
            'dynamic_policy':json.dumps({'version':1,'trigger':'exit','radius_m':200,
                'future_option':'keep-me','origin':{'name':place.title(),'latitude':LAT,'longitude':LON}}),**patch}


def test_setup_saves_boundary_and_upgrades_only_policy_preserving_phone_metadata(setup_scope,monkeypatch):
    from src.api.routers.mobile_compute import departure_boundaries
    from src.services.sqlite_store import SqlStore
    from src.services.departure_setup import ensure_boundary
    uid = 'jarvis_local_user'
    scope = setup_scope
    scope.db.execute('ALTER TABLE places ADD COLUMN phone_revision TEXT')
    scope.seed({'records':{'places':[place_row(),place_row('gym')],
                          'reminders':[reminder_row(),reminder_row('completed',status='COMPLETED')]}})
    sql = SqlStore()
    before_place = sql.get('places','home',uid=uid)
    before_other = sql.get('places','gym',uid=uid)
    before_reminder = sql.get('reminders','leave-home',uid=uid)
    provider = Mock(return_value={'status':'ok','boundary':satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON)})
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    result = departure_boundaries(uid)
    assert result['updated_reminders'] == ['leave-home']
    assert result['refreshed'] == ['home'] and result['pending_places'] == []
    assert provider.call_count == 1
    stored_place = sql.get('places','home',uid=uid)
    for field,value in before_place.items():
        if field not in {'boundary_json','updated_at'}:
            assert stored_place[field] == value
    assert sql.get('places','gym',uid=uid) == before_other
    boundary = json.loads(stored_place['boundary_json'])
    assert boundary['source'] == 'satellite_estimate'
    stored_reminder = sql.get('reminders','leave-home',uid=uid)
    for field,value in before_reminder.items():
        if field not in {'dynamic_policy','updated_at'}:
            assert stored_reminder[field] == value
    policy = json.loads(stored_reminder['dynamic_policy'])
    assert policy['version'] == 2 and policy['future_option'] == 'keep-me'
    assert 'radius_m' not in policy
    assert policy['origin']['place_id'] == 'home'
    assert sql.get('reminders','completed',uid=uid)['status'] == 'COMPLETED'
    changes = scope.changes()
    assert [r['id'] for r in changes['records']['places']] == ['home']
    assert [r['id'] for r in changes['records']['reminders']] == ['leave-home']
    assert changes['notifications'] == []
    # Repeating a foreground refresh reuses the persisted estimate, no provider work.
    departure_boundaries(uid)
    assert provider.call_count == 1


@pytest.mark.parametrize('value',[None,'broken json','[]','null','42','{"estimated_at":"bad"}'])
def test_setup_refusal_is_persisted_and_bounded_without_fabricating_geometry(setup_scope,monkeypatch,value):
    from src.services.database import DatabaseService
    from src.services.departure_setup import ensure_boundary
    uid = 'jarvis_local_user'
    setup_scope.seed({'records':{'places':[place_row(boundary_json=value)]}})
    db = DatabaseService()
    place = db.get_place(uid,'home')
    provider = Mock(return_value={'status':'uncertain','description':'Obscured roof.'})
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    assert ensure_boundary(db,uid,place) is None
    stored = json.loads(db.get_place(uid,'home')['boundary_json'])
    assert stored['status'] == 'uncertain'
    assert 'polygon' not in stored
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    assert provider.call_count == 1


def test_setup_refreshes_expired_estimates_and_retry_refusals(setup_scope,monkeypatch):
    from src.services.database import DatabaseService
    from src.services.departure_setup import ensure_boundary
    uid = 'jarvis_local_user'
    old = satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON)
    old['estimated_at'] = (datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    setup_scope.seed({'records':{'places':[place_row(boundary_json=old)]}})
    db = DatabaseService()
    provider = Mock(return_value={'status':'uncertain'})
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    assert provider.call_count == 1
    refused = {'version':1,'source':'satellite_estimate','status':'uncertain',
               'estimated_at':(datetime.now(timezone.utc)-timedelta(hours=7)).isoformat()}
    db.update_place(uid,'home',{'boundary_json':refused})
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    assert provider.call_count == 2


def test_setup_provider_limit_advances_past_cached_origins_on_next_request(setup_scope,monkeypatch):
    from src.api.routers.mobile_compute import departure_boundaries
    uid = 'jarvis_local_user'
    names = ['alpha','bravo','charlie','delta','echo']
    setup_scope.seed({'records':{'places':[place_row(n) for n in names],
        'reminders':[reminder_row('leave-'+n,place=n) for n in names]}})
    provider = Mock(return_value={'status':'uncertain'})
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    first = departure_boundaries(uid)
    assert provider.call_count == 1
    assert len(first['updated_reminders']) == 1
    assert len(first['pending_places']) == 4
    second = departure_boundaries(uid)
    assert provider.call_count == 2
    assert len(second['updated_reminders']) == 1
    assert len(second['pending_places']) == 3
    for _ in range(3):
        last = departure_boundaries(uid)
    assert provider.call_count == 5
    assert len(last['updated_reminders']) == 1
    assert last['pending_places'] == []


def test_wider_zoom_estimate_uses_correct_mercator_scale_and_metadata():
    close = satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON,zoom=19)
    wider = satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON,zoom=18)
    assert wider['imagery']['zoom'] == 18
    assert wider['polygon'][0]['longitude']-LON == pytest.approx(2*(close['polygon'][0]['longitude']-LON))
    assert wider['polygon'][0] == satellite.pixel_to_coordinate(480,480,LAT,LON,zoom=18)
    assert satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON,zoom=17) is None


def test_unclear_close_view_retries_one_wider_view_without_guessing_hidden_edges(monkeypatch):
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    fetch = Mock(return_value=PNG)
    vision = Mock(side_effect=[json.dumps(estimate(boundary_visible=False,reason='cropped_outline')),
                              json.dumps(estimate())])
    monkeypatch.setattr(service,'fetch_satellite_image',fetch)
    monkeypatch.setattr(service,'_boundary_vision_request',vision)
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['status'] == 'ok'
    assert result['boundary']['imagery']['zoom'] == 18
    assert result['attempts'] == [{'zoom':19,'reason':'cropped_outline'}]
    assert [c.kwargs['zoom'] for c in fetch.call_args_list] == [19,18]
    assert vision.call_count == 2
    assert all('Do not invent hidden edges' in c.args[1] for c in vision.call_args_list)
    assert all('whole apartment complex' in c.args[1] for c in vision.call_args_list)


def test_both_unclear_views_keep_uncertain_and_never_spend_third_call(monkeypatch):
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    fetch = Mock(return_value=PNG)
    vision = Mock(side_effect=[json.dumps(estimate(boundary_visible=False,reason='cropped_outline')),
                              json.dumps(estimate(boundary_visible=False,reason='obscured_outline'))])
    monkeypatch.setattr(service,'fetch_satellite_image',fetch)
    monkeypatch.setattr(service,'_boundary_vision_request',vision)
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['status'] == 'uncertain' and 'boundary' not in result
    assert result['reason'] == 'obscured_outline'
    assert result['attempts'] == [{'zoom':19,'reason':'cropped_outline'}, {'zoom':18,'reason':'obscured_outline'}]
    assert vision.call_count == fetch.call_count == 2


@pytest.mark.parametrize('failure',['network','allowance','incomplete'])
def test_non_geometric_vision_failure_never_starts_wider_retry(monkeypatch,failure):
    from fastapi import HTTPException
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    fetch = Mock(return_value=PNG)
    error = RuntimeError('private transport details') if failure == 'network' else HTTPException(429,'allowance')
    vision = Mock(return_value=None) if failure == 'incomplete' else Mock(side_effect=error)
    monkeypatch.setattr(service,'fetch_satellite_image',fetch)
    monkeypatch.setattr(service,'_boundary_vision_request',vision)
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['status'] == 'unavailable'
    assert fetch.call_count == vision.call_count == 1
    assert 'private transport details' not in json.dumps(result)


@pytest.mark.parametrize('old_version',[None,2])
def test_old_negative_cache_retries_new_analysis_once_then_retains_refusal_diagnostics(setup_scope,monkeypatch,old_version):
    from src.services.database import DatabaseService
    from src.services.departure_setup import ensure_boundary
    uid = 'jarvis_local_user'
    old = {'version':1,'source':'satellite_estimate','status':'uncertain',
           'estimated_at':datetime.now(timezone.utc).isoformat()}
    if old_version is not None:
        old['analysis_version'] = old_version
    setup_scope.seed({'records':{'places':[place_row(boundary_json=old)]}})
    db = DatabaseService()
    attempts = [{'zoom':19,'reason':'cropped_outline'},{'zoom':18,'reason':'obscured_outline'}]
    provider = Mock(return_value={'status':'uncertain','reason':'obscured_outline',
        'description':'Complete outline is not visible at either zoom.','attempts':attempts})
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    assert provider.call_count == 1
    stored = json.loads(db.get_place(uid,'home')['boundary_json'])
    assert stored['analysis_version'] == 3
    assert stored['status'] == 'uncertain' and stored['reason'] == 'obscured_outline'
    assert stored['attempts'] == attempts
    assert 'either zoom' in stored['description']
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    assert provider.call_count == 1


def test_unavailable_analysis_retains_safe_reason_and_versioned_retry_cache(setup_scope,monkeypatch):
    from src.services.database import DatabaseService
    from src.services.departure_setup import ensure_boundary
    uid = 'jarvis_local_user'
    setup_scope.seed({'records':{'places':[place_row()]}})
    db = DatabaseService()
    provider = Mock(return_value={'status':'unavailable','reason':'vision_did_not_complete',
                                  'description':'Analysis did not complete.'})
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    stored = json.loads(db.get_place(uid,'home')['boundary_json'])
    assert stored['status'] == 'unavailable' and stored['analysis_version'] == 3
    assert stored['reason'] == 'vision_did_not_complete'
    assert ensure_boundary(db,uid,db.get_place(uid,'home')) is None
    assert provider.call_count == 1


def mock_provider_response(monkeypatch, *, status=200, choice=None, choices=None):
    from src.api import rate_limiter
    guard = Mock()
    guard.check_and_reserve_tokens.return_value = ('day','reservation')
    monkeypatch.setattr(rate_limiter,'TokenBudgetGuard',lambda:guard)
    data = {'usage':{'prompt_tokens':1200,'completion_tokens':8192,'cost':0.005},
            'choices': choices if choices is not None else [choice or {'finish_reason':'stop','message':{'content':'{}'}}]}
    response = Mock(status_code=status)
    response.json.return_value = data
    # A provider body could include credentials or image input; diagnostics must never copy it.
    response.text = 'private-provider-input-and-key'
    post = Mock(return_value=response)
    monkeypatch.setattr(satellite.httpx,'post',post)
    return guard,post


@pytest.mark.parametrize('status',[400,401,402,429,500,503])
def test_provider_http_failures_are_sanitized_and_do_not_retry(monkeypatch,status):
    guard,post = mock_provider_response(monkeypatch,status=status)
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    fetch = Mock(return_value=PNG)
    monkeypatch.setattr(service,'fetch_satellite_image',fetch)
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['status'] == 'unavailable'
    assert result['reason'] == 'provider_http_'+str(status)
    assert result['attempts'] == [{'zoom':19,'reason':'provider_http_'+str(status)}]
    assert fetch.call_count == post.call_count == 1
    assert 'private-provider-input-and-key' not in json.dumps(result)
    guard.record_llm_usage.assert_not_called()


@pytest.mark.parametrize('finish,reason',[
    ('length','vision_finish_length'), ('content_filter','vision_finish_content_filter'),
    ('tool_calls','vision_finish_tool_calls'),('error','vision_finish_error'),
    ('provider-private-string','vision_finish_unknown'),(None,'vision_finish_unknown')])
def test_incomplete_finish_reasons_are_actionable_and_actual_usage_is_settled(monkeypatch,finish,reason):
    guard,post = mock_provider_response(monkeypatch,choice={'finish_reason':finish,'message':{'content':''}})
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    monkeypatch.setattr(service,'fetch_satellite_image',Mock(return_value=PNG))
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['reason'] == reason and result['status'] == 'unavailable'
    assert 'provider-private-string' not in json.dumps(result)
    assert post.call_count == 1
    assert guard.record_llm_usage.call_args.args == ('u',1200,8192)
    assert guard.record_llm_usage.call_args.kwargs['reservation'] == ('day','reservation')


@pytest.mark.parametrize('content',[None,'','   ',[],{'data':'not-text'}])
def test_empty_or_non_text_model_content_has_distinct_reason(monkeypatch,content):
    guard,post = mock_provider_response(monkeypatch,choice={'finish_reason':'stop','message':{'content':content}})
    with pytest.raises(satellite.BoundaryVisionUnavailable,match='vision_missing_content'):
        satellite.SatelliteVisionService()._boundary_vision_request(PNG,'inspect','u')
    assert guard.record_llm_usage.call_count == post.call_count == 1


def test_missing_choice_is_distinct_from_finish_length(monkeypatch):
    guard,post = mock_provider_response(monkeypatch,choices=[])
    with pytest.raises(satellite.BoundaryVisionUnavailable,match='vision_missing_choice'):
        satellite.SatelliteVisionService()._boundary_vision_request(PNG,'inspect','u')
    assert guard.record_llm_usage.call_count == 1


def test_transport_timeout_is_sanitized_and_does_not_start_wider_retry(monkeypatch):
    import httpx
    mock_provider_response(monkeypatch)
    post = Mock(side_effect=httpx.ReadTimeout('private timeout URL with key'))
    monkeypatch.setattr(satellite.httpx,'post',post)
    service = satellite.SatelliteVisionService()
    monkeypatch.setattr(satellite,'OPENROUTER_API_KEY','test-provider-key')
    monkeypatch.setattr(service,'fetch_satellite_image',Mock(return_value=PNG))
    result = service.estimate_boundary(LAT,LON,'Home','u')
    assert result['reason'] == 'vision_transport_timeout' and post.call_count == 1
    assert 'private timeout URL' not in json.dumps(result)


def test_setup_ignores_deleted_and_malformed_policies(setup_scope,monkeypatch):
    from src.api.routers.mobile_compute import departure_boundaries
    bad = ['[]','null','42','{"trigger":"exit","origin":[]}',
           '{"trigger":"exit","origin":{"name":null}}','broken json']
    setup_scope.seed({'records':{'places':[place_row()], 'reminders':[
        reminder_row('bad-'+str(i),dynamic_policy=value) for i,value in enumerate(bad)] + [
        reminder_row('deleted',deleted_at='2026-02-01T00:00:00+00:00')]}})
    provider = Mock()
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',provider)
    result = departure_boundaries('jarvis_local_user')
    assert result['refreshed'] == result['updated_reminders'] == []
    provider.assert_not_called()
    assert setup_scope.changes()['records']['reminders'] == []


def test_foreground_setup_returns_phone_commit_deltas_without_alerts(monkeypatch):
    from src.api.mobile_middleware import MobileStateMiddleware
    from src.api.routers.mobile_compute import router
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(MobileStateMiddleware)
    boundary = satellite.parse_boundary_estimate(json.dumps(estimate()),LAT,LON)
    monkeypatch.setattr(satellite.SatelliteVisionService,'estimate_boundary',
                        lambda *a,**k:{'status':'ok','boundary':boundary})
    with TestClient(app) as client:
        response = client.post('/mobile/departure-boundaries',json={'_mobile_state':{
            'records':{'places':[place_row()], 'reminders':[reminder_row()]}}})
    assert response.status_code == 200
    data = response.json()
    assert data['updated_reminders'] == ['leave-home']
    changes = data['_mobile_changes']
    assert changes['notifications'] == []
    place, = changes['records']['places']
    reminder, = changes['records']['reminders']
    assert json.loads(place['boundary_json']) == boundary
    assert place['alias'] == 'My flat' and place['phone_revision'] == 'phone-17'
    assert reminder['one_shot'] is False and reminder['delivery_mode'] == 'in_app_call'
    assert reminder['created_at'] == reminder_row()['created_at']
    assert reminder['due_at'] == reminder_row()['due_at']
    assert reminder['last_fired_at'] == reminder_row()['last_fired_at']
    assert reminder['status'] == 'ACTIVE'
