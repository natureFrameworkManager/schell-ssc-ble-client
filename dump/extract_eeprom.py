#!/usr/bin/env python3
"""Extract the full EEPROM content from the client.py dump logs.

The dump logs (dump/client-dump1.txt, dump/client-dump2.txt) contain pairs of
lines like:

    Raw notify response data: 12 0a 99 06 86 02 00 ff ff 00 00 40 09 00 25 09 17 b3
    Starting extraction at address: 32

The raw response packet layout is (see parse_notify_response() in client.py):

    byte 0    : packet length (total number of bytes in the packet)
    byte 1    : opcode (0x0A == CMD_READ_EE_BY_ADDR)
    byte 2..N : raw response payload (the actual EEPROM bytes)

The "Starting extraction at address" line that directly follows a raw response
is the EEPROM address of the first payload byte, so `payload[i]` belongs to
address `address + i`.

The script checks that the addresses inside every log are strictly increasing
and that the packet length byte matches the actual number of bytes received.
The chunks of all logs are then merged into one 64 KiB EEPROM image.
"""

import argparse
import sys
from pathlib import Path

EEPROM_SIZE = 0x10000

CMD_READ_EE_BY_ADDR = 0x0A

RAW_PREFIX = "Raw notify response data:"
ADDRESS_PREFIX = "Starting extraction at address:"

DEFAULT_DUMP_DIR = Path(__file__).resolve().parent / "dump"
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "eeprom.bin"


def parse_dump(path: Path):
    """Parse one dump log and return its (address, payload) chunks.

    The addresses are checked to be strictly increasing.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc

    chunks = []
    previous_address = None

    for index, line in enumerate(lines):
        if not line.startswith(RAW_PREFIX):
            continue

        # --- Parse the raw packet bytes ---
        try:
            packet = bytes(int(value, 16) for value in line[len(RAW_PREFIX):].split())
        except ValueError as exc:
            raise ValueError(
                f"{path}:{index + 1}: malformed hex bytes: {line!r}"
            ) from exc

        if len(packet) < 2:
            raise ValueError(
                f"{path}:{index + 1}: packet is too short for a length and "
                f"opcode byte: {line!r}"
            )

        length = packet[0]
        opcode = packet[1]

        # Byte 0 is the packet length, so it must match the received byte count.
        if length != len(packet):
            raise ValueError(
                f"{path}:{index + 1}: packet length byte is 0x{length:02x} "
                f"({length}) but the packet contains {len(packet)} bytes"
            )

        # Only EEPROM read responses matter here.
        if opcode != CMD_READ_EE_BY_ADDR:
            continue

        # --- The next line carries the address of the first payload byte ---
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if not next_line.startswith(ADDRESS_PREFIX):
            raise ValueError(
                f"{path}:{index + 1}: EEPROM read response is not followed by "
                f"an address line, got: {next_line!r}"
            )

        try:
            address = int(next_line[len(ADDRESS_PREFIX):].strip(), 10)
        except ValueError as exc:
            raise ValueError(
                f"{path}:{index + 2}: malformed address: {next_line!r}"
            ) from exc

        # --- Check that the addresses are strictly increasing ---
        if previous_address is not None and address <= previous_address:
            raise ValueError(
                f"{path}:{index + 2}: address {address} (0x{address:04X}) is "
                f"not increasing, previous address was {previous_address} "
                f"(0x{previous_address:04X})"
            )
        previous_address = address

        chunks.append((address, packet[2:]))

    if not chunks:
        raise ValueError(f"{path}: no EEPROM read responses found")

    return chunks


def merge_chunks(all_chunks):
    """Merge the chunks of all logs into a single 64 KiB image.

    Returns the image (bytearray) and a bytearray marking which addresses were
    written. Overlapping chunks must contain the same data, otherwise an error
    is raised.
    """
    image = bytearray([0xFF]) * EEPROM_SIZE
    written = bytearray(EEPROM_SIZE)

    for path, chunks in all_chunks:
        for address, payload in chunks:
            if address < 0 or address + len(payload) > EEPROM_SIZE:
                raise ValueError(
                    f"{path}: chunk at 0x{address:04X} with {len(payload)} "
                    f"bytes falls outside the 64 KiB EEPROM"
                )
            for offset, value in enumerate(payload):
                current = address + offset
                if written[current]:
                    if image[current] != value:
                        raise ValueError(
                            f"{path}: conflicting byte at 0x{current:04X}: "
                            f"0x{image[current]:02X} != 0x{value:02X}"
                        )
                    continue
                image[current] = value
                written[current] = 1

    return image, written


def missing_ranges(written):
    """Return the list of (first, last) address ranges that were not written."""
    ranges = []
    start = None
    for address, is_written in enumerate(written):
        if not is_written:
            if start is None:
                start = address
        elif start is not None:
            ranges.append((start, address - 1))
            start = None
    if start is not None:
        ranges.append((start, EEPROM_SIZE - 1))
    return ranges


def format_hexdump(data: bytes):
    """Return a classic 16-bytes-per-line hexdump of data."""
    lines = []
    for offset in range(0, len(data), 16):
        row = data[offset:offset + 16]
        hex_part = " ".join(f"{byte:02x}" for byte in row)
        ascii_part = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in row)
        lines.append(f"{offset:04x}  {hex_part:<47}  |{ascii_part}|")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract the full EEPROM content from client.py dump logs."
    )
    parser.add_argument(
        "dumps",
        nargs="*",
        type=Path,
        help="Dump log(s) to parse. Defaults to every dump/client-dump*.txt file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output binary file (default: %(default)s).",
    )
    parser.add_argument(
        "--hex",
        action="store_true",
        help="Also print a hexdump of the EEPROM image to stdout.",
    )
    args = parser.parse_args(argv)

    dump_paths = args.dumps
    if not dump_paths:
        dump_paths = sorted(DEFAULT_DUMP_DIR.glob("client-dump*.txt"))
        if not dump_paths:
            parser.error(f"no dump files found in {DEFAULT_DUMP_DIR}")

    all_chunks = []
    try:
        for path in dump_paths:
            chunks = parse_dump(path)
            first_address = chunks[0][0]
            last_address, last_payload = chunks[-1]
            last_byte = last_address + len(last_payload) - 1
            print(
                f"{path}: {len(chunks)} chunks, "
                f"addresses 0x{first_address:04X}..0x{last_byte:04X}"
            )
            all_chunks.append((path, chunks))

        image, written = merge_chunks(all_chunks)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    covered = sum(written)

    ranges = missing_ranges(written)
    if ranges:
        shown = ", ".join(f"0x{first:04X}..0x{last:04X}" for first, last in ranges[:10])
        more = "" if len(ranges) <= 10 else f" (+{len(ranges) - 10} more)"
        print(
            f"Warning: only {covered}/{EEPROM_SIZE} bytes covered, "
            f"missing: {shown}{more}",
            file=sys.stderr,
        )

    try:
        args.output.write_bytes(image)
    except OSError as exc:
        parser.error(f"cannot write {args.output}: {exc}")

    print(
        f"Coverage: {covered}/{EEPROM_SIZE} bytes "
        f"({covered / EEPROM_SIZE * 100:.1f}%), "
        f"wrote {EEPROM_SIZE} bytes to {args.output}"
    )

    if args.hex:
        print(format_hexdump(image))

    return 0


if __name__ == "__main__":
    sys.exit(main())