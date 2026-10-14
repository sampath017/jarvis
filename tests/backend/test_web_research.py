import json
from datetime import datetime, timezone
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from src.cloud.agent_tools import build_agent_tools
from src.graph.nodes.agent_tools import AgentToolsNode
from src.services import web_research as web
from src.services.database import DatabaseService
from src.services.places_client import PlacesClient


def response_data(**overrides):
    return {**{
        'choices': [{'finish_reason': 'stop', 'message': {'content': 'Advertised from INR 5,000 per night; taxes extra.',
            'annotations': [{'type': 'url_citation', 'url_citation': {
                'url': 'https://example.com/resort/rates', 'title': 'Resort rates', 'content': 'From INR 5,000 per night, excluding taxes.',
            }}]}}],
        'usage': {'prompt_tokens': 1200, 'completion_tokens': 200, 'cost': 0.0018,
                  'server_tool_use': {'web_search_requests': 1}},
    }, **overrides}


def researcher(monkeypatch, payload=None, status=200):
    monkeypatch.setattr(web, 'OPENROUTER_API_KEY', 'test-key')
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(status, json=payload if payload is not None else response_data())
    guard = Mock()
    guard.check_and_reserve_tokens.return_value = ('day', 'reservation')
    return web.WebResearch('u', httpx.Client(transport=httpx.MockTransport(handle)), guard), guard, requests


def test_search_returns_sources_and_reserves_search_fee_before_billing(monkeypatch):
    service, guard, requests = researcher(monkeypatch)
    result = service.search('resort prices in Test Area')
    assert result['status'] == 'ok'
    assert result['sources'][0]['url'] == 'https://example.com/resort/rates'
    assert 'excluding taxes' in result['sources'][0]['excerpt']
    assert requests[0]['tools'][0]['type'] == 'openrouter:web_search'
    assert requests[0]['tools'][0]['parameters']['max_uses'] == 1
    assert requests[0]['max_tool_calls'] == 1
    assert guard.check_and_reserve_tokens.call_args.kwargs['extra_cost_nanos'] == 1_000_000
    assert guard.record_llm_usage.call_args.kwargs['reservation'] == ('day', 'reservation')
    assert guard.record_llm_usage.call_args.kwargs['cost_usd'] == 0.0018
    assert len(requests[0]['messages']) == 2  # No conversation or personal records.


def test_fetch_accepts_arbitrary_public_domains_without_allowlist(monkeypatch):
    data = response_data(choices=[{'finish_reason': 'stop', 'message': {
        'content': json.dumps({'status': 'ok', 'title': 'Offers', 'content': 'Advertised rates from INR 5,000 per night.'}),
    }}], usage={'prompt_tokens': 300, 'completion_tokens': 80, 'cost': 0.0001,
                'server_tool_use_details': {'tool_calls_executed': 1}})
    service, guard, requests = researcher(monkeypatch, data)
    result = service.read('https://unfamiliar-resort.example/offers')
    assert result['status'] == 'ok'
    assert result['sources'][0]['url'] == 'https://unfamiliar-resort.example/offers'
    assert requests[0]['tools'][0] == {'type': 'openrouter:web_fetch', 'parameters': {
        'engine': 'openrouter', 'max_content_tokens': 5000, 'max_uses': 1,
    }}
    assert 'https://unfamiliar-resort.example/offers' in requests[0]['messages'][-1]['content']
    assert guard.check_and_reserve_tokens.call_args.kwargs['extra_cost_nanos'] == 0


@pytest.mark.parametrize('status,executed', [('unavailable', 1), ('ok', 0)])
def test_failed_fetch_or_missing_tool_execution_is_not_verified(monkeypatch, status, executed):
    data = response_data(choices=[{'finish_reason': 'stop', 'message': {
        'content': json.dumps({'status': status, 'content': 'HTTP 403 or unverified text'}),
    }}], usage={'server_tool_use_details': {'tool_calls_executed': executed}})
    service, _, _ = researcher(monkeypatch, data)
    result = service.read('https://example.com/blocked')
    assert result['status'] == 'unavailable'
    assert 'sources' not in result


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost/', 'http://127.0.0.1/',
    'http://169.254.169.254/', 'http://10.0.0.1/', 'https://metadata.google.internal/',
    'https://user:password@example.com/', 'https://[::1]/', 'https://example.com:bad/'])
def test_nonpublic_and_invalid_urls_do_not_start_paid_requests(monkeypatch, url):
    service, guard, requests = researcher(monkeypatch)
    assert service.read(url)['status'] == 'invalid_arguments'
    assert not requests
    guard.check_and_reserve_tokens.assert_not_called()


@pytest.mark.parametrize('payload', [
    response_data(choices=[]),
    response_data(choices=[{'finish_reason': 'stop', 'message': {'content': 'Invented price'}}]),
    response_data(choices=[{'finish_reason': 'length', 'message': response_data()['choices'][0]['message']}]),
])
def test_missing_sources_or_incomplete_answers_are_not_web_evidence(monkeypatch, payload):
    service, guard, _ = researcher(monkeypatch, payload)
    result = service.search('resort prices')
    assert result['status'] == 'unavailable'
    assert 'sources' not in result
    guard.record_llm_usage.assert_called_once()


def test_provider_error_is_not_retried_or_reported_as_a_checked_price(monkeypatch):
    service, guard, requests = researcher(monkeypatch, {'error': 'blocked'}, status=403)
    result = service.read('https://example.com/blocked')
    assert result['status'] == 'unavailable'
    assert len(requests) == 1
    guard.record_llm_usage.assert_not_called()  # Uncertain charge retains its hold.


def test_budget_rejection_prevents_web_request(monkeypatch):
    service, guard, requests = researcher(monkeypatch)
    guard.check_and_reserve_tokens.side_effect = HTTPException(429, 'Daily budget exhausted')
    with pytest.raises(HTTPException):
        service.search('resorts')
    assert not requests


def test_web_tool_answers_general_questions_without_phone_records(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'web.db')
    monkeypatch.setattr(db, 'get_latest_gps', Mock(side_effect=AssertionError('A general question needs no GPS')))
    search = Mock(return_value={'status': 'ok', 'sources': [{'url': 'https://example.com'}], 'content': 'Verified answer'})
    monkeypatch.setattr(web.WebResearch, 'search', search)
    tools = {tool.name: tool for tool in build_agent_tools(db, 'u')}
    assert {'search_web', 'read_webpage'} <= tools.keys()
    result = AgentToolsNode(db)({'uid': 'u', 'raw_request': {'text': 'What is HTTP?'}, 'agent_messages': [
        AIMessage(content='', tool_calls=[{'name': 'search_web', 'args': {'query': 'HTTP definition'}, 'id': 'web'}]),
    ]})
    assert json.loads(result['agent_messages'][-1].content)['status'] == 'ok'
    assert not result['changed_records']
    search.assert_called_once_with('HTTP definition')


def test_places_keyword_search_uses_text_endpoint_and_filters_outside_radius(monkeypatch):
    PlacesClient.reset_budgets()
    post = Mock(return_value=httpx.Response(200, request=httpx.Request('POST', 'https://places.googleapis.com'), json={
        'places': [
            {'id': 'resort', 'displayName': {'text': 'Nearby Resort'}, 'primaryType': 'resort_hotel',
             'location': {'latitude': 12.81, 'longitude': 80.2}},
            {'id': 'distant', 'displayName': {'text': 'Distant Resort'},
             'location': {'latitude': 15.0, 'longitude': 80.2}},
        ]}))
    monkeypatch.setattr('src.services.places_client.httpx.post', post)
    result = PlacesClient('test-key').search_nearby(12.8, 80.2, 20000, uid='u', query='resorts')
    assert [place.name for place in result] == ['Nearby Resort']
    assert post.call_args.args[0].endswith('places:searchText')
    assert post.call_args.kwargs['json']['textQuery'] == 'resorts'
    assert post.call_args.kwargs['json']['locationBias']['circle']['radius'] == 20000


def test_nearby_tool_passes_keyword_and_rejects_stale_location(monkeypatch, tmp_path):
    db = DatabaseService(tmp_path / 'nearby.db')
    db.create_event_idempotent('u', 'fresh', {'activity': 'STILL', 'transition': 'LOCATION_REQUEST',
        'timestamp': datetime.now(timezone.utc).isoformat(), 'gps': {'latitude': 12.8, 'longitude': 80.2}})
    search = Mock(return_value=[])
    monkeypatch.setattr(PlacesClient, 'search_nearby', search)
    tools = {tool.name: tool for tool in build_agent_tools(db, 'u')}
    tools['search_nearby_places'].invoke({'query': 'resorts', 'radius_m': 20000})
    assert search.call_args.kwargs['query'] == 'resorts'
    assert search.call_args.kwargs['radius_m'] == 20000
    search.reset_mock()
    monkeypatch.setattr(db, 'get_latest_gps', lambda _: {'latitude': 12.8, 'longitude': 80.2, 'observed_at': '2020-01-01T00:00:00Z'})
    assert 'current location is unknown' in tools['search_nearby_places'].invoke({'query': 'resorts'})
    search.assert_not_called()
