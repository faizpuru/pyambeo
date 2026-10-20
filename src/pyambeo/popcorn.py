"""Implementation for Ambeo Soundbar Plus and Mini (Popcorn)."""

import asyncio
from collections.abc import Mapping
from typing import Any

from .const import (
    AMBEO_POPCORN_VOLUME_STEP,
    MINI_SOUNDBAR,
    PLUS_SOUNDBAR,
    Capability,
    Setting,
    StateKey,
)
from .exceptions import AmbeoError
from .models import Preset, Source
from .soundbar import AmbeoSoundbar, _none_on_response_error
from .transport import AmbeoTransport

# Short names of the plain codecs, as shown by the web app. Dolby, DTS and
# MPEG-H names are already descriptive and kept as is.
_SHORT_CODEC_NAMES = (
    ("pcm", "PCM"),
    ("vorbis", "Vorbis"),
    ("mp3", "MP3"),
    ("flac", "FLAC"),
    ("aac", "AAC"),
    ("sbc", "SBC"),
)


def _codec_name(codec: str) -> str:
    """Return the display name of a decoder codec."""
    lowered = codec.lower()
    if "dolby" in lowered or "dts" in lowered or "mpeg-h" in lowered:
        return codec
    # Tidal Atmos is reported by its container.
    if lowered.startswith("e-ac-3"):
        return "Dolby Atmos"
    for needle, name in _SHORT_CODEC_NAMES:
        if needle in lowered:
            return name
    return codec


class AmbeoPopcorn(AmbeoSoundbar):
    """Ambeo Soundbar Plus and Mini."""

    models = (MINI_SOUNDBAR, PLUS_SOUNDBAR)

    capabilities = frozenset(
        {
            Capability.AMBEO_LOGO,
            Capability.BLUETOOTH_PAIRING,
            Capability.CODEC_LED,
            Capability.DECODER_STATUS,
            Capability.ECO_MODE,
            Capability.LED_BAR,
            Capability.NATIVE_VOLUME,
            Capability.SUBWOOFER,
            Capability.VOICE_ENHANCEMENT_TOGGLE,
            Capability.CENTER_VOLUME,
        }
    )

    _SETTINGS = (
        Setting(
            "settings:/popcorn/audio/nightModeStatus", StateKey.NIGHT_MODE, "bool_"
        ),
        Setting(
            "settings:/popcorn/audio/ambeoModeStatus", StateKey.AMBEO_MODE, "bool_"
        ),
        Setting(
            "settings:/popcorn/ux/soundFeedbackStatus", StateKey.SOUND_FEEDBACK, "bool_"
        ),
        Setting(
            "popcorn:inputChange/selected", StateKey.CURRENT_SOURCE, "popcornInputId"
        ),
        Setting(
            "settings:/popcorn/audio/audioPresets/audioPreset",
            StateKey.CURRENT_PRESET,
            "popcornAudioPreset",
        ),
        Setting(
            "ui:/settings/interface/codecLedBrightness",
            StateKey.CODEC_LED_BRIGHTNESS,
            "i32_",
            Capability.CODEC_LED,
        ),
        Setting(
            "ui:/settings/interface/ambeoSection/brightness",
            StateKey.LOGO_BRIGHTNESS,
            "i32_",
            Capability.AMBEO_LOGO,
        ),
        Setting(
            "settings:/popcorn/ui/ledStatus",
            StateKey.LOGO_STATE,
            "bool_",
            Capability.AMBEO_LOGO,
        ),
        Setting(
            "ui:/settings/interface/ledBrightness",
            StateKey.LED_BAR_BRIGHTNESS,
            "i32_",
            Capability.LED_BAR,
        ),
        Setting(
            "ui:/settings/subwoofer/enabled",
            StateKey.SUBWOOFER_STATUS,
            "bool_",
            Capability.SUBWOOFER,
        ),
        Setting(
            "ui:/settings/subwoofer/volume",
            StateKey.SUBWOOFER_VOLUME,
            "double_",
            Capability.SUBWOOFER,
        ),
        Setting(
            "uipopcorn:ecoModeState", StateKey.ECO_MODE, "bool_", Capability.ECO_MODE
        ),
        Setting(
            "imx8af:decoderAudioFormat",
            StateKey.DECODER_STATUS,
            "imx8AfAudioFormat",
            Capability.DECODER_STATUS,
        ),
        Setting(
            "settings:/popcorn/audio/voiceEnhancement",
            StateKey.VOICE_ENHANCEMENT,
            "bool_",
            Capability.VOICE_ENHANCEMENT_TOGGLE,
        ),
        Setting(
            "bluetooth:state",
            StateKey.BLUETOOTH_PAIRING,
            "bluetoothState",
            Capability.BLUETOOTH_PAIRING,
            "pairable",
        ),
        Setting(
            "settings:/popcorn/audio/centerVolume",
            StateKey.CENTER_VOLUME,
            "double_",
            Capability.CENTER_VOLUME,
        ),
    )

    # Inputs not listed by the device: they become active when casting to it.
    _ADDITIONAL_SOURCES = (
        Source("airplay", "AirPlay", selectable=False),
        Source("googlecast", "Google Cast", selectable=False),
    )
    _INPUT_NAMES_PATH = "settings:/popcorn/ui/input/inputList"

    def __init__(self, transport: AmbeoTransport, *args, **kwargs) -> None:
        """Initialize and set up instance variables."""
        super().__init__(transport, *args, **kwargs)
        self._has_subwoofer: bool | None = None

    def get_volume_step(self) -> float:
        """Get the volume step size."""
        return AMBEO_POPCORN_VOLUME_STEP

    async def _multi_purpose_button(self) -> None:
        """Press the multi-purpose button (toggles play/pause)."""
        await self._transport.activate(
            "popcorn:multiPurposeButtonActivate", {"type": "bool_", "bool_": True}
        )

    async def _player_state(self) -> str | None:
        """Return the player state (playing, paused…), if readable."""
        data = await _none_on_response_error(self._get(StateKey.PLAYER_DATA))
        return data.get("state") if isinstance(data, dict) else None

    # The web app plays and pauses with the multi-purpose button, as player
    # controls do not resume cast streams. It toggles: only press it when needed.
    async def play(self) -> None:
        """Send play command."""
        if await self._player_state() != "playing":
            await self._multi_purpose_button()

    async def pause(self) -> None:
        """Send pause command."""
        if await self._player_state() not in ("paused", "stopped"):
            await self._multi_purpose_button()

    def audio_codec(self, state: Mapping[str, Any]) -> str | None:
        """Return the codec of the decoded audio, or None when there is none."""
        # Bluetooth bypasses the decoder: the codec is in the stream URI.
        player_data = state.get(StateKey.PLAYER_DATA) or {}
        media_data = (player_data.get("mediaRoles") or {}).get("mediaData") or {}
        resources = media_data.get("resources") or [{}]
        uri = resources[0].get("uri") if isinstance(resources[0], dict) else None
        if isinstance(uri, str) and uri.startswith("bluetooth"):
            return "SBC" if uri.startswith("bluetoothsbc:") else "AAC"
        decoder_status = state.get(StateKey.DECODER_STATUS)
        codec = (
            decoder_status.get("codec") if isinstance(decoder_status, dict) else None
        )
        if not isinstance(codec, str) or not codec:
            return None
        return _codec_name(codec)

    async def set_bluetooth_pairing_state(self, state: bool) -> None:
        """Set the Bluetooth pairing state."""
        await self._transport.activate(
            "bluetooth:deviceList/discoverable", {"type": "bool_", "bool_": state}
        )

    async def fetch_sources(self) -> list[Source]:
        """Fetch all available audio sources, with the names set by the user."""
        rows, inputs = await asyncio.gather(
            self._transport.get_rows("ui:/inputs", 0, 10),
            _none_on_response_error(
                self._transport.get_value(self._INPUT_NAMES_PATH, "popcornInputList")
            ),
        )
        custom_names = {
            i["id"]: i["customName"]
            for i in inputs or []
            if isinstance(i, dict) and i.get("id") and i.get("customName")
        }
        sources = [
            Source(
                row["id"], custom_names.get(row["id"], row["title"]), row.get("path")
            )
            for row in rows
            if "id" in row and "title" in row
        ]
        sources.extend(self._ADDITIONAL_SOURCES)
        return sources

    async def set_source(self, source_id: str) -> None:
        """Set the audio source.

        Raises AmbeoError for sources that cannot be selected (AirPlay…).
        """
        source = next((s for s in self.sources if s.id == source_id), None)
        if source is not None and not source.selectable:
            raise AmbeoError(f"Source {source_id} cannot be selected")
        # The ID is not always the last segment of the path (spdif -> optical).
        path = (source.path if source else None) or f"ui:/inputs/{source_id}"
        await self._transport.activate(path, {"type": "bool_", "bool_": True})

    async def fetch_presets(self) -> list[Preset]:
        """Fetch all available audio presets."""
        rows = await self._transport.get_rows(
            "settings:/popcorn/audio/audioPresetValues", 0, 10
        )
        return [
            Preset(row["value"]["popcornAudioPreset"], row["title"])
            for row in rows
            if "title" in row
            and isinstance(row.get("value"), dict)
            and "popcornAudioPreset" in row["value"]
        ]

    async def has_subwoofer(self) -> bool:
        """Check if a wireless or wired subwoofer is connected."""
        if self._has_subwoofer is None:
            subwoofers, plugged = await asyncio.gather(
                _none_on_response_error(
                    self._transport.get_value(
                        "settings:/popcorn/subwoofer/list", "popcornSubwooferList"
                    )
                ),
                _none_on_response_error(
                    self._transport.get_value("popcorn:subPlugDetect", "bool_")
                ),
            )
            self._has_subwoofer = bool(subwoofers) or plugged is True
        return self._has_subwoofer
