"""Contract of the ElevenLabs client (`xi-api-key` header; JSON reads, audio
generations returned as bytes).

Mocks `requests.Session.request`: paths, query and body as in the vendor's API
reference, the key in a header and never in the query, timeouts, base64
decoding of the timed speech and the voice design previews, local refusals.
"""
from __future__ import annotations

import base64

import pytest

from oto.tools.common.credentials import MissingCredential
from oto.tools.common.errors import UpstreamHTTPError
from oto.tools.elevenlabs import client as el

AUDIO = b"ID3\x04fake-mp3"


class _Resp:
    def __init__(self, status_code=200, body=None, content=None, headers=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = content if content is not None else b"{}"
        self.text = str(self._body)
        self.headers = headers or {}

    def json(self):
        return self._body


@pytest.fixture()
def capture(monkeypatch):
    seen = {"responses": []}

    def fake_request(self, method, url, **kwargs):
        seen.update(method=method, url=url, kwargs=kwargs)
        if seen["responses"]:
            return seen["responses"].pop(0)
        return _Resp(200, content=AUDIO, headers={"request-id": "req1", "x-character-count": "12"})

    monkeypatch.setattr(el.requests.Session, "request", fake_request)
    return seen


@pytest.fixture()
def cli():
    return el.ElevenLabsClient(api_key="SECRET_KEY")


def test_key_is_required():
    with pytest.raises(MissingCredential):
        el.ElevenLabsClient(api_key=None)


def test_key_in_header_never_in_query(cli, capture):
    capture["responses"].append(_Resp(200, body={"voices": []}))
    cli.list_voices(search="calm")
    assert cli.session.headers["xi-api-key"] == "SECRET_KEY"
    assert "SECRET_KEY" not in capture["url"]
    assert all("SECRET_KEY" not in str(v) for v in (capture["kwargs"].get("params") or {}).values())


@pytest.mark.parametrize("call,method,path", [
    (lambda c: c.probe(), "GET", "/v1/user/subscription"),
    (lambda c: c.get_subscription(), "GET", "/v1/user/subscription"),
    (lambda c: c.list_voices(), "GET", "/v2/voices"),
    (lambda c: c.get_voice("cgSgspJ2msm6clMCkdW9"), "GET", "/v1/voices/cgSgspJ2msm6clMCkdW9"),
    (lambda c: c.list_models(), "GET", "/v1/models"),
])
def test_read_paths(cli, capture, call, method, path):
    capture["responses"].append(_Resp(200, body={"ok": True}))
    assert call(cli) == {"ok": True}
    assert capture["method"] == method
    assert capture["url"] == el.BASE_URL + path
    assert capture["kwargs"]["timeout"] == el._READ_TIMEOUT


def test_list_voices_params_and_unset_ones_dropped(cli, capture):
    capture["responses"].append(_Resp(200, body={"voices": []}))
    cli.list_voices(search="warm", category="premade", page_size=50)
    assert capture["kwargs"]["params"] == {"search": "warm", "category": "premade", "page_size": 50}


def test_list_voices_page_size_bounded(cli):
    with pytest.raises(ValueError):
        cli.list_voices(page_size=101)


def test_speech_returns_bytes_and_type(cli, capture):
    out = cli.create_speech("voice1", "Hello there.", model_id="eleven_v4", seed=7,
                            voice_settings={"stability": 0.5})
    assert capture["method"] == "POST"
    assert capture["url"] == el.BASE_URL + "/v1/text-to-speech/voice1"
    assert capture["kwargs"]["params"] == {"output_format": "mp3_44100_128"}
    assert capture["kwargs"]["json"] == {"text": "Hello there.", "model_id": "eleven_v4",
                                         "voice_settings": {"stability": 0.5}, "seed": 7}
    assert capture["kwargs"]["timeout"] == el._SPEECH_TIMEOUT
    assert out["content"] == AUDIO
    assert out["content_type"] == "audio/mpeg" and out["extension"] == "mp3"
    assert out["request_id"] == "req1" and out["character_count"] == 12


def test_speech_with_timestamps_decodes_audio(cli, capture):
    alignment = {"characters": ["H", "i"], "character_start_times_seconds": [0.0, 0.1],
                 "character_end_times_seconds": [0.1, 0.2]}
    capture["responses"].append(_Resp(200, body={
        "audio_base64": base64.b64encode(AUDIO).decode(), "alignment": alignment,
        "normalized_alignment": alignment}))
    out = cli.create_speech("voice1", "Hi", previous_text="Before.", next_text="After.",
                            timestamps=True, output_format="pcm_24000")
    assert capture["url"] == el.BASE_URL + "/v1/text-to-speech/voice1/with-timestamps"
    assert capture["kwargs"]["params"] == {"output_format": "pcm_24000"}
    assert capture["kwargs"]["json"]["previous_text"] == "Before."
    assert out["content"] == AUDIO
    assert out["alignment"] == alignment
    assert out["extension"] == "pcm"


@pytest.mark.parametrize("bad", ["../voices", "a b", "", None])
def test_voice_id_cannot_leave_the_path(cli, bad):
    with pytest.raises(ValueError):
        cli.create_speech(bad, "text")


@pytest.mark.parametrize("bad", ["mp3", "flac_44100", "mp3_44100_128;x", "MP3_44100_128"])
def test_output_format_checked(cli, bad):
    with pytest.raises(ValueError):
        cli.create_speech("voice1", "text", output_format=bad)


def test_seed_bounded(cli):
    with pytest.raises(ValueError):
        cli.create_speech("voice1", "text", seed=-1)
    with pytest.raises(ValueError):
        cli.create_speech("voice1", "text", seed=True)


def test_music_from_a_plan(cli, capture):
    plan = {"positive_global_styles": ["bright"], "negative_global_styles": ["drop"],
            "sections": [{"section_name": "Intro", "duration_ms": 3000,
                          "positive_local_styles": [], "negative_local_styles": [], "lines": []}]}
    out = cli.create_music(composition_plan=plan, model_id="music_v1", seed=3,
                           respect_sections_durations=True, output_format="mp3_48000_192")
    assert capture["url"] == el.BASE_URL + "/v1/music"
    assert capture["kwargs"]["params"] == {"output_format": "mp3_48000_192"}
    assert capture["kwargs"]["json"] == {"composition_plan": plan, "model_id": "music_v1", "seed": 3,
                                         "respect_sections_durations": True}
    assert capture["kwargs"]["timeout"] == el._MUSIC_TIMEOUT
    assert out["content"] == AUDIO


def test_music_needs_exactly_one_of_prompt_and_plan(cli):
    with pytest.raises(ValueError):
        cli.create_music()
    with pytest.raises(ValueError):
        cli.create_music(prompt="calm", composition_plan={"sections": []})
    with pytest.raises(ValueError):
        cli.create_music(composition_plan={"sections": []}, music_length_ms=10000)
    with pytest.raises(ValueError):
        cli.create_music(prompt="calm", music_length_ms=1000)


def test_sound(cli, capture):
    cli.create_sound("a soft click", duration_seconds=1.5, prompt_influence=0.6)
    assert capture["url"] == el.BASE_URL + "/v1/sound-generation"
    assert capture["kwargs"]["json"] == {"text": "a soft click", "duration_seconds": 1.5,
                                         "prompt_influence": 0.6}
    with pytest.raises(ValueError):
        cli.create_sound("x", duration_seconds=31)


def test_voice_design_decodes_each_preview(cli, capture):
    capture["responses"].append(_Resp(200, body={"text": "Read this.", "previews": [
        {"audio_base_64": base64.b64encode(AUDIO).decode(), "generated_voice_id": "g1",
         "duration_secs": 2.5, "language": "en"}]}))
    out = cli.create_voice_design("A calm, low voice for a narrator.", text="Read this.")
    assert capture["url"] == el.BASE_URL + "/v1/text-to-voice/design"
    assert capture["kwargs"]["json"] == {"voice_description": "A calm, low voice for a narrator.",
                                         "text": "Read this."}
    assert out["text"] == "Read this."
    assert out["previews"][0]["content"] == AUDIO
    assert out["previews"][0]["generated_voice_id"] == "g1"


def test_upstream_error_is_typed(cli, capture):
    capture["responses"].append(_Resp(401, body={"detail": {"status": "quota_exceeded"}}))
    with pytest.raises(UpstreamHTTPError) as e:
        cli.create_speech("voice1", "text")
    assert e.value.status_code == 401
    assert e.value.body["detail"]["status"] == "quota_exceeded"
