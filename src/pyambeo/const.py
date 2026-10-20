"""Constants for Ambeo Soundbar API."""

from enum import StrEnum
from typing import NamedTuple

DEFAULT_PORT = 80
DEFAULT_TIMEOUT = 5

# ESPRESSO: MAX
MAX_SOUNDBAR = "AMBEO Soundbar Max"
EXCLUDE_SOURCES_MAX = ["aes"]
AMBEO_MAX_VOLUME_STEP = 0.02


# POPCORN: PLUS/MINI
PLUS_SOUNDBAR = "AMBEO Soundbar Plus"
MINI_SOUNDBAR = "AMBEO Soundbar Mini"
AMBEO_POPCORN_VOLUME_STEP = 0.01


class Capability(StrEnum):
    """Device capability identifiers."""

    AMBEO_LOGO = "AmbeoLogo"
    DECODER_STATUS = "DecoderStatus"
    AMBEO_MODE_LEVEL = "AmbeoModeLevel"
    BLUETOOTH_PAIRING = "AmbeoBluetoothPairing"
    CENTER_SPEAKER_LEVEL = "CenterSpeakerLevel"
    CENTER_VOLUME = "CenterVolume"
    CODEC_LED = "CodecLED"
    ECO_MODE = "EcoMode"
    LED_BAR = "LEDBar"
    MAX_DISPLAY = "AmbeoMaxDisplay"
    MAX_LOGO = "AmbeoMaxLogo"
    RESET_EXPERT_SETTINGS = "ResetExpertSettings"
    SIDE_FIRING_LEVEL = "SideFiringLevel"
    STANDBY = "standby"
    SUBWOOFER = "SubWoofer"
    UP_FIRING_LEVEL = "UpFiringLevel"
    NATIVE_VOLUME = "NativeVolume"
    VOICE_ENHANCEMENT_LEVEL = "VoiceEnhancementLevel"
    VOICE_ENHANCEMENT_TOGGLE = "VoiceEnhancementMode"


class StateKey(StrEnum):
    """Keys of the device state returned by fetch_state() and listen()."""

    VOLUME = "volume"
    MUTED = "muted"
    STATE = "state"
    CURRENT_SOURCE = "current_source"
    CURRENT_PRESET = "current_preset"
    PLAYER_DATA = "player_data"
    PLAY_TIME = "play_time"
    LED_BAR_BRIGHTNESS = "led_bar_brightness"
    CODEC_LED_BRIGHTNESS = "codec_led_brightness"
    LOGO_BRIGHTNESS = "logo_brightness"
    LOGO_STATE = "logo_state"
    DISPLAY_BRIGHTNESS = "display_brightness"
    NIGHT_MODE = "night_mode"
    AMBEO_MODE = "ambeo_mode"
    AMBEO_MODE_LEVEL = "ambeo_mode_level"
    SOUND_FEEDBACK = "sound_feedback"
    VOICE_ENHANCEMENT = "voice_enhancement"
    VOICE_ENHANCEMENT_LEVEL = "voice_enhancement_level"
    BLUETOOTH_PAIRING = "bluetooth_pairing"
    SUBWOOFER_STATUS = "subwoofer_status"
    SUBWOOFER_VOLUME = "subwoofer_volume"
    CENTER_SPEAKER_LEVEL = "center_speaker_level"
    SIDE_FIRING_LEVEL = "side_firing_level"
    UP_FIRING_LEVEL = "up_firing_level"
    CENTER_VOLUME = "center_volume"
    ECO_MODE = "eco_mode"
    DECODER_STATUS = "decoder_status"


class Setting(NamedTuple):
    """Describes a device setting, read, written and subscribed to by path.

    path       -- Device API path.
    data_key   -- Key used in the state dict.
    type_key   -- JSON type key of the value (e.g. "bool_", "i32_").
    capability -- Required device capability, or None if always available.
    sub_key    -- If set, the final value is value[sub_key]
                  (used when the type value is itself a dict).
    """

    path: str
    data_key: StateKey
    type_key: str
    capability: Capability | None = None
    sub_key: str | None = None
