"""Decoding of ``CMD_DIG_READ_BYTE`` responses (one control bit)."""

from __future__ import annotations

# address bit -> (name, label when set, label when clear)
BIT_STATES: dict[int, tuple[str, str, str]] = {
    0x01: ("Value", "open", "closed"),
    0x02: ("ThermalDesinfectionCycle", "active", "inactive"),
    0x04: ("StagnationFlush", "active", "inactive"),
    0x08: ("Dauerlauf", "active", "inactive"),
    0x10: ("CleaningStop", "active", "inactive"),
    0x20: ("Error", "present", "absent"),
    0x40: ("ErrorBattery", "low", "ok"),
    0x80: ("ThermalDesinfectionSpecial", "active", "inactive"),
}


def parse_bit_read(address_bit: int, value: int) -> tuple[str, str, bool]:
    """Return ``(name, label, active)`` for a single bit read response."""
    state = bool(value)
    labels = BIT_STATES.get(address_bit)
    if labels is None:
        return ("Unknown", "active" if state else "inactive", state)
    name, set_label, clear_label = labels
    return (name, set_label if state else clear_label, state)