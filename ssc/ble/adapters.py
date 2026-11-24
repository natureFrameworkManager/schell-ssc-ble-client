"""Adapter discovery and selection helpers around :mod:`simplepyble`.

No prompting happens here: :func:`select_adapter` takes a ``choose`` callback
so the CLI stays the only place that reads stdin.
"""

from __future__ import annotations

from collections.abc import Callable

import simplepyble

from ssc.constants import TEST_ADAPTER_IDENTIFIER

Adapter = simplepyble.Adapter
ChooseCallback = Callable[[list[Adapter]], "Adapter | None"]


def get_adapters() -> list[Adapter]:
    """All BLE adapters known to the operating system (may include a test stub)."""
    return simplepyble.Adapter.get_adapters()


def selectable_adapters(adapters: list[Adapter]) -> list[Adapter]:
    """Drop the ``test`` adapter that simplepyble reports on some platforms."""
    return [adapter for adapter in adapters if adapter.identifier() != TEST_ADAPTER_IDENTIFIER]


def select_adapter(adapters: list[Adapter], choose: ChooseCallback) -> Adapter | None:
    """Pick the adapter to use, asking the user only if there is a choice."""
    candidates = selectable_adapters(adapters)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    return choose(adapters)


def find_adapter(adapters: list[Adapter], selector: str) -> Adapter | None:
    """Find an adapter by identifier or address, case-insensitively."""
    wanted = selector.strip().lower()
    for adapter in selectable_adapters(adapters):
        if adapter.identifier().lower() == wanted or adapter.address().lower() == wanted:
            return adapter
    return None


def get_adapter(selector: str | None = None) -> Adapter | None:
    """Return a non-interactive adapter selection.

    With *selector* the adapter is matched by identifier or address.  Without a
    selector a single selectable adapter is used; if there are several, ``None``
    is returned and the caller should fall back to logging a configuration
    hint.
    """
    candidates = selectable_adapters(get_adapters())
    if selector:
        return find_adapter(candidates, selector)
    return candidates[0] if len(candidates) == 1 else None


def ensure_powered(adapter: Adapter) -> Adapter:
    """Power the adapter on if the platform reports it as off."""
    if not adapter.is_powered():
        adapter.power_on()
    return adapter


def endpoint_label(endpoint: Adapter | simplepyble.Peripheral) -> str:
    """Format an adapter or peripheral as ``identifier [address]``."""
    return f"{endpoint.identifier()} [{endpoint.address()}]"