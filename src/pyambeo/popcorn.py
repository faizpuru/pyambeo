"""Implementation for Ambeo Soundbar Plus and Mini (Popcorn)."""

from .const import (
    AMBEO_POPCORN_VOLUME_STEP,
    MINI_SOUNDBAR,
    PLUS_SOUNDBAR,
    Capability,
    Setting,
    StateKey,
)
from .exceptions import AmbeoResponseError
from .models import Preset, Source
from .soundbar import AmbeoSoundbar
from .transport import AmbeoTransport


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

    # Inputs not listed by the device.
    _ADDITIONAL_SOURCES = (
        Source("airplay", "AirPlay"),
        Source("googlecast", "Google Cast"),
    )

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

    async def play(self) -> None:
        """Send play command."""
        await self._multi_purpose_button()

    async def pause(self) -> None:
        """Send pause command."""
        await self._multi_purpose_button()

    async def set_bluetooth_pairing_state(self, state: bool) -> None:
        """Set the Bluetooth pairing state."""
        await self._transport.activate(
            "bluetooth:deviceList/discoverable", {"type": "bool_", "bool_": state}
        )

    async def fetch_sources(self) -> list[Source]:
        """Fetch all available audio sources."""
        rows = await self._transport.get_rows("ui:/inputs", 0, 10)
        sources = [
            Source(row["id"], row["title"], row.get("path"))
            for row in rows
            if "id" in row and "title" in row
        ]
        sources.extend(self._ADDITIONAL_SOURCES)
        return sources

    async def set_source(self, source_id: str) -> None:
        """Set the audio source."""
        # The ID is not always the last segment of the path (spdif -> optical).
        path = next(
            (s.path for s in self.sources if s.id == source_id and s.path),
            f"ui:/inputs/{source_id}",
        )
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
        """Check if a subwoofer is connected."""
        if self._has_subwoofer is None:
            try:
                subwoofers = await self._transport.get_value(
                    "settings:/popcorn/subwoofer/list", "popcornSubwooferList"
                )
            except AmbeoResponseError:
                subwoofers = None
            self._has_subwoofer = bool(subwoofers)
        return self._has_subwoofer
