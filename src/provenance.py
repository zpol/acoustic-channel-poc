"""Provenance labels for generated / simulated / physical artefacts."""

from __future__ import annotations

from enum import Enum


class Provenance(str, Enum):
    GENERATED_TX = "GENERATED_TX"
    SIMULATED_RX = "SIMULATED_RX"
    PHYSICAL_RX = "PHYSICAL_RX"
    PHYSICAL_REPLAY = "PHYSICAL_REPLAY"

    def plot_title(self, base: str) -> str:
        return f"{base} [{self.value}]"
