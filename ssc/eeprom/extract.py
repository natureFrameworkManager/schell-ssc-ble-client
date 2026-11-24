"""Field extraction from an EEPROM read response."""

from __future__ import annotations

import logging

from ssc.config import Options
from ssc.eeprom.layout import FIELDS

logger = logging.getLogger(__name__)


def extract_eeprom(
    data: bytes,
    starting_address: int = 108,
    options: Options | None = None,
) -> dict[str, object]:
    """Decode every known field that lies inside *data*.

    *starting_address* is the EEPROM address of ``data[0]`` (taken from the
    request that triggered the response).  *options* controls the "segment does
    not fit" warnings; extraction itself is unaffected.
    """
    options = options or Options()
    found_fields: dict[str, object] = {}
    logger.debug("Starting extraction at address: %s", starting_address)
    for field in FIELDS:
        # Stop at the first field that is not fully contained in *data*; all
        # following fields start at a higher address, so none would fit either.
        if field.address + field.length > starting_address + len(data):
            if options.warnings_eeprom:
                logger.warning(
                    "Segment for %s at address %s exceeds data length",
                    field.name,
                    field.address,
                )
            break
        if field.address < starting_address:
            continue
        offset = field.address - starting_address
        segment = data[offset:offset + field.length]
        logger.debug(
            "Extracting %s at address %s: %s",
            field.name,
            field.address,
            segment.hex(" "),
        )
        try:
            parsed = field.loads(segment)
        except Exception as exc:  # noqa: BLE001 - one bad field must not abort the dump
            logger.error("Error parsing %s at address %s: %s", field.name, field.address, exc)
            continue
        logger.debug("%s Parsed: %s", field.name, parsed)
        found_fields[field.name] = parsed
    return found_fields