"""Tests pinning the device API calls of each soundbar model."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pyambeo import (
    AmbeoError,
    AmbeoEspresso,
    AmbeoPopcorn,
    AmbeoResponseError,
    DeviceInfo,
    PlayMode,
    Source,
    StateKey,
)
from pyambeo.transport import AmbeoTransport

PRESS = {"type": "bool_", "bool_": True}


def _make(cls):
    """Build a soundbar on a mocked transport."""
    transport = MagicMock(spec=AmbeoTransport)
    return cls(transport, DeviceInfo(cls.models[0], None, None, None)), transport


@pytest.mark.parametrize(
    ("method", "arg", "path", "data_type", "value"),
    [
        ("set_volume", 20, "player:volume", "i32_", 20),
        (
            "set_play_mode",
            PlayMode.SHUFFLE,
            "settings:/mediaPlayer/playMode",
            "playerPlayMode",
            "shuffle",
        ),
        ("set_mute", True, "settings:/mediaPlayer/mute", "bool_", True),
        ("set_source", 2, "espresso:audioInputID", "i32_", 2),
        ("set_preset", 4, "settings:/espresso/equalizerPreset", "i32_", 4),
        ("set_night_mode", True, "espresso:nightModeUi", "bool_", True),
        ("set_ambeo_mode", True, "espresso:ambeoModeUi", "bool_", True),
        ("set_ambeo_mode_level", 1, "settings:/espresso/ambeoMode", "i32_", 1),
        (
            "set_sound_feedback",
            False,
            "settings:/espresso/soundFeedback",
            "bool_",
            False,
        ),
        ("set_voice_enhancement_level", 3, "ui:/mydevice/voiceEnhanceLevel", "i16_", 3),
        ("set_center_speaker_level", 2, "ui:/settings/audio/centerSettings", "i16_", 2),
        ("set_side_firing_level", 2, "ui:/settings/audio/widthSettings", "i16_", 2),
        ("set_up_firing_level", 2, "ui:/settings/audio/heightSettings", "i16_", 2),
        ("set_subwoofer_status", True, "ui:/settings/subwoofer/enabled", "bool_", True),
        # The Max expects an integer subwoofer volume.
        ("set_subwoofer_volume", 3.0, "ui:/settings/subwoofer/volume", "i16_", 3),
        ("stand_by", None, "espresso:appRequestedStandby", "bool_", True),
        ("wake", None, "espresso:appRequestedOnline", "bool_", True),
    ],
)
async def test_espresso_set_value(method, arg, path, data_type, value):
    """Write each Max setting to its device path."""
    bar, transport = _make(AmbeoEspresso)
    args = () if arg is None else (arg,)
    await getattr(bar, method)(*args)
    transport.set_value.assert_awaited_once_with(path, data_type, value)


@pytest.mark.parametrize(
    ("method", "arg", "path", "data_type", "value"),
    [
        ("set_volume", 20, "player:volume", "i32_", 20),
        ("set_mute", True, "settings:/mediaPlayer/mute", "bool_", True),
        (
            "set_preset",
            "movie",
            "settings:/popcorn/audio/audioPresets/audioPreset",
            "popcornAudioPreset",
            "movie",
        ),
        (
            "set_night_mode",
            True,
            "settings:/popcorn/audio/nightModeStatus",
            "bool_",
            True,
        ),
        (
            "set_ambeo_mode",
            True,
            "settings:/popcorn/audio/ambeoModeStatus",
            "bool_",
            True,
        ),
        (
            "set_sound_feedback",
            False,
            "settings:/popcorn/ux/soundFeedbackStatus",
            "bool_",
            False,
        ),
        (
            "set_voice_enhancement",
            True,
            "settings:/popcorn/audio/voiceEnhancement",
            "bool_",
            True,
        ),
        (
            "set_codec_led_brightness",
            40,
            "ui:/settings/interface/codecLedBrightness",
            "i32_",
            40,
        ),
        (
            "set_logo_brightness",
            40,
            "ui:/settings/interface/ambeoSection/brightness",
            "i32_",
            40,
        ),
        ("change_logo_state", False, "settings:/popcorn/ui/ledStatus", "bool_", False),
        (
            "set_led_bar_brightness",
            40,
            "ui:/settings/interface/ledBrightness",
            "i32_",
            40,
        ),
        ("set_subwoofer_status", True, "ui:/settings/subwoofer/enabled", "bool_", True),
        # The Plus expects a double subwoofer volume.
        (
            "set_subwoofer_volume",
            -2.5,
            "ui:/settings/subwoofer/volume",
            "double_",
            -2.5,
        ),
        (
            "set_center_volume",
            1.0,
            "settings:/popcorn/audio/centerVolume",
            "double_",
            1.0,
        ),
    ],
)
async def test_popcorn_set_value(method, arg, path, data_type, value):
    """Write each Plus/Mini setting to its device path."""
    bar, transport = _make(AmbeoPopcorn)
    await getattr(bar, method)(arg)
    transport.set_value.assert_awaited_once_with(path, data_type, value)


@pytest.mark.parametrize(
    ("cls", "method", "args", "path", "payload"),
    [
        (AmbeoPopcorn, "set_source", ("hdmi1",), "ui:/inputs/hdmi1", PRESS),
        (AmbeoPopcorn, "play", (), "popcorn:multiPurposeButtonActivate", PRESS),
        (AmbeoPopcorn, "pause", (), "popcorn:multiPurposeButtonActivate", PRESS),
        (
            AmbeoPopcorn,
            "set_bluetooth_pairing_state",
            (True,),
            "bluetooth:deviceList/discoverable",
            PRESS,
        ),
        (AmbeoEspresso, "play", (), "player:player/control", {"control": "play"}),
        (AmbeoEspresso, "pause", (), "player:player/control", {"control": "pause"}),
        (AmbeoEspresso, "next", (), "player:player/control", {"control": "next"}),
        (
            AmbeoPopcorn,
            "seek",
            (30000,),
            "player:player/control",
            {"control": "seekTime", "time": 30000},
        ),
        (AmbeoEspresso, "reboot", (), "ui:/settings/system/restart", PRESS),
        (
            AmbeoEspresso,
            "reset_expert_settings",
            (),
            "ui:/settings/audio/resetExpertSettings",
            PRESS,
        ),
    ],
)
async def test_activate(cls, method, args, path, payload):
    """Trigger action paths with the right payload."""
    bar, transport = _make(cls)
    await getattr(bar, method)(*args)
    transport.activate.assert_awaited_once_with(path, payload)
    transport.set_value.assert_not_awaited()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("repeatOne", PlayMode.REPEAT_ONE), ("unknown", None), (None, None)],
)
async def test_get_play_mode(value, expected):
    """Read the play mode, ignoring values the library does not know."""
    bar, transport = _make(AmbeoPopcorn)
    transport.get_value = AsyncMock(return_value=value)
    assert await bar.get_play_mode() == expected
    transport.get_value.assert_awaited_once_with(
        "settings:/mediaPlayer/playMode", "playerPlayMode"
    )


@pytest.mark.parametrize(
    ("source_id", "path"),
    [("spdif", "ui:/inputs/optical"), ("hdmiarc", "ui:/inputs/hdmiTv")],
)
async def test_popcorn_set_source_uses_row_path(source_id, path):
    """Activate the path reported by the device, not one built from the ID."""
    bar, transport = _make(AmbeoPopcorn)
    bar.sources = [
        Source("hdmiarc", "HDMI TV", "ui:/inputs/hdmiTv"),
        Source("spdif", "Optical", "ui:/inputs/optical"),
    ]
    await bar.set_source(source_id)
    transport.activate.assert_awaited_once_with(path, PRESS)


async def test_popcorn_set_source_not_selectable():
    """Refuse sources only shown while casting, without calling the device."""
    bar, transport = _make(AmbeoPopcorn)
    bar.sources = [Source("googlecast", "Google Cast", selectable=False)]
    with pytest.raises(AmbeoError):
        await bar.set_source("googlecast")
    transport.activate.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "state", "pressed"),
    [
        ("play", "paused", True),
        ("play", "stopped", True),
        ("play", "playing", False),
        ("play", None, True),
        ("pause", "playing", True),
        ("pause", "paused", False),
        ("pause", "stopped", False),
        ("pause", None, True),
    ],
)
async def test_popcorn_play_pause_toggle_only_when_needed(method, state, pressed):
    """Press the multi-purpose button only when it changes the state."""
    bar, transport = _make(AmbeoPopcorn)
    data = {"state": state} if state else AmbeoResponseError("500", 500)
    transport.get_value = AsyncMock(side_effect=[data])
    await getattr(bar, method)()
    assert transport.activate.await_count == pressed


@pytest.mark.parametrize("method", ["stand_by", "wake", "reset_expert_settings"])
async def test_popcorn_unsupported(method):
    """Reject commands the Plus/Mini does not support."""
    bar, _ = _make(AmbeoPopcorn)
    with pytest.raises(NotImplementedError):
        await getattr(bar, method)()


@pytest.mark.parametrize(
    ("subwoofers", "plugged", "expected"),
    [
        ([{"id": "sub1"}], False, True),
        ([], True, True),
        ([], False, False),
        (AmbeoResponseError("404", 404), AmbeoResponseError("404", 404), False),
    ],
)
async def test_popcorn_has_subwoofer(subwoofers, plugged, expected):
    """Detect a paired or wired subwoofer, once."""
    bar, transport = _make(AmbeoPopcorn)
    transport.get_value = AsyncMock(side_effect=[subwoofers, plugged])
    assert await bar.has_subwoofer() is expected
    assert await bar.has_subwoofer() is expected
    assert transport.get_value.await_count == 2


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"modifiable": True}, True),
        ({"modifiable": False}, False),
        (AmbeoResponseError("404", 404), False),
    ],
)
async def test_espresso_has_subwoofer(data, expected):
    """Detect a subwoofer from the settings path, once."""
    bar, transport = _make(AmbeoEspresso)
    transport.get_data = AsyncMock(side_effect=[data])
    assert await bar.has_subwoofer() is expected
    assert await bar.has_subwoofer() is expected
    transport.get_data.assert_awaited_once_with("ui:/settings/subwoofer/enabled")


@pytest.mark.parametrize("cls", [AmbeoEspresso, AmbeoPopcorn])
@pytest.mark.parametrize("max_concurrency", [1, 3])
async def test_fetch_state_limits_concurrency(cls, max_concurrency):
    """Never have more than max_concurrency requests in flight during a poll."""
    bar, transport = _make(cls)
    in_flight = peak = calls = 0

    async def get_value(path, data_type):
        nonlocal in_flight, peak, calls
        in_flight += 1
        calls += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        if data_type == "espressoBrightness":
            return {"ambeologo": 1, "display": 2}

    transport.get_value = AsyncMock(side_effect=get_value)
    state = await bar.fetch_state(max_concurrency)
    assert calls > max_concurrency
    assert peak == max_concurrency
    if cls is AmbeoEspresso:
        assert state[StateKey.DISPLAY_BRIGHTNESS] == 2


@pytest.mark.parametrize(
    ("cls", "method", "path", "data_type", "raw", "expected"),
    [
        (AmbeoEspresso, "get_night_mode", "espresso:nightModeUi", "bool_", True, True),
        (
            AmbeoPopcorn,
            "get_night_mode",
            "settings:/popcorn/audio/nightModeStatus",
            "bool_",
            True,
            True,
        ),
        (AmbeoPopcorn, "get_volume", "player:volume", "i32_", 20, 20),
        (
            AmbeoPopcorn,
            "get_state",
            "powermanager:target",
            "powerTarget",
            {"target": "online"},
            "online",
        ),
        (AmbeoPopcorn, "get_state", "powermanager:target", "powerTarget", None, None),
        (
            AmbeoPopcorn,
            "get_bluetooth_pairing_state",
            "bluetooth:state",
            "bluetoothState",
            {"pairable": True},
            True,
        ),
    ],
)
async def test_get_value(cls, method, path, data_type, raw, expected):
    """Read each setting from its device path, unwrapping nested values."""
    bar, transport = _make(cls)
    transport.get_value = AsyncMock(return_value=raw)
    assert await getattr(bar, method)() == expected
    transport.get_value.assert_awaited_once_with(path, data_type)


@pytest.mark.parametrize(
    ("cls", "method"),
    [
        (AmbeoEspresso, "get_eco_mode"),
        (AmbeoEspresso, "get_led_bar_brightness"),
        (AmbeoPopcorn, "get_display_brightness"),
        (AmbeoPopcorn, "get_up_firing_level"),
    ],
)
async def test_get_unsupported(cls, method):
    """Raise NotImplementedError for settings the model does not have."""
    bar, transport = _make(cls)
    with pytest.raises(NotImplementedError):
        await getattr(bar, method)()
    transport.get_value.assert_not_called()
