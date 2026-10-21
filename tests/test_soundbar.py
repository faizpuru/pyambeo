"""Tests for the Ambeo soundbar models."""

import asyncio
import json
from unittest.mock import AsyncMock

import aiohttp
import pytest

from pyambeo import (
    AmbeoConnectionError,
    AmbeoEspresso,
    AmbeoPopcorn,
    AmbeoResponseError,
    AmbeoSoundbar,
    AmbeoUnsupportedModelError,
    Capability,
    DeviceInfo,
    PlayerStatus,
    Preset,
    Range,
    Source,
    StateKey,
)
from pyambeo.transport import AmbeoTransport

from .conftest import HOST, mock_device_info, mock_rows, mock_value, url_for

PLUS = "AMBEO Soundbar Plus"
MAX = "AMBEO Soundbar Max"


def _make(cls, session, **kwargs):
    """Build a soundbar without connecting."""
    return cls(
        AmbeoTransport(HOST, session),
        DeviceInfo(cls.models[0], "name", "serial", "1.0"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


async def test_connect_popcorn(mock_http, session):
    """Pick the Popcorn implementation and load info, sources and presets."""
    mock_device_info(mock_http, PLUS)
    mock_rows(
        mock_http,
        "ui:/inputs",
        [
            {"id": "hdmi1", "title": "HDMI 1"},
            {"id": "spdif", "title": "Optical", "path": "ui:/inputs/optical"},
        ],
    )
    mock_value(
        mock_http,
        "settings:/popcorn/ui/input/inputList",
        "popcornInputList",
        [
            {"id": "hdmi1", "name": "HDMI 1", "customName": "Google TV"},
            {"id": "spdif", "name": "Optical", "customName": ""},
        ],
    )
    mock_http.get(
        url_for("getData", "settings:/popcorn/audio/centerVolume"),
        payload={
            "edit": {"min": "-6", "max": "9", "step": "1", "type": "slider"},
            "valueUnit": {"type": "string_", "string_": "db"},
        },
    )
    mock_rows(
        mock_http,
        "settings:/popcorn/audio/audioPresetValues",
        [{"title": "Movies", "value": {"popcornAudioPreset": "movies"}}],
    )

    bar = await AmbeoSoundbar.connect(HOST, session)

    assert isinstance(bar, AmbeoPopcorn)
    assert bar.info == DeviceInfo(PLUS, "Living room", "SN123", "1.2.3")
    assert bar.sources == [
        Source("hdmi1", "Google TV"),
        Source("spdif", "Optical", "ui:/inputs/optical"),
        Source("airplay", "AirPlay", selectable=False),
        Source("googlecast", "Google Cast", selectable=False),
    ]
    assert bar.presets == [Preset("movies", "Movies")]
    # Reported by the device, otherwise the known bounds.
    assert bar.get_range(StateKey.CENTER_VOLUME) == Range(-6, 9, 1, "dB")
    assert bar.get_range(StateKey.SUBWOOFER_VOLUME) == Range(-10, 10, unit="dB")


# Order of the espresso: rows of a Max (ha-ambeo_soundbar#44 HAR).
MAX_INPUT_ROWS = [
    {"title": t}
    for t in [
        "HDMI1",
        "HDMI2",
        "HDMI3",
        "HDMIARC",
        "bluetooth",
        "googlecast",
        "UPnP",
        "Optical",
        "AUX",
        "spotify",
        "AES",
        "airplay",
        "avs",
        "tidal",
        "tuneIn",
        "Toggle_Next",
        "Toggle_Prev",
    ]
]


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (
            "stream810ambeobar",
            [Source(0, "TV"), Source(7, "Optical"), Source(14, "Tidal Connect")],
        ),
        ("stream810ambeobarcn", [Source(0, "TV"), Source(7, "Optical")]),
    ],
)
async def test_connect_espresso_sources(mock_http, session, machine, expected):
    """Map Max input names to the input IDs used by the web app."""
    mock_device_info(mock_http, MAX)
    mock_value(mock_http, "settings:/system/machineName", "string_", machine)
    mock_rows(
        mock_http,
        "settings:/espresso/inputNames",
        [
            {"title": "hdmi1", "value": {"string_": "TV"}},
            {"title": "aes", "value": {"string_": "AES"}},
            {"title": "optical", "value": {"string_": "Optical"}},
            {"title": "tidal", "value": {"string_": "Tidal Connect"}},
            {"title": "hdmi2", "value": {"string_": "Not listed"}},
        ],
    )
    mock_rows(
        mock_http,
        "espresso:",
        [r for r in MAX_INPUT_ROWS if r["title"] != "HDMI2"],
    )

    bar = await AmbeoSoundbar.connect(HOST, session)

    assert isinstance(bar, AmbeoEspresso)
    assert bar.sources == expected
    assert [p.title for p in bar.presets][:2] == ["Neutral", "Movies"]


async def test_connect_tolerates_missing_sources(mock_http, session):
    """Fall back to empty sources/presets when the device rejects them."""
    mock_device_info(mock_http, PLUS)
    mock_http.get(url_for("getRows"), status=404, repeat=True)

    bar = await AmbeoSoundbar.connect(HOST, session)

    assert bar.sources == []
    assert bar.presets == []


async def test_connect_unsupported_model(mock_http, session):
    """Raise for unknown models."""
    mock_device_info(mock_http, "AMBEO Soundbar Ultra")
    with pytest.raises(AmbeoUnsupportedModelError) as err:
        await AmbeoSoundbar.connect(HOST, session)
    assert err.value.model == "AMBEO Soundbar Ultra"


async def test_connect_on_other_subclass(mock_http, session):
    """Refuse a device of another model when called on a subclass."""
    mock_device_info(mock_http, MAX)
    with pytest.raises(AmbeoUnsupportedModelError):
        await AmbeoPopcorn.connect(HOST, session)


async def test_connect_model_unreadable(mock_http, session):
    """Report a device error, not an unsupported model, when the model is unreadable."""
    mock_http.get(url_for("getData"), status=500, repeat=True)
    with pytest.raises(AmbeoResponseError):
        await AmbeoSoundbar.connect(HOST, session)


async def test_connect_skips_malformed_espresso_rows(mock_http, session):
    """Ignore Max input rows missing their title or value."""
    mock_device_info(mock_http, MAX)
    mock_rows(
        mock_http,
        "settings:/espresso/inputNames",
        [
            {"title": "HDMI1", "value": {"string_": "TV"}},
            {"title": "optical"},
            {"value": {"string_": "No title"}},
        ],
    )
    mock_rows(mock_http, "espresso:", [{"title": "hdmi1"}, {}, {"title": "optical"}])
    mock_http.get(
        url_for("getData", "settings:/system/machineName"), status=500, repeat=True
    )

    bar = await AmbeoSoundbar.connect(HOST, session)

    assert bar.sources == [Source(0, "TV")]


async def test_connect_skips_malformed_popcorn_presets(mock_http, session):
    """Ignore Popcorn preset rows missing their title or value."""
    mock_device_info(mock_http, PLUS)
    mock_rows(mock_http, "ui:/inputs", [])
    mock_http.get(
        url_for("getData", "settings:/popcorn/ui/input/inputList"),
        status=500,
        repeat=True,
    )
    mock_rows(
        mock_http,
        "settings:/popcorn/audio/audioPresetValues",
        [
            {"title": "Movies", "value": {"popcornAudioPreset": "movies"}},
            {"title": "Broken"},
            {"title": "Null", "value": None},
            {"value": {"popcornAudioPreset": "music"}},
        ],
    )

    bar = await AmbeoSoundbar.connect(HOST, session)

    assert bar.presets == [Preset("movies", "Movies")]


async def test_connect_unreachable(mock_http, session):
    """Propagate connection errors."""
    mock_http.get(
        url_for("getData"), exception=aiohttp.ClientConnectionError(), repeat=True
    )
    with pytest.raises(AmbeoConnectionError):
        await AmbeoSoundbar.connect(HOST, session)


# ---------------------------------------------------------------------------
# fetch_state()
# ---------------------------------------------------------------------------


async def test_fetch_state(mock_http, session):
    """Return core values and capability-filtered optional values."""
    bar = _make(AmbeoEspresso, session)
    mock_value(mock_http, "player:volume", "i32_", 20)
    mock_value(mock_http, "settings:/mediaPlayer/mute", "bool_", False)
    mock_value(mock_http, "powermanager:target", "powerTarget", {"target": "online"})
    mock_value(mock_http, "espresso:audioInputID", "i32_", 1)
    mock_value(mock_http, "settings:/espresso/equalizerPreset", "i32_", 4)
    mock_value(mock_http, "espresso:nightModeUi", "bool_", True)
    mock_value(
        mock_http,
        "settings:/espresso/brightnessSensor",
        "espressoBrightness",
        {"ambeologo": 10, "display": 20},
    )
    # Everything else is rejected by the device.
    mock_http.get(url_for("getData"), status=404, repeat=True)

    state = await bar.fetch_state()

    assert state[StateKey.VOLUME] == 20
    assert state[StateKey.MUTED] is False
    assert state[StateKey.STATE] == "online"
    assert state[StateKey.CURRENT_SOURCE] == 1
    assert state[StateKey.CURRENT_PRESET] == 4
    assert state[StateKey.PLAYER_DATA] is None
    assert state[StateKey.NIGHT_MODE] is True
    assert state[StateKey.DISPLAY_BRIGHTNESS] == 20
    assert state[StateKey.LOGO_BRIGHTNESS] == 10
    # Logo and display share one path: read it once.
    brightness_reads = [
        url
        for (method, url), calls in mock_http.requests.items()
        for _ in calls
        if url.query.get("path") == "settings:/espresso/brightnessSensor"
    ]
    assert len(brightness_reads) == 1
    # Popcorn-only capability, never fetched on the Max.
    assert StateKey.LED_BAR_BRIGHTNESS not in state
    # Rejected optional value is left out.
    assert StateKey.AMBEO_MODE not in state


async def test_fetch_state_unreachable(mock_http, session):
    """Propagate connection errors on core values."""
    bar = _make(AmbeoPopcorn, session)
    mock_http.get(
        url_for("getData"), exception=aiohttp.ClientConnectionError(), repeat=True
    )
    with pytest.raises(AmbeoConnectionError):
        await bar.fetch_state()


# ---------------------------------------------------------------------------
# player_status()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "state", "expected"),
    [
        (AmbeoEspresso, {"state": "networkStandby"}, PlayerStatus.STANDBY),
        (AmbeoPopcorn, {"state": "networkStandby"}, PlayerStatus.STANDBY),
        # Eco mode is a setting, not a power state.
        (
            AmbeoPopcorn,
            {"state": "online", "eco_mode": True, "decoder_status": {"channels": 2}},
            PlayerStatus.PLAYING,
        ),
        (AmbeoPopcorn, {"state": None}, PlayerStatus.ON),
        (
            AmbeoPopcorn,
            {"state": "online", "player_data": {"state": "paused"}},
            PlayerStatus.PAUSED,
        ),
        (
            AmbeoPopcorn,
            {"state": "online", "decoder_status": {"channels": 2}},
            PlayerStatus.PLAYING,
        ),
        (
            AmbeoEspresso,
            {"state": "online", "decoder_status": {"decoder_status": 0}},
            PlayerStatus.IDLE,
        ),
        (
            AmbeoPopcorn,
            {"state": "online", "player_data": {"state": "playing"}},
            PlayerStatus.PLAYING,
        ),
        (
            AmbeoPopcorn,
            {"state": "online", "player_data": {"state": "unknown"}},
            PlayerStatus.IDLE,
        ),
    ],
)
async def test_player_status(session, cls, state, expected):
    """Derive the playback status from a state snapshot."""
    assert _make(cls, session).player_status(state) == expected


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


async def test_subscribed_paths(session):
    """Subscribe to base paths and capability-filtered model paths."""
    popcorn = _make(AmbeoPopcorn, session).subscribed_paths()
    espresso = _make(AmbeoEspresso, session).subscribed_paths()

    assert "powermanager:target" in popcorn
    assert "bluetooth:state" in popcorn
    assert "settings:/espresso/brightnessSensor" not in popcorn
    assert "settings:/espresso/brightnessSensor" in espresso
    assert "bluetooth:state" not in espresso


async def test_process_event(session):
    """Map event values to state keys."""
    popcorn = _make(AmbeoPopcorn, session)
    espresso = _make(AmbeoEspresso, session)

    assert popcorn.process_event(
        "powermanager:target", {"powerTarget": {"target": "online"}}
    ) == {StateKey.STATE: "online"}
    assert popcorn.process_event(
        "bluetooth:state", {"bluetoothState": {"pairable": True}}
    ) == {StateKey.BLUETOOTH_PAIRING: True}
    assert espresso.process_event(
        "settings:/mediaPlayer/playMode", {"playerPlayMode": "shuffleRepeatAll"}
    ) == {StateKey.PLAY_MODE: "shuffleRepeatAll"}
    assert espresso.process_event(
        "settings:/espresso/brightnessSensor",
        {"espressoBrightness": {"ambeologo": 5, "display": 7}},
    ) == {StateKey.LOGO_BRIGHTNESS: 5, StateKey.DISPLAY_BRIGHTNESS: 7}
    assert (
        espresso.process_event(
            "settings:/espresso/brightnessSensor", {"espressoBrightness": None}
        )
        == {}
    )
    assert popcorn.process_event("unknown:path", {"i32_": 1}) == {}


async def test_listen(session):
    """Yield batched updates and recreate the queue when it is lost."""
    bar = _make(AmbeoPopcorn, session)
    transport = bar._transport
    transport.create_event_queue = AsyncMock(side_effect=["q1", "q2"])
    transport.poll_event_queue = AsyncMock(
        side_effect=[
            [
                {
                    "itemType": "update",
                    "path": "player:volume",
                    "itemValue": {"i32_": 3},
                },
                {
                    "itemType": "update",
                    "path": "settings:/mediaPlayer/mute",
                    "itemValue": {"bool_": True},
                },
                {"itemType": "add", "path": "player:volume", "itemValue": {"i32_": 9}},
            ],
            [],
            None,
            [{"itemType": "update", "path": "player:volume", "itemValue": {"i32_": 4}}],
        ]
    )

    listener = bar.listen(retry_delay=0)
    assert await anext(listener) == {StateKey.VOLUME: 3, StateKey.MUTED: True}
    assert await anext(listener) == {StateKey.VOLUME: 4}
    await listener.aclose()

    assert [c.args[0] for c in transport.create_event_queue.call_args_list] == [
        bar.subscribed_paths(),
        bar.subscribed_paths(),
    ]
    assert transport.poll_event_queue.call_args_list[-1].args[0] == "q2"


async def test_listen_retries_queue_creation(session):
    """Retry queue creation after a delay when it fails."""
    bar = _make(AmbeoPopcorn, session)
    transport = bar._transport
    transport.create_event_queue = AsyncMock(
        side_effect=[AmbeoConnectionError("down"), None, "q"]
    )
    transport.poll_event_queue = AsyncMock(
        return_value=[
            {"itemType": "update", "path": "player:volume", "itemValue": {"i32_": 1}}
        ]
    )

    update = await asyncio.wait_for(anext(bar.listen(retry_delay=0)), 1)

    assert update == {StateKey.VOLUME: 1}
    assert transport.create_event_queue.await_count == 3


async def test_has_capability(session):
    """Capabilities accept enum members and raw strings."""
    bar = _make(AmbeoEspresso, session)
    assert bar.has_capability(Capability.STANDBY)
    assert bar.has_capability("standby")
    assert not bar.has_capability(Capability.LED_BAR)


# ---------------------------------------------------------------------------
# audio_codec()
# ---------------------------------------------------------------------------


def _bluetooth(uri):
    return {
        StateKey.DECODER_STATUS: {"codec": "pcm"},
        StateKey.PLAYER_DATA: {
            "mediaRoles": {"mediaData": {"resources": [{"uri": uri}]}}
        },
    }


@pytest.mark.parametrize(
    ("cls", "state", "expected"),
    [
        (AmbeoPopcorn, {StateKey.DECODER_STATUS: {"codec": "pcm"}}, "PCM"),
        (AmbeoPopcorn, {StateKey.DECODER_STATUS: {"codec": "MPEG-4 AAC"}}, "AAC"),
        (
            AmbeoPopcorn,
            {StateKey.DECODER_STATUS: {"codec": "Dolby TrueHD - Dolby Atmos"}},
            "Dolby TrueHD - Dolby Atmos",
        ),
        (
            AmbeoPopcorn,
            {StateKey.DECODER_STATUS: {"codec": "E-AC-3 (container: ISO MP4/M4A)"}},
            "Dolby Atmos",
        ),
        (AmbeoPopcorn, {StateKey.DECODER_STATUS: {"codec": "Opus"}}, "Opus"),
        (AmbeoPopcorn, _bluetooth("bluetoothsbc:00:11"), "SBC"),
        (AmbeoPopcorn, _bluetooth("bluetoothaac:00:11"), "AAC"),
        (AmbeoPopcorn, _bluetooth("HDMI:1"), "PCM"),
        (AmbeoPopcorn, {StateKey.DECODER_STATUS: {}}, None),
        (AmbeoPopcorn, {}, None),
        (AmbeoEspresso, {StateKey.DECODER_STATUS: {"decoder_status": 1}}, "PCM"),
        (AmbeoEspresso, {StateKey.DECODER_STATUS: {"decoder_status": 18}}, "DTS:X"),
        (AmbeoEspresso, {StateKey.DECODER_STATUS: {"decoder_status": 99}}, "Codec 99"),
        (AmbeoEspresso, {StateKey.DECODER_STATUS: {"decoder_status": 0}}, None),
        (AmbeoEspresso, {}, None),
    ],
)
async def test_audio_codec(session, cls, state, expected):
    """Name the decoded codec as the web app does."""
    assert _make(cls, session).audio_codec(state) == expected


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            {
                "edit": {"min": "-10.0", "max": "10.0", "step": "1"},
                "valueUnit": {"string_": "db"},
            },
            Range(-10, 10, 1, "dB"),
        ),
        ({"edit": {"min": "0", "max": "100"}}, Range(0, 100, 1, "%")),
        ({"edit": {"min": "5", "max": "5"}}, None),
        ({"edit": {"min": "a", "max": "5"}}, None),
        ({"edit": {"max": "5"}}, None),
        ({"value": {"i32_": 1}}, None),
    ],
)
async def test_fetch_ranges(session, data, expected):
    """Read the slider bounds from the device, ignoring invalid ones."""
    bar = _make(AmbeoPopcorn, session)
    bar._transport.get_data = AsyncMock(return_value=data)
    await bar.fetch_ranges()
    default = AmbeoPopcorn._DEFAULT_RANGES[StateKey.LED_BAR_BRIGHTNESS]
    assert bar.get_range(StateKey.LED_BAR_BRIGHTNESS) == (expected or default)


async def test_fetch_ranges_tolerates_errors(session):
    """Fall back to the known bounds when the device does not answer."""
    bar = _make(AmbeoEspresso, session)
    bar._transport.get_data = AsyncMock(side_effect=AmbeoResponseError("404", 404))
    await bar.fetch_ranges()
    assert bar.get_display_volume_max() == 50
    assert bar.get_logo_brightness_range() == (1, 118)
    assert bar.get_display_brightness_range() == (1, 126)
    assert (bar.get_subwoofer_min_value(), bar.get_subwoofer_max_value()) == (-12, 12)


async def test_fetch_ranges_espresso(session):
    """Read the Max bounds, as numbers; the display shows half the volume."""
    bar = _make(AmbeoEspresso, session)
    bar._transport.get_data = AsyncMock(
        return_value={
            "edit": {"max": 12, "min": -12, "step": 1, "type": "number"},
            "valueUnit": {"type": "string_", "string_": "db"},
        }
    )
    await bar.fetch_ranges()
    assert bar.get_range(StateKey.SIDE_FIRING_LEVEL) == Range(-12, 12, 1, "dB")
    assert bar.get_range(StateKey.VOLUME) == Range(-12, 12, 1, "dB")
    assert bar.get_display_volume_max() == 50


async def test_range_getters_use_device_ranges(session):
    """Derive the legacy range getters from the device bounds."""
    bar = _make(AmbeoPopcorn, session)
    bar._transport.get_data = AsyncMock(
        return_value={"edit": {"min": "-5.0", "max": "50.0", "step": "1"}}
    )
    await bar.fetch_ranges()
    assert bar.get_display_volume_max() == 50
    assert bar.get_led_bar_brightness_range() == (-5, 50)
    assert bar.get_range(StateKey.UP_FIRING_LEVEL) == Range(-12, 12, unit="dB")
    assert bar.get_range(StateKey.NIGHT_MODE) is None


def _set_data_values(mock_http) -> list[dict]:
    """Return the JSON values sent with setData requests."""
    return [
        json.loads(url.query["value"])
        for (method, url) in mock_http.requests
        if url.path.endswith("/setData")
    ]


async def test_set_logo_brightness_keeps_display(mock_http, session):
    """Write the new logo brightness along with the current display brightness."""
    bar = _make(AmbeoEspresso, session)
    mock_value(
        mock_http,
        "settings:/espresso/brightnessSensor",
        "espressoBrightness",
        {"ambeologo": 10, "display": 20},
    )
    mock_http.get(url_for("setData"), payload=None)

    await bar.set_logo_brightness(5)

    assert _set_data_values(mock_http) == [
        {
            "type": "espressoBrightness",
            "espressoBrightness": {"ambeologo": 5, "display": 20},
        }
    ]


async def test_set_brightness_missing_value(mock_http, session):
    """Refuse to overwrite the other brightness when it cannot be read."""
    bar = _make(AmbeoEspresso, session)
    mock_value(
        mock_http,
        "settings:/espresso/brightnessSensor",
        "espressoBrightness",
        {"ambeologo": 10},
    )

    with pytest.raises(AmbeoResponseError):
        await bar.set_logo_brightness(5)
    assert _set_data_values(mock_http) == []
