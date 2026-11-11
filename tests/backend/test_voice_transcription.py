import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from src.api.routers import voice


def wav(rate=16000, frames=16000):
    out = io.BytesIO()
    with wave.open(out, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b'\x00\x00' * frames)
    return base64.b64encode(out.getvalue()).decode()


@pytest.mark.parametrize('audio', ['invalid base64!', base64.b64encode(b'not wav').decode(), wav(8000), wav(frames=100), wav(frames=960001)], ids=['base64', 'not-wav', 'rate', 'short', 'long'])
def test_rejects_invalid_audio_before_provider(audio):
    with pytest.raises(HTTPException) as error:
        voice.validate_audio(audio)
    assert error.value.status_code == 422


def test_accepts_phone_wav_and_rejects_truncation():
    encoded = wav()
    assert voice.validate_audio(encoded) == 1
    truncated = base64.b64encode(base64.b64decode(encoded)[:-100]).decode()
    with pytest.raises(HTTPException):
        voice.validate_audio(truncated)


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [200, 429, 500])
async def test_provider_contract_and_no_automatic_paid_retry(monkeypatch, code):
    guard = Mock()
    guard.check_and_reserve_tokens.return_value = ('day', 'hold')
    monkeypatch.setattr(voice, 'TokenBudgetGuard', lambda: guard)
    monkeypatch.setattr(voice, 'OPENROUTER_API_KEY', 'test-only')
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)
    monkeypatch.setattr(voice, 'run_in_threadpool', inline)
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return SimpleNamespace(status_code=code, json=lambda: {'text': ' Set a timer. ', 'usage': {'cost': 0.000003}})
    monkeypatch.setattr(voice.httpx, 'AsyncClient', Client)
    if code == 200:
        result = await voice.transcribe(voice.AudioCommand(audio=wav()), 'test-user')
        assert result == {'text': 'Set a timer.', 'model': voice.MODEL}
        assert guard.record_llm_usage.call_args.kwargs['cost_usd'] == 0.000003
    else:
        with pytest.raises(HTTPException) as error:
            await voice.transcribe(voice.AudioCommand(audio=wav()), 'test-user')
        assert error.value.status_code == 502
        guard.record_llm_usage.assert_not_called()
    assert len(calls) == 1
    assert calls[0][0].endswith('/audio/transcriptions')
    assert calls[0][1]['json']['model'] == 'openai/whisper-large-v3-turbo'
    assert calls[0][1]['json']['input_audio']['format'] == 'wav'
