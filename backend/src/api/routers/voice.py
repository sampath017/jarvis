"""Transient command audio transcription. Never persist audio or provider credentials."""
import base64
import binascii
import io
import wave
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ...settings import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from ..auth import get_current_user
from ..rate_limiter import TokenBudgetGuard

router = APIRouter(prefix='/voice', tags=['voice'])
MODEL = 'openai/whisper-large-v3-turbo'


class AudioCommand(BaseModel):
    audio: str = Field(min_length=60, max_length=2_600_000)


def validate_audio(encoded: str) -> float:
    try:
        raw = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(raw), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, 16000):
                raise ValueError('Expected mono 16kHz PCM16')
            frames = audio.getnframes()
            if not 3200 <= frames <= 960000 or len(audio.readframes(frames)) != frames * 2:
                raise ValueError('Invalid or truncated command audio')
            return frames / 16000
    except (ValueError, binascii.Error, wave.Error, EOFError) as exc:
        raise HTTPException(422, 'Expected 0.2–60 seconds of mono 16kHz PCM16 WAV audio') from exc


@router.post('/transcribe')
async def transcribe(body: AudioCommand, uid: Annotated[str, Depends(get_current_user)]):
    duration = validate_audio(body.audio)
    if not OPENROUTER_API_KEY:
        raise HTTPException(503, 'Speech transcription is not configured')
    guard = TokenBudgetGuard()
    # Reserve at the highest currently listed provider price; settle reported cost.
    estimate = duration * 0.000011
    hold = await run_in_threadpool(guard.check_and_reserve_tokens, uid, 0,
                                  model=MODEL, extra_cost_nanos=int(estimate * 1e9) + 1)
    try:
        async with httpx.AsyncClient(timeout=65) as client:
            response = await client.post(OPENROUTER_BASE_URL + '/audio/transcriptions',
                headers={'Authorization': 'Bearer ' + OPENROUTER_API_KEY},
                json={'model': MODEL, 'input_audio': {'data': body.audio, 'format': 'wav'}})
        if response.status_code != 200:
            raise HTTPException(502, 'Speech provider could not transcribe this command. Please try again.')
        data = response.json()
        usage = data.get('usage') or {}
        await run_in_threadpool(guard.record_llm_usage, uid, 0, 0, reservation=hold,
                                model=MODEL, cost_usd=usage.get('cost', estimate))
        text = data.get('text')
        if not isinstance(text, str) or len(text) > 2000:
            raise HTTPException(502, 'Speech provider returned an invalid transcript')
        return {'text': text.strip(), 'model': MODEL}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise HTTPException(502, 'Speech transcription was interrupted. Please try again.') from exc
