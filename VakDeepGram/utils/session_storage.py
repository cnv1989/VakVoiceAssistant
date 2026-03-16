"""
Async utility for uploading call transcripts and audio recordings to S3.

The transcript is a JSON document capturing all conversation turns
(ConversationText events from Deepgram). The audio recording captures
agent TTS audio chunks collected during the session.

S3 key layout (per call, under the configured prefix):
  {prefix}/{YYYY}/{MM}/{DD}/{call_id}/transcript.json
  {prefix}/{YYYY}/{MM}/{DD}/{call_id}/recording.wav   (if audio present)
"""
from __future__ import annotations

import json
import logging
import struct
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import aioboto3

logger = logging.getLogger("vak.session_storage")

_PCM_FORMAT = 1  # PCM linear


def _build_wav_header(
    num_samples: int,
    sample_rate: int,
    num_channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """Build a minimal 44-byte WAV header for raw PCM data."""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_samples * num_channels * bits_per_sample // 8
    chunk_size = data_size + 36  # 44 - 8

    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        _PCM_FORMAT,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )


def _pcm_chunks_to_wav(chunks: List[bytes], sample_rate: int) -> bytes:
    """Combine raw PCM16 chunks into a WAV file."""
    raw = b"".join(chunks)
    num_samples = len(raw) // 2  # 16-bit samples
    return _build_wav_header(num_samples, sample_rate) + raw


def _mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    """Convert 8-bit mu-law samples to 16-bit linear PCM."""
    out = bytearray(len(mulaw_bytes) * 2)
    for i, byte in enumerate(mulaw_bytes):
        byte = ~byte & 0xFF
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        value = ((mantissa << 1) + 33) << exponent
        value -= 33
        if sign:
            value = -value
        value = max(-32768, min(32767, value))
        struct.pack_into("<h", out, i * 2, value)
    return bytes(out)


async def upload_transcript(
    *,
    call_id: str,
    transcript_turns: List[Dict[str, Any]],
    bucket_name: str,
    aws_region: str = "us-west-2",
    key_prefix: str = "call-sessions",
    metadata: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Upload a JSON transcript to S3 and return the S3 key.

    Returns the S3 key on success, None on failure.
    Never raises — failures are logged but do not affect the call outcome.
    """
    if not bucket_name:
        return None
    if not transcript_turns:
        logger.debug("No transcript turns to upload for call %s", call_id)
        return None

    now = datetime.now(timezone.utc)
    s3_key = f"{key_prefix}/{now.strftime('%Y/%m/%d')}/{call_id}/transcript.json"

    transcript_doc: Dict[str, Any] = {
        "callId": call_id,
        "uploadedAt": now.isoformat(),
        "turns": transcript_turns,
    }
    body = json.dumps(transcript_doc, ensure_ascii=False, indent=2).encode("utf-8")

    try:
        async with aioboto3.Session().client("s3", region_name=aws_region) as s3:
            kwargs: Dict[str, Any] = {
                "Bucket": bucket_name,
                "Key": s3_key,
                "Body": body,
                "ContentType": "application/json",
            }
            if metadata:
                kwargs["Metadata"] = metadata
            await s3.put_object(**kwargs)
        logger.info(
            "Transcript uploaded: callId=%s bucket=%s key=%s turns=%d",
            call_id,
            bucket_name,
            s3_key,
            len(transcript_turns),
        )
        return s3_key
    except Exception as exc:
        logger.error(
            "Failed to upload transcript for call %s: %s",
            call_id,
            exc,
            exc_info=True,
        )
        return None


async def upload_recording(
    *,
    call_id: str,
    audio_chunks: List[bytes],
    sample_rate: int,
    is_mulaw: bool,
    bucket_name: str,
    aws_region: str = "us-west-2",
    key_prefix: str = "call-sessions",
    metadata: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Upload a WAV recording to S3 and return the S3 key.

    Accepts raw PCM16 or mu-law chunks. mu-law is decoded to PCM16 before
    building the WAV container.

    Returns the S3 key on success, None on failure.
    Never raises — failures are logged but do not affect the call outcome.
    """
    if not bucket_name:
        return None
    if not audio_chunks:
        logger.debug("No audio chunks to upload for call %s", call_id)
        return None

    now = datetime.now(timezone.utc)
    s3_key = f"{key_prefix}/{now.strftime('%Y/%m/%d')}/{call_id}/recording.wav"

    if is_mulaw:
        pcm_chunks = [_mulaw_to_pcm16(c) for c in audio_chunks]
        wav_sample_rate = 8000
    else:
        pcm_chunks = audio_chunks
        wav_sample_rate = sample_rate

    wav_data = _pcm_chunks_to_wav(pcm_chunks, wav_sample_rate)

    try:
        async with aioboto3.Session().client("s3", region_name=aws_region) as s3:
            kwargs: Dict[str, Any] = {
                "Bucket": bucket_name,
                "Key": s3_key,
                "Body": wav_data,
                "ContentType": "audio/wav",
            }
            if metadata:
                kwargs["Metadata"] = metadata
            await s3.put_object(**kwargs)
        duration_s = len(wav_data) / (wav_sample_rate * 2)
        logger.info(
            "Recording uploaded: callId=%s bucket=%s key=%s size=%dB (~%.1fs)",
            call_id,
            bucket_name,
            s3_key,
            len(wav_data),
            duration_s,
        )
        return s3_key
    except Exception as exc:
        logger.error(
            "Failed to upload recording for call %s: %s",
            call_id,
            exc,
            exc_info=True,
        )
        return None


async def generate_presigned_url(
    *,
    bucket_name: str,
    s3_key: str,
    aws_region: str = "us-west-2",
    expires_in: int = 3600,
) -> Optional[str]:
    """Generate a presigned GET URL for an S3 object.

    Returns the URL string, or None on failure.
    """
    if not bucket_name or not s3_key:
        return None
    try:
        async with aioboto3.Session().client("s3", region_name=aws_region) as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": s3_key},
                ExpiresIn=expires_in,
            )
        return url
    except Exception as exc:
        logger.error(
            "Failed to generate presigned URL for %s/%s: %s",
            bucket_name,
            s3_key,
            exc,
            exc_info=True,
        )
        return None
