"""ElevenLabs API client (https://elevenlabs.io/docs/api-reference) — voices,
models and the account's credit balance, and four generations: speech (with
or without per-character timings), music, sound effects and voice design.

Authenticated by the **`xi-api-key`** header. Host `https://api.elevenlabs.io`;
every path carries its version (`/v1/…`, `/v2/voices`). Reads return the parsed
JSON unchanged. Generations return the audio as BYTES (`content`) with its
`content_type`, never base64: what to do with a file (store it, link it, play
it) is the caller's business.

## Protocol facts that shape a caller

- **Every generation spends the account's credits** (characters for speech,
  per second for music and sound). A POST is never retried here: there is no
  idempotency key, a replay would bill twice.
- **A key may be restricted** to some endpoints when it is created. A
  restricted key without `user_read` cannot read the balance (`probe`), and one
  without `voices_read` cannot list voices, even when it can generate.
- **Out of credits answers 401**, not 402, with `detail.status` set to
  `quota_exceeded`; a refused key answers 401 with `invalid_api_key` or
  `missing_permissions`. Read `detail.status` before blaming the key.
- **`output_format`** is `<codec>_<sample rate>[_<bitrate>]`: `mp3_44100_128`
  (the default here), `pcm_24000`, `opus_48000_64`, `ulaw_8000`… Some formats
  (`mp3_44100_192`, `pcm_44100`) need a paid plan and answer 403 otherwise.
- **Speech with timings** (`timestamps=True`) answers JSON: the audio in base64
  plus `alignment` (each character with its start and end, in seconds) and
  `normalized_alignment` (the same after the text was normalised, e.g. "3" →
  "three"). The client decodes the audio; the alignments are returned as is.
- **`previous_text` / `next_text`** make a line sound continuous with its
  neighbours when a script is read line by line; **`seed`** (0 to 4294967295)
  makes a take reproducible as far as the model allows.
- **Music** takes either a free `prompt` (with `music_length_ms`, 3 s to 5 min)
  or a `composition_plan` (sections with their own durations and positive and
  negative styles), never both. A prompt naming an artist or a copyrighted work
  is refused with 400 `bad_prompt`.
- **Voice design** returns up to three previews of a voice described in words,
  each with a `generated_voice_id`. A preview is not a voice of the account:
  saving one takes a voice slot and is not done here.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional

import requests

from ..common import raise_for_upstream
from ..common.credentials import require

BASE_URL = "https://api.elevenlabs.io"

# (connect, read). A generation is long: a few seconds for a line, up to
# minutes for five minutes of music. Reads are short.
_READ_TIMEOUT = (10, 60)
_SPEECH_TIMEOUT = (10, 180)
_MUSIC_TIMEOUT = (10, 600)

DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"

_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_OUTPUT_FORMAT = re.compile(r"^(mp3|pcm|ulaw|alaw|opus|wav)_\d{4,5}(_\d{2,3})?$")

# The container each codec comes back in, and the extension a file of it takes.
_CODECS = {
    "mp3": ("audio/mpeg", "mp3"),
    "opus": ("audio/ogg", "opus"),
    "wav": ("audio/wav", "wav"),
    "pcm": ("audio/L16", "pcm"),
    "ulaw": ("audio/basic", "ulaw"),
    "alaw": ("audio/basic", "alaw"),
}

MIN_SEED, MAX_SEED = 0, 4294967295
MIN_MUSIC_MS, MAX_MUSIC_MS = 3000, 300000
MIN_SOUND_S, MAX_SOUND_S = 0.5, 30.0
MAX_PAGE_SIZE = 100


def audio_type(output_format: str) -> Dict[str, str]:
    """`{"content_type", "extension"}` of an `output_format`, e.g. `mp3_44100_128`."""
    codec = output_format.split("_", 1)[0]
    content_type, extension = _CODECS[codec]
    return {"content_type": content_type, "extension": extension}


def _object_id(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not _ID.match(text):
        raise ValueError(f"`{name}` must be an ElevenLabs id (letters, digits, - and _).")
    return text


def _format(output_format: Optional[str]) -> str:
    value = (output_format or DEFAULT_OUTPUT_FORMAT).strip()
    if not _OUTPUT_FORMAT.match(value):
        raise ValueError(
            f"`output_format` unreadable: {value!r}. Expected <codec>_<sample rate>"
            "[_<bitrate>], e.g. mp3_44100_128, pcm_24000, opus_48000_64.")
    return value


def _seed(seed: Optional[int]) -> Optional[int]:
    if seed is None:
        return None
    if isinstance(seed, bool) or not isinstance(seed, int) or not MIN_SEED <= seed <= MAX_SEED:
        raise ValueError(f"`seed` must be an integer from {MIN_SEED} to {MAX_SEED}.")
    return seed


def _text(value: Optional[str], name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"`{name}` must be a non-empty text.")
    return value


def _clean(body: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the arguments left unset, so the API applies its own defaults."""
    return {k: v for k, v in body.items() if v is not None}


class ElevenLabsClient:
    """One method per endpoint. Reads return JSON; generations return
    `{"content": bytes, "content_type", "extension", "output_format", …}`."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = require(api_key, "ELEVENLABS_API_KEY")
        self.session = requests.Session()
        self.session.headers.update({"xi-api-key": self.api_key, "Accept": "application/json"})

    # --- transport ---------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        resp = self.session.request("GET", f"{BASE_URL}{path}", params=_clean(params or {}) or None,
                                    timeout=_READ_TIMEOUT)
        raise_for_upstream(resp, service="elevenlabs")
        return resp.json() if resp.content else {}

    def _post(self, path: str, body: Dict[str, Any], *, output_format: str,
              timeout: tuple) -> Any:
        resp = self.session.request("POST", f"{BASE_URL}{path}", params={"output_format": output_format},
                                    json=_clean(body), timeout=timeout)
        raise_for_upstream(resp, service="elevenlabs")
        return resp

    @staticmethod
    def _audio(resp: Any, output_format: str) -> Dict[str, Any]:
        headers = getattr(resp, "headers", None) or {}
        out: Dict[str, Any] = {"content": resp.content, "output_format": output_format,
                               **audio_type(output_format)}
        if headers.get("request-id"):
            out["request_id"] = headers["request-id"]
        if headers.get("x-character-count"):
            out["character_count"] = int(headers["x-character-count"])
        return out

    # --- account -----------------------------------------------------------

    def probe(self) -> Any:
        """Cheapest authenticated call: the subscription (needs `user_read`)."""
        return self.get_subscription()

    def get_subscription(self) -> Any:
        """Plan, credits used and allowed this period, and when they reset."""
        return self._get("/v1/user/subscription")

    # --- voices and models -------------------------------------------------

    def list_voices(self, *, search: Optional[str] = None, voice_type: Optional[str] = None,
                    category: Optional[str] = None, page_size: Optional[int] = None,
                    next_page_token: Optional[str] = None) -> Any:
        """The voices this account can use: its own and the default ones.
        `voice_type`: personal, community, default, workspace, non-default.
        `category`: premade, cloned, generated, professional."""
        if page_size is not None and not 1 <= int(page_size) <= MAX_PAGE_SIZE:
            raise ValueError(f"`page_size` must be from 1 to {MAX_PAGE_SIZE}.")
        return self._get("/v2/voices", {"search": search, "voice_type": voice_type,
                                        "category": category, "page_size": page_size,
                                        "next_page_token": next_page_token})

    def get_voice(self, voice_id: str) -> Any:
        """One voice: name, labels, description, preview URL, settings."""
        return self._get(f"/v1/voices/{_object_id(voice_id, 'voice_id')}")

    def list_models(self) -> Any:
        """The models, with what each can do (speech, languages, limits)."""
        return self._get("/v1/models")

    # --- generations -------------------------------------------------------

    def create_speech(self, voice_id: str, text: str, *, model_id: Optional[str] = None,
                      voice_settings: Optional[Dict[str, Any]] = None,
                      previous_text: Optional[str] = None, next_text: Optional[str] = None,
                      seed: Optional[int] = None, language_code: Optional[str] = None,
                      output_format: Optional[str] = None, timestamps: bool = False) -> Dict[str, Any]:
        """Text to speech in one voice. With `timestamps`, also each
        character's start and end (`alignment`, `normalized_alignment`)."""
        fmt = _format(output_format)
        path = f"/v1/text-to-speech/{_object_id(voice_id, 'voice_id')}"
        body = {"text": _text(text, "text"), "model_id": model_id, "voice_settings": voice_settings,
                "previous_text": previous_text, "next_text": next_text, "seed": _seed(seed),
                "language_code": language_code}
        if not timestamps:
            return self._audio(self._post(path, body, output_format=fmt, timeout=_SPEECH_TIMEOUT), fmt)
        resp = self._post(f"{path}/with-timestamps", body, output_format=fmt, timeout=_SPEECH_TIMEOUT)
        data = resp.json()
        out = self._audio(resp, fmt)
        out["content"] = base64.b64decode(data.get("audio_base64") or "")
        out["alignment"] = data.get("alignment")
        out["normalized_alignment"] = data.get("normalized_alignment")
        return out

    def create_music(self, *, prompt: Optional[str] = None,
                     composition_plan: Optional[Dict[str, Any]] = None,
                     music_length_ms: Optional[int] = None, model_id: Optional[str] = None,
                     seed: Optional[int] = None, force_instrumental: Optional[bool] = None,
                     respect_sections_durations: Optional[bool] = None,
                     output_format: Optional[str] = None) -> Dict[str, Any]:
        """A track from a prompt, or from a composition plan (sections with
        their durations and styles). Exactly one of the two."""
        if (prompt is None) == (composition_plan is None):
            raise ValueError("Give either `prompt` or `composition_plan`, not both and not neither.")
        if prompt is not None:
            _text(prompt, "prompt")
        if composition_plan is not None and music_length_ms is not None:
            raise ValueError("`music_length_ms` goes with `prompt`; a composition plan sets "
                             "its length through its sections' durations.")
        if music_length_ms is not None and not MIN_MUSIC_MS <= int(music_length_ms) <= MAX_MUSIC_MS:
            raise ValueError(f"`music_length_ms` must be from {MIN_MUSIC_MS} to {MAX_MUSIC_MS}.")
        fmt = _format(output_format)
        body = {"prompt": prompt, "composition_plan": composition_plan,
                "music_length_ms": music_length_ms, "model_id": model_id, "seed": _seed(seed),
                "force_instrumental": force_instrumental,
                "respect_sections_durations": respect_sections_durations}
        return self._audio(self._post("/v1/music", body, output_format=fmt, timeout=_MUSIC_TIMEOUT), fmt)

    def create_sound(self, text: str, *, duration_seconds: Optional[float] = None,
                     prompt_influence: Optional[float] = None, loop: Optional[bool] = None,
                     model_id: Optional[str] = None,
                     output_format: Optional[str] = None) -> Dict[str, Any]:
        """A sound effect from a description; the length is chosen by the
        model unless `duration_seconds` (0.5 to 30) is given."""
        if duration_seconds is not None and not MIN_SOUND_S <= float(duration_seconds) <= MAX_SOUND_S:
            raise ValueError(f"`duration_seconds` must be from {MIN_SOUND_S} to {MAX_SOUND_S}.")
        if prompt_influence is not None and not 0 <= float(prompt_influence) <= 1:
            raise ValueError("`prompt_influence` must be from 0 to 1.")
        fmt = _format(output_format)
        body = {"text": _text(text, "text"), "duration_seconds": duration_seconds,
                "prompt_influence": prompt_influence, "loop": loop, "model_id": model_id}
        return self._audio(self._post("/v1/sound-generation", body, output_format=fmt,
                                      timeout=_SPEECH_TIMEOUT), fmt)

    def create_voice_design(self, voice_description: str, *, text: Optional[str] = None,
                            auto_generate_text: Optional[bool] = None,
                            model_id: Optional[str] = None, seed: Optional[int] = None,
                            output_format: Optional[str] = None) -> Dict[str, Any]:
        """Previews of a voice described in words, each reading `text` (or a
        text the model writes when `auto_generate_text`). Returns
        `{"text", "previews": [{"generated_voice_id", "duration_secs",
        "language", "content", "content_type", "extension"}]}`."""
        fmt = _format(output_format)
        body = {"voice_description": _text(voice_description, "voice_description"),
                "text": text, "auto_generate_text": auto_generate_text, "model_id": model_id,
                "seed": _seed(seed)}
        data = self._post("/v1/text-to-voice/design", body, output_format=fmt,
                          timeout=_SPEECH_TIMEOUT).json()
        previews: List[Dict[str, Any]] = []
        for p in data.get("previews") or []:
            previews.append({
                "generated_voice_id": p.get("generated_voice_id"),
                "duration_secs": p.get("duration_secs"),
                "language": p.get("language"),
                "content": base64.b64decode(p.get("audio_base_64") or ""),
                "output_format": fmt,
                **audio_type(fmt),
            })
        return {"text": data.get("text"), "previews": previews}
