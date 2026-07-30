"""Audio device listing and selection helpers using sounddevice."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List, Optional

from rich.console import Console
from rich.table import Table

console = Console(stderr=True)


@dataclass(frozen=True)
class AudioDeviceInfo:
    """Summary of a PortAudio device."""

    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float
    hostapi_name: str


def _hostapi_name(hostapi_index: int) -> str:
    try:
        import sounddevice as sd

        return str(sd.query_hostapis(hostapi_index)["name"])
    except Exception:
        return f"hostapi-{hostapi_index}"


def list_devices() -> List[AudioDeviceInfo]:
    """Return all available PortAudio devices."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is not installed. Activate the venv and "
            "pip install -r requirements.txt"
        ) from exc

    devices: List[AudioDeviceInfo] = []
    try:
        raw = sd.query_devices()
    except Exception as exc:  # PortAudioError and friends
        raise RuntimeError(
            f"Failed to query audio devices: {exc}. "
            "Check ALSA/PipeWire/PulseAudio and that PortAudio is installed."
        ) from exc

    for index, dev in enumerate(raw):
        devices.append(
            AudioDeviceInfo(
                index=index,
                name=str(dev["name"]),
                max_input_channels=int(dev["max_input_channels"]),
                max_output_channels=int(dev["max_output_channels"]),
                default_samplerate=float(dev["default_samplerate"]),
                hostapi_name=_hostapi_name(int(dev["hostapi"])),
            )
        )
    return devices


def print_devices(devices: Optional[List[AudioDeviceInfo]] = None) -> None:
    """Pretty-print input and output devices with rich."""
    if devices is None:
        devices = list_devices()

    table = Table(title="Audio devices (PortAudio / sounddevice)")
    table.add_column("Index", justify="right")
    table.add_column("Name")
    table.add_column("In", justify="right")
    table.add_column("Out", justify="right")
    table.add_column("Default SR", justify="right")
    table.add_column("Host API")

    for d in devices:
        table.add_row(
            str(d.index),
            d.name,
            str(d.max_input_channels),
            str(d.max_output_channels),
            f"{d.default_samplerate:.0f}",
            d.hostapi_name,
        )
    console.print(table)

    try:
        import sounddevice as sd

        defaults = sd.default.device
        console.print(
            f"[dim]Default input/output device indices: {defaults}[/dim]"
        )
    except Exception:
        pass


def get_device(index: int) -> AudioDeviceInfo:
    """Look up a device by index or raise a clear error."""
    devices = list_devices()
    for d in devices:
        if d.index == index:
            return d
    available = ", ".join(str(d.index) for d in devices) or "(none)"
    raise ValueError(
        f"Audio device index {index} not found. Available: {available}. "
        "Run: python -m src.audio_devices"
    )


def validate_input_device(index: int) -> AudioDeviceInfo:
    """Ensure the device supports capture."""
    device = get_device(index)
    if device.max_input_channels < 1:
        raise ValueError(
            f"Device {index} ({device.name!r}) has no input channels. "
            "Choose a microphone with python -m src.audio_devices"
        )
    return device


def validate_output_device(index: int) -> AudioDeviceInfo:
    """Ensure the device supports playback."""
    device = get_device(index)
    if device.max_output_channels < 1:
        raise ValueError(
            f"Device {index} ({device.name!r}) has no output channels. "
            "Choose a speaker with python -m src.audio_devices"
        )
    return device


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry: list audio devices."""
    del argv  # unused; argparse not needed for listing
    try:
        print_devices()
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
