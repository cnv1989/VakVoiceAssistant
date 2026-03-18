"""
Real-time noise suppressor for Twilio mulaw audio using SpeexDSP.

Pipeline per call:
  mulaw bytes → linear16 → speex preprocess (denoise) → mulaw bytes → Deepgram
"""
import audioop
import logging

logger = logging.getLogger(__name__)

# Frame size for 8kHz audio: 160 samples = 20ms (matches Twilio's mulaw frame size)
_FRAME_SAMPLES = 160
_SAMPLE_RATE = 8000


def _try_import_speex():
    try:
        from speexdsp.preprocess import SpeexPreprocess
        return SpeexPreprocess
    except ImportError:
        logger.warning("speexdsp not available — noise suppression disabled")
        return None


_SpeexPreprocess = _try_import_speex()


class NoiseSuppressor:
    """Per-call noise suppressor. Create one instance per Twilio session."""

    def __init__(self):
        self._pp = None
        if _SpeexPreprocess is not None:
            try:
                self._pp = _SpeexPreprocess(_FRAME_SAMPLES, _SAMPLE_RATE)
                self._pp.ctl_set("SPEEX_PREPROCESS_SET_DENOISE", 1)
                self._pp.ctl_set("SPEEX_PREPROCESS_SET_AGC", 0)
                self._pp.ctl_set("SPEEX_PREPROCESS_SET_VAD", 0)
                self._pp.ctl_set("SPEEX_PREPROCESS_SET_DEREVERB", 1)
                logger.info("NoiseSuppressor: speexdsp initialized (8kHz, %d samples/frame)", _FRAME_SAMPLES)
            except Exception as e:
                logger.warning("NoiseSuppressor: failed to init speexdsp: %s", e)
                self._pp = None

    @property
    def enabled(self) -> bool:
        return self._pp is not None

    def process(self, mulaw_bytes: bytes) -> bytes:
        """Suppress noise in a mulaw frame. Returns mulaw bytes (same length)."""
        if self._pp is None:
            return mulaw_bytes
        try:
            # mulaw → linear16
            pcm = audioop.ulaw2lin(mulaw_bytes, 2)
            # denoise
            pcm_out = self._pp.process(pcm)
            # linear16 → mulaw
            return audioop.lin2ulaw(pcm_out, 2)
        except Exception as e:
            logger.debug("NoiseSuppressor.process error: %s", e)
            return mulaw_bytes
