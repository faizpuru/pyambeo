"""Data models for the Ambeo Soundbar API."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """Static information about a soundbar."""

    model: str
    name: str | None
    serial: str | None
    firmware_version: str | None


@dataclass(frozen=True, slots=True)
class Source:
    """An audio input (HDMI, Optical, …)."""

    id: str | int
    title: str
    # Device action path, when it differs from the ID (Plus/Mini only).
    path: str | None = None
    # False for inputs that are only shown while in use (AirPlay, Google Cast…).
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class Range:
    """Bounds of a numeric setting."""

    min: float
    max: float
    step: float = 1
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class Preset:
    """An audio preset / sound mode (Movies, Music, …)."""

    id: str | int
    title: str


class PlayerStatus(StrEnum):
    """Effective playback status derived from the device state."""

    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"
    ON = "on"
    STANDBY = "standby"
