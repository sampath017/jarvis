"""Change-driven command snapshots with bounded recovery and clean teardown."""
import asyncio
import time


async def command_updates(store, uid, request_id, *, heartbeat_seconds=10, recovery_seconds=30):
    subscribe = getattr(store, 'subscribe', None)
    if not callable(subscribe):
        # Local stores/test doubles without a RecordStore watch keep compatibility.
        while True:
            yield await asyncio.to_thread(store.get, uid, request_id)
            await asyncio.sleep(1)

    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=1)
    closed = False

    def deliver(data):
        if closed:
            return
        if queue.full():
            queue.get_nowait()
        queue.put_nowait(data)

    def received(data):
        try:
            loop.call_soon_threadsafe(deliver, data)
        except RuntimeError:
            pass  # The response's event loop has already closed.

    watch = await asyncio.to_thread(subscribe, uid, request_id, received)
    latest = None
    last_update = time.monotonic()
    try:
        while True:
            try:
                latest = await asyncio.wait_for(queue.get(), heartbeat_seconds)
                last_update = time.monotonic()
            except asyncio.TimeoutError:
                # Cached heartbeats keep SSE alive; sparse recovery reads cover
                # a silent transport failure without per-second database reads.
                if latest is None or time.monotonic() - last_update >= recovery_seconds:
                    latest = await asyncio.to_thread(store.get, uid, request_id)
                    last_update = time.monotonic()
            if latest is None:
                from fastapi import HTTPException
                raise HTTPException(404, 'Request not found')
            yield latest
    finally:
        closed = True
        await asyncio.to_thread(watch.unsubscribe)
