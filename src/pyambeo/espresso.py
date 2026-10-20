"""Implementation for Ambeo Soundbar Max (Espresso)."""

import asyncio
import logging
from typing import Any

from .const import (
    AMBEO_MAX_VOLUME_STEP,
    EXCLUDE_SOURCES_MAX,
    MAX_SOUNDBAR,
    Capability,
    Setting,
    StateKey,
)
from .exceptions import AmbeoError, AmbeoResponseError
from .models import Preset, Range, Source
from .soundbar import AmbeoSoundbar
from .transport import AmbeoTransport

_LOGGER = logging.getLogger(__name__)


def _brightness_state(brightness: dict) -> dict[StateKey, Any]:
    """Map an espressoBrightness value to logo and display brightness."""
    values = {
        StateKey.LOGO_BRIGHTNESS: brightness.get("ambeologo"),
        StateKey.DISPLAY_BRIGHTNESS: brightness.get("display"),
    }
    return {key: value for key, value in values.items() if value is not None}


class AmbeoEspresso(AmbeoSoundbar):
    """Ambeo Soundbar Max."""

    models = (MAX_SOUNDBAR,)

    capabilities = frozenset(
        {
            Capability.AMBEO_MODE_LEVEL,
            Capability.CENTER_SPEAKER_LEVEL,
            Capability.DECODER_STATUS,
            Capability.MAX_DISPLAY,
            Capability.MAX_LOGO,
            Capability.NATIVE_VOLUME,
            Capability.RESET_EXPERT_SETTINGS,
            Capability.SIDE_FIRING_LEVEL,
            Capability.STANDBY,
            Capability.SUBWOOFER,
            Capability.UP_FIRING_LEVEL,
            Capability.VOICE_ENHANCEMENT_LEVEL,
        }
    )

    # brightnessSensor is subscribed separately because it maps to two keys.
    _BRIGHTNESS_PATH = "settings:/espresso/brightnessSensor"

    _SETTINGS = (
        Setting("espresso:nightModeUi", StateKey.NIGHT_MODE, "bool_"),
        Setting("espresso:ambeoModeUi", StateKey.AMBEO_MODE, "bool_"),
        Setting("settings:/espresso/soundFeedback", StateKey.SOUND_FEEDBACK, "bool_"),
        Setting("espresso:audioInputID", StateKey.CURRENT_SOURCE, "i32_"),
        Setting("settings:/espresso/equalizerPreset", StateKey.CURRENT_PRESET, "i32_"),
        Setting(
            "ui:/mydevice/voiceEnhanceLevel",
            StateKey.VOICE_ENHANCEMENT_LEVEL,
            "i16_",
            Capability.VOICE_ENHANCEMENT_LEVEL,
        ),
        Setting(
            "ui:/settings/audio/centerSettings",
            StateKey.CENTER_SPEAKER_LEVEL,
            "i16_",
            Capability.CENTER_SPEAKER_LEVEL,
        ),
        Setting(
            "ui:/settings/audio/widthSettings",
            StateKey.SIDE_FIRING_LEVEL,
            "i16_",
            Capability.SIDE_FIRING_LEVEL,
        ),
        Setting(
            "ui:/settings/audio/heightSettings",
            StateKey.UP_FIRING_LEVEL,
            "i16_",
            Capability.UP_FIRING_LEVEL,
        ),
        Setting(
            "settings:/espresso/ambeoMode",
            StateKey.AMBEO_MODE_LEVEL,
            "i32_",
            Capability.AMBEO_MODE_LEVEL,
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
            "i16_",
            Capability.SUBWOOFER,
        ),
        Setting(
            "settings:/espresso/decoderStatus",
            StateKey.DECODER_STATUS,
            "espressoDecoderStatus",
            Capability.DECODER_STATUS,
        ),
    )

    # player:volume reports its native 0-100 scale, the display shows half of it.
    _FIXED_RANGES = frozenset({StateKey.VOLUME})
    _DEFAULT_RANGES = {
        **AmbeoSoundbar._DEFAULT_RANGES,
        StateKey.VOLUME: Range(0, 50),
        StateKey.SUBWOOFER_VOLUME: Range(-12, 12, unit="dB"),
        StateKey.LOGO_BRIGHTNESS: Range(1, 118, unit="%"),
        StateKey.DISPLAY_BRIGHTNESS: Range(1, 126, unit="%"),
    }

    _PRESETS = (
        Preset(0, "Neutral"),
        Preset(1, "Movies"),
        Preset(2, "Sport"),
        Preset(3, "News"),
        Preset(4, "Music"),
    )

    def __init__(self, transport: AmbeoTransport, *args, **kwargs) -> None:
        """Initialize and set up instance variables."""
        super().__init__(transport, *args, **kwargs)
        self._has_subwoofer: bool | None = None
        # Logo and display brightness share one path: serialize read-modify-write.
        self._brightness_lock = asyncio.Lock()

    def get_volume_step(self) -> float:
        """Get the volume step size."""
        return AMBEO_MAX_VOLUME_STEP

    async def stand_by(self) -> None:
        """Put the device into standby mode."""
        await self._transport.set_value("espresso:appRequestedStandby", "bool_", True)

    async def wake(self) -> None:
        """Wake the device from standby."""
        await self._transport.set_value("espresso:appRequestedOnline", "bool_", True)

    async def fetch_sources(self) -> list[Source]:
        """Fetch all available audio sources."""
        input_names, inputs = await asyncio.gather(
            self._transport.get_rows("settings:/espresso/inputNames", 0, 20),
            self._transport.get_rows("espresso:", 0, 20),
        )
        input_index_map = {
            row["title"].lower(): index
            for index, row in enumerate(inputs)
            if isinstance(row.get("title"), str)
        }
        sources = []
        for name in input_names:
            title = name.get("title")
            value = name.get("value")
            label = value.get("string_") if isinstance(value, dict) else None
            if not isinstance(title, str) or label is None:
                continue
            key = title.lower()
            if key in EXCLUDE_SOURCES_MAX or key not in input_index_map:
                continue
            sources.append(Source(input_index_map[key], label))
        return sources

    async def fetch_presets(self) -> list[Preset]:
        """Return the audio presets (fixed on this model)."""
        return list(self._PRESETS)

    async def _fetch_extra_state(self) -> dict[StateKey, Any]:
        """Return the logo and display brightness, which share one path."""
        try:
            brightness = await self._get_brightness()
        except AmbeoError as e:
            _LOGGER.debug("Brightness not available: %s", e)
            return {}
        return _brightness_state(brightness)

    async def _get_brightness(self) -> dict:
        """Get the logo and display brightness values."""
        brightness = await self._transport.get_value(
            self._BRIGHTNESS_PATH, "espressoBrightness"
        )
        return brightness if isinstance(brightness, dict) else {}

    async def _set_brightness(self, key: str, brightness: int) -> None:
        """Set one brightness value, keeping the other one unchanged."""
        async with self._brightness_lock:
            current = await self._get_brightness()
            value = {
                "ambeologo": current.get("ambeologo"),
                "display": current.get("display"),
                key: brightness,
            }
            if None in value.values():
                raise AmbeoResponseError(
                    f"Missing brightness value for path: {self._BRIGHTNESS_PATH}"
                )
            await self._transport.set_value(
                self._BRIGHTNESS_PATH, "espressoBrightness", value
            )

    async def get_display_brightness(self) -> int | None:
        """Get the display brightness."""
        return (await self._get_brightness()).get("display")

    async def set_display_brightness(self, brightness: int) -> None:
        """Set the display brightness."""
        await self._set_brightness("display", brightness)

    async def get_logo_brightness(self) -> int | None:
        """Get the Ambeo logo brightness."""
        return (await self._get_brightness()).get("ambeologo")

    async def set_logo_brightness(self, brightness: int) -> None:
        """Set the Ambeo logo brightness."""
        await self._set_brightness("ambeologo", brightness)

    async def reset_expert_settings(self) -> None:
        """Reset expert audio settings to defaults."""
        await self._transport.activate(
            "ui:/settings/audio/resetExpertSettings", {"type": "bool_", "bool_": True}
        )

    # Subwoofer.
    async def has_subwoofer(self) -> bool:
        """Check if a subwoofer is connected."""
        if self._has_subwoofer is None:
            try:
                data = await self._transport.get_data("ui:/settings/subwoofer/enabled")
            except AmbeoResponseError:
                data = None
            self._has_subwoofer = (
                bool(data.get("modifiable", False)) if isinstance(data, dict) else False
            )
        return self._has_subwoofer

    async def set_subwoofer_volume(self, volume: float) -> None:
        """Set the subwoofer volume (an integer on this model)."""
        await self._set(StateKey.SUBWOOFER_VOLUME, int(volume))

    def subscribed_paths(self) -> list[str]:
        """Return paths to subscribe to, filtered by device capabilities."""
        paths = super().subscribed_paths()
        if self.has_capability(Capability.MAX_DISPLAY) or self.has_capability(
            Capability.MAX_LOGO
        ):
            paths.append(self._BRIGHTNESS_PATH)
        return paths

    def process_event(self, path: str, item_value: dict) -> dict[StateKey, Any]:
        """Map an event path + itemValue to state updates."""
        if path == self._BRIGHTNESS_PATH:
            brightness = item_value.get("espressoBrightness")
            return _brightness_state(brightness) if isinstance(brightness, dict) else {}
        return super().process_event(path, item_value)
