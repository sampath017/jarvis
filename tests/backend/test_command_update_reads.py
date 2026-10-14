import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock

from src.services.command_updates import command_updates
from src.services.command_run_store import CommandRunStore
from src.api.routers.commands import _command_events


class WatchedStore:
    public = staticmethod(CommandRunStore.public)

    def __init__(self):
        self.data = dict(request_id='r', status='running', started_at=datetime.now(timezone.utc),
                         message='Working', steps=[], sequence=0, response=None)
        self.reads = 0
        self.watch = Mock()

    def subscribe(self, uid, request_id, callback):
        self.callback = callback
        callback(dict(self.data))
        return self.watch

    def get(self, uid, request_id):
        self.reads += 1
        return dict(self.data)


def test_idle_heartbeats_do_not_poll_and_teardown_unsubscribes():
    async def run():
        store = WatchedStore()
        stream = command_updates(store, 'u', 'r', heartbeat_seconds=.002, recovery_seconds=10)
        for _ in range(20):
            assert (await anext(stream))['message'] == 'Working'
        assert store.reads == 0
        await stream.aclose()
        store.watch.unsubscribe.assert_called_once()
    asyncio.run(run())


def test_changed_action_and_completion_arrive_without_waiting_for_poll():
    async def run():
        store = WatchedStore()
        stream = _command_events(store, 'u', 'r')
        assert 'event: progress' in await anext(stream)
        store.callback({**store.data, 'calendar_action': {'action_id': 'a'}, 'calendar_result': None})
        assert 'event: calendar_action' in await asyncio.wait_for(anext(stream), .5)
        store.callback({**store.data, 'status': 'complete', 'response': {'status': 'ok', 'message': 'Done'}})
        assert 'event: result' in await asyncio.wait_for(anext(stream), .5)
        try:
            await anext(stream)
        except StopAsyncIteration:
            pass
        store.watch.unsubscribe.assert_called_once()
        assert store.reads == 0
    asyncio.run(run())


def test_silent_transport_has_sparse_recovery_reads():
    async def run():
        store = WatchedStore()
        stream = command_updates(store, 'u', 'r', heartbeat_seconds=.002, recovery_seconds=0)
        await anext(stream)
        store.data['status'] = 'complete'
        assert (await anext(stream))['status'] == 'complete'
        assert store.reads == 1
        await stream.aclose()
    asyncio.run(run())
