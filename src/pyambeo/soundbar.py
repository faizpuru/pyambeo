"""Base class for Ambeo Soundbar devices."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Mapping
from typing import Any, ClassVar

import aiohttp

from .const import (
    BRIGHTNESS_RANGE_DEFAULT,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    Capability,
    Setting,
    StateKey,
)
from .exceptions import (
    AmbeoError,
    AmbeoResponseError,
    AmbeoUnsupportedModelError,
)
from .models import DeviceInfo, PlayerStatus, Preset, Source
from .transport import AmbeoTransport

_LOGGER = logging.getLogger(__name__)


_MODEL_PATH = "settings:/system/productName"
_NAME_PATH = "systemmanager:/deviceName"
_SERIAL_PATH = "settings:/system/serialNumber"
_VERSION_PATH = "ui:settings/firmwareUpdate/currentVersion"

# Populated by AmbeoSoundbar.__init_subclass__ from each subclass's `models`.
_MODEL_CLASSES: dict[str, type["AmbeoSoundbar"]] = {}


# Always present in fetch_state() (None when the device does not answer them).
_CORE_KEYS = (
    StateKey.VOLUME,
    StateKey.MUTED,
    StateKey.STATE,
    StateKey.CURRENT_SOURCE,
    StateKey.CURRENT_PRESET,
    StateKey.PLAYER_DATA,
)


def _unwrap(setting: Setting, value: Any) -> Any:
    """Return the setting value, extracting its sub_key if any."""
    if setting.sub_key is None:
        return value
    return value.get(setting.sub_key) if isinstance(value, dict) else None


async def _none_on_response_error[T](coro: Awaitable[T]) -> T | None:
    """Await coro, returning None if the device answered with an error."""
    try:
        return await coro
    except AmbeoResponseError as e:
        _LOGGER.debug("Ignoring response error: %s", e)
        return None


class AmbeoSoundbar:
    """Base class for Ambeo Soundbar devices.

    Use `await AmbeoSoundbar.connect(host, session)` to get the implementation
    matching the device model.
    """

    # Device models handled by the subclass.
    models: ClassVar[tuple[str, ...]] = ()
    capabilities: ClassVar[frozenset[Capability]] = frozenset()

    # Settings shared by all device models.
    _BASE_SETTINGS: ClassVar[tuple[Setting, ...]] = (
        Setting("player:volume", StateKey.VOLUME, "i32_"),
        Setting("settings:/mediaPlayer/mute", StateKey.MUTED, "bool_"),
        Setting("player:player/data/value", StateKey.PLAYER_DATA, "playLogicData"),
        Setting("player:player/data/playTime", StateKey.PLAY_TIME, "i64_"),
        Setting("powermanager:target", StateKey.STATE, "powerTarget", sub_key="target"),
    )
    # Model specific settings: read, written, polled and subscribed to by path.
    _SETTINGS: ClassVar[tuple[Setting, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the subclass for its device models."""
        super().__init_subclass__(**kwargs)
        for model in cls.models:
            _MODEL_CLASSES[model] = cls

    def __init__(
        self,
        transport: AmbeoTransport,
        info: DeviceInfo,
        sources: list[Source] | None = None,
        presets: list[Preset] | None = None,
    ) -> None:
        """Initialize the soundbar."""
        self._transport = transport
        self.info = info
        self.sources: list[Source] = sources or []
        self.presets: list[Preset] = presets or []

    @classmethod
    async def connect(
        cls,
        host: str,
        session: aiohttp.ClientSession,
        *,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> "AmbeoSoundbar":
        """Connect to a soundbar and return the implementation for its model.

        Loads the device info, sources and presets. When called on a subclass,
        raises AmbeoUnsupportedModelError if the device is another model.
        """
        transport = AmbeoTransport(host, session, port, timeout)
        model = await transport.get_value(_MODEL_PATH, "string_")
        impl = _MODEL_CLASSES.get(model)
        if impl is None or not issubclass(impl, cls):
            raise AmbeoUnsupportedModelError(model)
        _LOGGER.debug("Setting up the API for %s", model)

        name, serial, version = await asyncio.gather(
            _none_on_response_error(transport.get_value(_NAME_PATH, "string_")),
            _none_on_response_error(transport.get_value(_SERIAL_PATH, "string_")),
            _none_on_response_error(transport.get_value(_VERSION_PATH, "string_")),
        )
        soundbar = impl(transport, DeviceInfo(model, name, serial, version))
        soundbar.sources = await _none_on_response_error(soundbar.fetch_sources()) or []
        soundbar.presets = await _none_on_response_error(soundbar.fetch_presets()) or []
        return soundbar

    @property
    def host(self) -> str:
        """Return the device host."""
        return self._transport.host

    @property
    def port(self) -> int:
        """Return the device port."""
        return self._transport.port

    def has_capability(self, capability: Capability | str) -> bool:
        """Check if the device has a specific capability."""
        return capability in self.capabilities

    # Settings.
    def _available_settings(self) -> list[Setting]:
        """Return the settings of this device, filtered by capability."""
        return [
            s
            for s in (*self._BASE_SETTINGS, *self._SETTINGS)
            if s.capability is None or self.has_capability(s.capability)
        ]

    def _setting(self, key: StateKey) -> Setting:
        """Return the setting for a state key.

        Raises NotImplementedError when the model does not have it.
        """
        for setting in (*self._BASE_SETTINGS, *self._SETTINGS):
            if setting.data_key == key:
                return setting
        raise NotImplementedError(f"{key} is not supported by {type(self).__name__}")

    async def _read(self, setting: Setting) -> Any:
        """Read a setting value from the device."""
        value = await self._transport.get_value(setting.path, setting.type_key)
        return _unwrap(setting, value)

    async def _get(self, key: StateKey) -> Any:
        """Read the value of a state key from the device."""
        return await self._read(self._setting(key))

    async def _set(self, key: StateKey, value: Any) -> None:
        """Write the value of a state key to the device."""
        setting = self._setting(key)
        await self._transport.set_value(setting.path, setting.type_key, value)

    # State.
    async def fetch_state(self, max_concurrency: int = 3) -> dict[StateKey, Any]:
        """Fetch the full device state.

        Core values are always present (None when the device does not answer
        them). Optional values are only present when available. At most
        `max_concurrency` requests are in flight at once.
        Raises AmbeoConnectionError when the device cannot be reached.
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def limited[T](coro: Awaitable[T]) -> T:
            async with semaphore:
                return await coro

        async def fetch(setting: Setting) -> Any:
            if setting.data_key in _CORE_KEYS:
                return await _none_on_response_error(limited(self._read(setting)))
            try:
                return await limited(self._read(setting))
            except AmbeoError as e:
                _LOGGER.debug("%s not available: %s", setting.data_key, e)
                return None

        settings = self._available_settings()
        values, extra = await asyncio.gather(
            asyncio.gather(*(fetch(s) for s in settings)),
            limited(self._fetch_extra_state()),
        )
        state: dict[StateKey, Any] = dict.fromkeys(_CORE_KEYS)
        for setting, value in zip(settings, values, strict=True):
            if value is not None:
                state[setting.data_key] = value
        state.update(extra)
        return state

    async def _fetch_extra_state(self) -> dict[StateKey, Any]:
        """Return model-specific state values, fetched with a single request."""
        return {}

    def player_status(self, state: Mapping[str, Any]) -> PlayerStatus:
        """Return the effective playback status for a state snapshot."""
        power_map = {
            "playing": PlayerStatus.PLAYING,
            "paused": PlayerStatus.PAUSED,
            "stopped": PlayerStatus.IDLE,
            "online": PlayerStatus.ON,
            "networkStandby": PlayerStatus.STANDBY
            if self.has_capability(Capability.STANDBY)
            else PlayerStatus.IDLE,
        }
        power_status = power_map.get(state.get(StateKey.STATE) or "", PlayerStatus.ON)
        if power_status != PlayerStatus.ON:
            return power_status

        player_data = state.get(StateKey.PLAYER_DATA) or {}
        if player_data.get("state") == "paused":
            return PlayerStatus.PAUSED

        decoder_status = state.get(StateKey.DECODER_STATUS)
        if isinstance(decoder_status, dict):
            is_playing = (
                decoder_status.get("decoder_status", decoder_status.get("channels", 0))
                > 0
            )
            return PlayerStatus.PLAYING if is_playing else PlayerStatus.IDLE

        player_state = player_data.get("state")
        if player_state:
            return power_map.get(player_state, PlayerStatus.IDLE)
        return power_status

    # Events.
    def subscribed_paths(self) -> list[str]:
        """Return the paths to subscribe to, filtered by device capabilities."""
        return [s.path for s in self._available_settings()]

    def process_event(self, path: str, item_value: dict) -> dict[StateKey, Any]:
        """Map an event path + itemValue to state updates."""
        for setting in (*self._BASE_SETTINGS, *self._SETTINGS):
            if setting.path == path:
                value = _unwrap(setting, item_value.get(setting.type_key))
                return {setting.data_key: value} if value is not None else {}
        return {}

    async def listen(
        self, *, poll_timeout_ms: int = 30000, retry_delay: float = 30
    ) -> AsyncIterator[dict[StateKey, Any]]:
        """Yield state updates pushed by the device, forever.

        The event queue is recreated when lost; queue creation failures are
        retried every `retry_delay` seconds.
        """
        paths = self.subscribed_paths()
        _LOGGER.debug("Starting event listener for %d paths", len(paths))
        while True:
            try:
                queue_id = await self._transport.create_event_queue(paths)
            except AmbeoError as e:
                _LOGGER.debug("Failed to create event queue: %s", e)
                queue_id = None
            if not queue_id:
                _LOGGER.debug("No event queue, retrying in %ss", retry_delay)
                await asyncio.sleep(retry_delay)
                continue

            _LOGGER.debug("Event queue created: %s", queue_id)
            while (
                events := await self._transport.poll_event_queue(
                    queue_id, poll_timeout_ms
                )
            ) is not None:
                updates: dict[StateKey, Any] = {}
                for event in events:
                    if not isinstance(event, dict) or event.get("itemType") != "update":
                        continue
                    path = event.get("path")
                    item_value = event.get("itemValue")
                    if path and isinstance(item_value, dict):
                        updates.update(self.process_event(path, item_value))
                if updates:
                    yield updates
            _LOGGER.debug("Poll error, recreating event queue")

    # Device info.
    async def get_name(self) -> str | None:
        """Get the device name."""
        return await self._transport.get_value(_NAME_PATH, "string_")

    # Settings ranges.
    def get_volume_step(self) -> float:
        """Get the volume step size."""
        return 0.01

    def get_volume_max(self) -> int:
        """Get the maximum native volume value."""
        return 100

    def get_subwoofer_min_value(self) -> int:
        """Get the subwoofer minimum value."""
        return -10

    def get_subwoofer_max_value(self) -> int:
        """Get the subwoofer maximum value."""
        return 10

    def get_logo_brightness_range(self) -> tuple[int, int]:
        """Get the Ambeo logo brightness range."""
        return BRIGHTNESS_RANGE_DEFAULT

    def get_led_bar_brightness_range(self) -> tuple[int, int]:
        """Get the LED bar brightness range."""
        return BRIGHTNESS_RANGE_DEFAULT

    def get_display_brightness_range(self) -> tuple[int, int]:
        """Get the display brightness range."""
        return BRIGHTNESS_RANGE_DEFAULT

    def get_codec_led_brightness_range(self) -> tuple[int, int]:
        """Get the codec LED brightness range."""
        return BRIGHTNESS_RANGE_DEFAULT

    # Volume.
    async def get_volume(self) -> int | None:
        """Get the current volume."""
        return await self._get(StateKey.VOLUME)

    async def set_volume(self, volume: float) -> None:
        """Set the volume."""
        await self._set(StateKey.VOLUME, volume)

    # Mute.
    async def is_mute(self) -> bool | None:
        """Check if the device is muted."""
        return await self._get(StateKey.MUTED)

    async def set_mute(self, mute: bool) -> None:
        """Set the mute state."""
        await self._set(StateKey.MUTED, mute)

    # Power.
    async def get_state(self) -> str | None:
        """Get the current power state (online, networkStandby, …)."""
        return await self._get(StateKey.STATE)

    async def stand_by(self) -> None:
        """Put the device into standby mode."""
        raise NotImplementedError

    async def wake(self) -> None:
        """Wake the device from standby."""
        raise NotImplementedError

    async def reboot(self) -> None:
        """Reboot the device."""
        await self._transport.activate(
            "ui:/settings/system/restart", {"type": "bool_", "bool_": True}
        )

    # Playback.
    async def _player_control(self, control: str) -> None:
        """Send a player control command."""
        await self._transport.activate("player:player/control", {"control": control})

    async def play(self) -> None:
        """Send play command."""
        await self._player_control("play")

    async def pause(self) -> None:
        """Send pause command."""
        await self._player_control("pause")

    async def next(self) -> None:
        """Skip to the next track."""
        await self._player_control("next")

    async def previous(self) -> None:
        """Go back to the previous track."""
        await self._player_control("previous")

    async def get_play_time(self) -> int | None:
        """Get the current play time in milliseconds."""
        return await self._get(StateKey.PLAY_TIME)

    async def player_data(self) -> dict | None:
        """Get the current player data."""
        return await self._get(StateKey.PLAYER_DATA)

    # Sources.
    async def fetch_sources(self) -> list[Source]:
        """Fetch all available audio sources."""
        raise NotImplementedError

    async def get_current_source(self) -> Any:
        """Get the current audio source ID."""
        return await self._get(StateKey.CURRENT_SOURCE)

    async def set_source(self, source_id: Any) -> None:
        """Set the audio source."""
        await self._set(StateKey.CURRENT_SOURCE, source_id)

    # Presets.
    async def fetch_presets(self) -> list[Preset]:
        """Fetch all available audio presets."""
        raise NotImplementedError

    async def get_current_preset(self) -> Any:
        """Get the current audio preset ID."""
        return await self._get(StateKey.CURRENT_PRESET)

    async def set_preset(self, preset: Any) -> None:
        """Set the audio preset."""
        await self._set(StateKey.CURRENT_PRESET, preset)

    # Night mode.
    async def get_night_mode(self) -> bool | None:
        """Get the night mode state."""
        return await self._get(StateKey.NIGHT_MODE)

    async def set_night_mode(self, night_mode: bool) -> None:
        """Set the night mode state."""
        await self._set(StateKey.NIGHT_MODE, night_mode)

    # Ambeo mode.
    async def get_ambeo_mode(self) -> bool | None:
        """Get the Ambeo mode state."""
        return await self._get(StateKey.AMBEO_MODE)

    async def set_ambeo_mode(self, ambeo_mode: bool) -> None:
        """Set the Ambeo mode state."""
        await self._set(StateKey.AMBEO_MODE, ambeo_mode)

    async def get_ambeo_mode_level(self) -> int | None:
        """Get the Ambeo mode level (1=Light, 2=Regular, 3=Boost)."""
        return await self._get(StateKey.AMBEO_MODE_LEVEL)

    async def set_ambeo_mode_level(self, level: int) -> None:
        """Set the Ambeo mode level (1=Light, 2=Regular, 3=Boost)."""
        await self._set(StateKey.AMBEO_MODE_LEVEL, level)

    # Sound feedback.
    async def get_sound_feedback(self) -> bool | None:
        """Get the sound feedback state."""
        return await self._get(StateKey.SOUND_FEEDBACK)

    async def set_sound_feedback(self, state: bool) -> None:
        """Set the sound feedback state."""
        await self._set(StateKey.SOUND_FEEDBACK, state)

    # Voice enhancement.
    async def get_voice_enhancement(self) -> bool | None:
        """Get the voice enhancement state."""
        return await self._get(StateKey.VOICE_ENHANCEMENT)

    async def set_voice_enhancement(self, voice_enhancement_mode: bool) -> None:
        """Set the voice enhancement mode."""
        await self._set(StateKey.VOICE_ENHANCEMENT, voice_enhancement_mode)

    async def get_voice_enhancement_level(self) -> int | None:
        """Get the voice enhancement level."""
        return await self._get(StateKey.VOICE_ENHANCEMENT_LEVEL)

    async def set_voice_enhancement_level(self, level: int) -> None:
        """Set the voice enhancement level."""
        await self._set(StateKey.VOICE_ENHANCEMENT_LEVEL, level)

    # Subwoofer.
    async def has_subwoofer(self) -> bool:
        """Check if a subwoofer is connected."""
        raise NotImplementedError

    async def get_subwoofer_status(self) -> bool | None:
        """Get the subwoofer enabled status."""
        return await self._get(StateKey.SUBWOOFER_STATUS)

    async def set_subwoofer_status(self, status: bool) -> None:
        """Set the subwoofer enabled status."""
        await self._set(StateKey.SUBWOOFER_STATUS, status)

    async def get_subwoofer_volume(self) -> float | None:
        """Get the subwoofer volume."""
        return await self._get(StateKey.SUBWOOFER_VOLUME)

    async def set_subwoofer_volume(self, volume: float) -> None:
        """Set the subwoofer volume."""
        await self._set(StateKey.SUBWOOFER_VOLUME, volume)

    # Ambeo logo.
    async def get_logo_state(self) -> bool | None:
        """Get the Ambeo logo state."""
        return await self._get(StateKey.LOGO_STATE)

    async def change_logo_state(self, value: bool) -> None:
        """Change the Ambeo logo state."""
        await self._set(StateKey.LOGO_STATE, value)

    async def get_logo_brightness(self) -> int | None:
        """Get the Ambeo logo brightness."""
        return await self._get(StateKey.LOGO_BRIGHTNESS)

    async def set_logo_brightness(self, brightness: int) -> None:
        """Set the Ambeo logo brightness."""
        await self._set(StateKey.LOGO_BRIGHTNESS, brightness)

    # LED bar.
    async def get_led_bar_brightness(self) -> int | None:
        """Get the LED bar brightness."""
        return await self._get(StateKey.LED_BAR_BRIGHTNESS)

    async def set_led_bar_brightness(self, brightness: int) -> None:
        """Set the LED bar brightness."""
        await self._set(StateKey.LED_BAR_BRIGHTNESS, brightness)

    # Ambeo display.
    async def get_display_brightness(self) -> int | None:
        """Get the display brightness."""
        return await self._get(StateKey.DISPLAY_BRIGHTNESS)

    async def set_display_brightness(self, brightness: int) -> None:
        """Set the display brightness."""
        await self._set(StateKey.DISPLAY_BRIGHTNESS, brightness)

    # Codec LED.
    async def get_codec_led_brightness(self) -> int | None:
        """Get the codec LED brightness."""
        return await self._get(StateKey.CODEC_LED_BRIGHTNESS)

    async def set_codec_led_brightness(self, brightness: int) -> None:
        """Set the codec LED brightness."""
        await self._set(StateKey.CODEC_LED_BRIGHTNESS, brightness)

    # Bluetooth pairing.
    async def get_bluetooth_pairing_state(self) -> bool | None:
        """Get the Bluetooth pairing state."""
        return await self._get(StateKey.BLUETOOTH_PAIRING)

    async def set_bluetooth_pairing_state(self, state: bool) -> None:
        """Set the Bluetooth pairing state."""
        raise NotImplementedError

    # Speaker levels.
    async def get_center_speaker_level(self) -> int | None:
        """Get the center speaker level."""
        return await self._get(StateKey.CENTER_SPEAKER_LEVEL)

    async def set_center_speaker_level(self, level: int) -> None:
        """Set the center speaker level."""
        await self._set(StateKey.CENTER_SPEAKER_LEVEL, level)

    async def get_side_firing_level(self) -> int | None:
        """Get the side firing level."""
        return await self._get(StateKey.SIDE_FIRING_LEVEL)

    async def set_side_firing_level(self, level: int) -> None:
        """Set the side firing level."""
        await self._set(StateKey.SIDE_FIRING_LEVEL, level)

    async def get_up_firing_level(self) -> int | None:
        """Get the up firing level."""
        return await self._get(StateKey.UP_FIRING_LEVEL)

    async def set_up_firing_level(self, level: int) -> None:
        """Set the up firing level."""
        await self._set(StateKey.UP_FIRING_LEVEL, level)

    async def get_center_volume(self) -> float | None:
        """Get the center volume."""
        return await self._get(StateKey.CENTER_VOLUME)

    async def set_center_volume(self, volume: float) -> None:
        """Set the center volume."""
        await self._set(StateKey.CENTER_VOLUME, volume)

    # Eco mode.
    async def get_eco_mode(self) -> bool | None:
        """Get the eco mode state."""
        return await self._get(StateKey.ECO_MODE)

    # Decoder.
    async def get_decoder_status(self) -> dict | None:
        """Get the current audio decoder status."""
        return await self._get(StateKey.DECODER_STATUS)

    # Expert settings.
    async def reset_expert_settings(self) -> None:
        """Reset expert settings."""
        raise NotImplementedError
