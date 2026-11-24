import datetime
import time

import simplepyble

from queue import Queue

SCAN_DURATION = 2
SCAN_DEBUG_SSC = False
SCAN_SHOW_UNKNOWN = False
DEBUG_BYTES = True
SHOW_TELEMETRY = False

SERVICE_UUID                    = "89ce0100-56b1-40c1-be09-887f3c723d22"
DEVICE_INFO_CHARACTERISTIC      = "89ce0101-56b1-40c1-be09-887f3c723d22"
DEVICE_CONFIG_CHARACTERISTIC    = "89ce0102-56b1-40c1-be09-887f3c723d22"
SSC_CHARACTERISTIC              = "89ce0103-56b1-40c1-be09-887f3c723d22"
OTA_SERVICE_UUID                = "1D14D6EE-FD63-4FA1-BFA4-8F47B42119F0"
OTA_CONTROL_CHARACTERISTIC      = "F7BF3564-FB6D-4E53-88A4-5E37E0326063"
OTA_DATA_CHARACTERISTIC         = "984227F3-34FC-4045-A5D0-2C581F81A153"

CMD_READ_MODULE_INFO    = 0x01
CMD_DIG_WRITE_BIT       = 0x02
CMD_DIG_READ_BYTE       = 0x05
CMD_READ_EE_BY_ADDR     = 0x0A
CMD_WRITE_EE_BY_ADDR    = 0x0B
CMD_READ_ARRAY          = 0x1A

def bcd_to_int(value: int) -> int:
    """Convert one packed BCD byte (e.g. 0x24) into its decimal value (24)."""
    return ((value >> 4) & 0x0F) * 10 + (value & 0x0F)

# EEPROM regions [addr, len]
EEPROM_MAP = [
    [[32, 5], "EEPROM_ArticleNumber", lambda data: ("{0:X}-{1:X}-{2:X}-{3:X}-{4:X}".format(data[4], data[3], data[2], data[1], data[0]))],
    [[108, 1], "EEPROM_CleaningStop_enabled", lambda data: bool(data[0])],
    [[109, 2], "EEPROM_CleaningStop_runtime", lambda data: int.from_bytes(data, "little")],
    [[112, 2], "EEPROM_StagnationAndFollowUp", lambda data: int.from_bytes(data, "little")],
    [[114, 2], "EEPROM_FollowUpRuntime", lambda data: int.from_bytes(data, "little")],
    [[118, 1], "EEPROM_StagnationFlushInterval_mode", lambda data: bool(data[0] == 2)],
    [[119, 2], "EEPROM_StagnationFlushInterval_hours", lambda data: int.from_bytes(data, "little")],
    [[121, 2], "EEPROM_StagnationFlushInterval_runtime", lambda data: int.from_bytes(data, "little")],
    [[128, 1], "EEPROM_HybridMode", lambda data: bool(data[0])],
    [[129, 1], "EEPROM_HybridInterval", lambda data: int.from_bytes(data)],
    [[130, 1], "EEPROM_HybridRuntime", lambda data: int.from_bytes(data)],
    [[146, 1], "EEPROM_PreFlushMode", lambda data: bool(data[0])],
    [[147, 1], "EEPROM_PreFlushStart", lambda data: int.from_bytes(data)],
    [[148, 1], "EEPROM_SensorRange", lambda data: ["short", "mid", "long"][data[0]]],
    [[149, 1], "EEPROM_Scenario", lambda data: int.from_bytes(data)],
    [[158, 1], "EEPROM_PreFlushRuntime", lambda data: int.from_bytes(data)],
    [[160, None], "EEPROM_ThermalAndContinuous", lambda data: data],
    [[162, 1], "EEPROM_StadionMode", lambda data: bool(data[0])],
    [[163, 1], "EEPROM_OdourStopMode", lambda data: bool(data[0])],
    [[164, 1], "EEPROM_OdourStopInterval", lambda data: int.from_bytes(data)],
    [[167, 1], "EEPROM_StadionRuntime", lambda data: int.from_bytes(data)],
    [[168, 1], "EEPROM_ContinuousEnabled", lambda data: bool(data[0])],
    [[169, 2], "EEPROM_ContinuousRuntime", lambda data: int.from_bytes(data, "little")],
    [[171, 1], "EEPROM_ThermalEnabled", lambda data: bool(data[0])],
    [[172, 2], "EEPROM_ThermalRuntime", lambda data: int.from_bytes(data, "little")],
    [[174, 1], "EEPROM_OdourStopRuntime", lambda data: int.from_bytes(data)],
    [[176, 15], "EEPROM_Installer", lambda data: data.decode("cp1250").rstrip("\x00")], #CP1250 text, bytes outside 0x20–0x7A zeroed
    [[192, 3], "EEPROM_InstallationDate", lambda data: datetime.date(2000 + bcd_to_int(data[0]), bcd_to_int(data[1]), bcd_to_int(data[2]))], # BCD year/month/day, e.g. 26 07 24 -> 2026-07-24
    [[200, 1], "EEPROM_WcFlushDuration", lambda data: int.from_bytes(data)], # TODO: Lookup via WCTable
    [[208, 15], "EEPROM_Location", lambda data: data.decode("cp1250").rstrip("\x00")], #CP1250 text, bytes outside 0x20–0x7A zeroed
    [[256, None], "EEPROM_ConfigStart", lambda data: data],
    [[276, 1], "EEPROM_AmbiantSensorEnabled", lambda data: bool(data[0] != 0)],
    [[284, 2], "EEPROM_LongRangeMode", lambda data: int.from_bytes(data, "little")],
    [[288, 10], "EEPROM_RaweId", lambda data: data.decode("ascii").rstrip("\x00")], # ASCII
    [[336, None], "EEPROM_RangeMode", lambda data: data],
    [[347, 2], "EEPROM_LongRangeModeInterval", lambda data: int.from_bytes(data, "little")],
    [[349, 2], "EEPROM_UserDetectionModeInterval", lambda data: int.from_bytes(data, "little")],
    [[362, 2], "EEPROM_HandDetectTime", lambda data: int.from_bytes(data, "little")],
    [[370, 2], "EEPROM_SwitchOffInterval", lambda data: int.from_bytes(data, "little")],
    [[383, None], "EEPROM_ConfigEnd", lambda data: data],
    [[512, 12], "EEPROM_DeviceName", lambda data: data.decode("cp1250").rstrip("\x00")],
    [[528, 7], "EEPROM_DevicePassword", lambda data: data.decode("cp1250").rstrip("\x00")],
    [[535, 7], "EEPROM_Password", lambda data: data.decode("cp1250").rstrip("\x00")],
    [[589, 1], "EEPROM_StagnationFlushLog_nextIndex", lambda data: int.from_bytes(data) * 8 + 1024],
    [[590, 1], "EEPROM_ThermalDesinfectionLog_nextIndex", lambda data: int.from_bytes(data) * 8 + 2048],
    [[592, 1], "EEPROM_DauerlaufLog_nextIndex", lambda data: int.from_bytes(data) * 8 + 2176],
    [[593, 1], "EEPROM_CleaningStopLog_nextIndex", lambda data: int.from_bytes(data) * 8 + 2304],
    [[594, 1], "EEPROM_FlowRate", lambda data: int.from_bytes(data)],
    [[606, 1], "EEPROM_SensorExpertMode", lambda data: bool(data)],
    [[768, 112], "EEPROM_CalendarStart", lambda data: get_eeprom_calendar(data)],
    [[880, None], "EEPROM_CalendarEnd", lambda data: data],
    [[896, 8], "EEPROM_NeedBased", lambda data: bool(data[0] == 0x7F)], # same 8-byte layout, 0x7F sentinel in byte 0 marks need-based mode
]

def split_eeprom_calendar(data: bytes):
    """Split into 8 byte chunks"""
    """
    [0] bitmask: bit0=Mon .. bit6=Sun (scheduled mode); 0x7F = "need-based" sentinel; 0xFF = empty/disabled slot
    [1] hour       (0-23)
    [2] minute
    [3] second
    [4..5] runtime, seconds (uint16 LE)
    [6..7] reserved (0xFF 0xFF)
    """
    chunks = [data[i:i+8] for i in range(0, len(data), 8)]
    return chunks

def extract_eeprom_calendar_chunk(data: bytes):
    """Parse a single 8-byte calendar chunk"""
    if len(data) != 8:
        raise ValueError("Calendar chunk must be 8 bytes")
    bitmask = data[0]
    hour = data[1]
    minute = data[2]
    second = data[3]
    runtime = int.from_bytes(data[4:6], "little")
    reserved = data[6:8]
    return {
        "bitmask": bitmask,
        "hour": hour,
        "minute": minute,
        "second": second,
        "runtime": runtime,
        "reserved": reserved
    }

def map_eeprom_calendar_bitmask(bitmask_raw: int) -> tuple[str, str|None]:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if bitmask_raw == 0x7F:
        return ("Need-based", None)
    if bitmask_raw == 0xFF:
        return ("Empty", None)
    active_days = [day for i, day in enumerate(days) if bitmask_raw & (1 << i)]
    return ("Scheduled", ", ".join(active_days) if active_days else None)

def get_eeprom_calendar(data: bytes):
    chunks = split_eeprom_calendar(data)
    parsed_chunks = [extract_eeprom_calendar_chunk(chunk) for chunk in chunks]
    parsed_chunks = [dict(chunk, bitmask_mapped=map_eeprom_calendar_bitmask(chunk["bitmask"])) for chunk in parsed_chunks]
    return parsed_chunks

cmd_queries: dict[str, tuple[bytes, Queue[bytes]]] = {
    DEVICE_INFO_CHARACTERISTIC: (b"", Queue()),
    DEVICE_CONFIG_CHARACTERISTIC: (b"", Queue()),
    SSC_CHARACTERISTIC: (b"", Queue())
}

def extract_eeprom(data: bytes, starting_address: int = 108):
    print(f"Starting extraction at address: {starting_address}")
    for entry in EEPROM_MAP:
        address, length, name, parser = entry[0][0], entry[0][1], entry[1], entry[2]
        # Check if segment is longer than the available data
        # Also check if the segment could have partial data within the available range
        if length is not None and address + length > starting_address + len(data):
            print(f"Segment for {name} at address {address} exceeds data length")
            break
        if starting_address <= address:
            if length is None:
                print(f"Unknown segment for {name} at address {address}")
                continue
            segment_begin = address - starting_address
            segment_end = segment_begin + length
            segment_data = data[segment_begin:segment_end]
            print(f"Extracting {name} at address {address}: {segment_data.hex(" ")}")
            # Here you would add the actual extraction logic based on the parser and data
            try:
                print(f"{name} Parsed: {parser(segment_data)}")
            except Exception as e:
                print(f"Error parsing {name} at address {address}: {e}")

def generate_cmds_for_eeprom_dump(start: int = 0x0000, end: int = 0xFFFF, overlap: int = 0) -> list[bytes]:
    CHUNK_SIZE = 16
    cmds = []
    for address in range(start, end, CHUNK_SIZE - overlap):  # Assuming 16-byte chunks
        cmd = build_read_request(address, CHUNK_SIZE)
        cmds.append(cmd)
    return cmds

def generate_cmds_for_array_dimp(start: int = 0x00, end: int = 0xFF, overlap: int = 0) -> list[bytes]:
    CHUNK_SIZE = 1
    cmds = []
    for index in range(start, end, CHUNK_SIZE - overlap):
        cmd = build_read_array_request(index, CHUNK_SIZE)
        cmds.append(cmd)
    return cmds

def parse_reset_reason(reason: int) -> str:
    flags = []
    mapping = [
        (0x1, "PIN"),
        (0x2, "DOG"),
        (0x4, "SREQ"),
        (0x8, "LOCKUP"),
        (0x10000, "OFF"),
        (0x20000, "LPCOMP"),
        (0x40000, "DIF"),
        (0x80000, "NFC"),
    ]
    for mask, name in mapping:
        if reason & mask:
            flags.append(name)
    return "-".join(flags)

def extract_advertisement(data: bytes) -> dict[str, int|None|bytes|str]:
    """
    Byte 0: DeviceType
    Byte 1: DeviceSubType
    Byte 16: DeviceSubSubType
    Byte 2..13: Serial/DisplayName
    Byte 18: Battery voltage
    Last Byte: Battery (update?)
    """
    advertisement: dict[str, int|None|bytes] = {
        "device_type": None,
        "device_sub_type": None,
        "serial_display_name": None,
        "device_sub_sub_type": None,
        "battery_voltage_adv": None
    }
    advertisement["device_type"] = data[0]
    advertisement["device_sub_type"] = data[1]
    advertisement["serial_display_name"] = data[2:14]
    advertisement["device_sub_sub_type"] = data[16]
    advertisement["battery_voltage_adv"] = data[18]
    return advertisement

def calculate_battery(battery_voltage_adv: int) -> dict[str, float|int]:
    battery_voltage = battery_voltage_adv / 10
    if battery_voltage <= 4.5:
        battery_level = 0
    elif battery_voltage > 7.5: # saturated
        battery_level = 100
    elif battery_voltage > 6:
        battery_level = 100
    else:
        # Linear interpolation between 4.5V and 6 from 0% to 100% battery level
        battery_level = int((battery_voltage - 4.5) / (6 - 4.5) * 100)
    return {
        "battery_voltage": battery_voltage,
        "battery_level": battery_level
    }

def map_device_types(device_type: int|None, device_sub_type: int|None, device_sub_sub_type: int|None) -> dict[str, str]:
    device_type_mapping = {
        0x00: "Unrecognized",
        0x02: "Waschtisch",
        0x03: "Urinal",
        0x04: "WC",
        0x10: "CVD/Solenoid",
        0xF0: "BLE-Basic",
        0xF1: "BLE-Vitus",
        0xF2: "BLE-Montus-Flow",
    }
    device_subtype_waschtisch_mapping = {
        1: "Celis E²",
        10: "Puris E²",
        11: "Venus E²",
        12: "Xeris E²",
        20: "Vitus IR",
        21: "Grandis E",
        30: "Linus E",
        31: "Walis E"
    }
    device_subtype_urinal_mapping = {
        1: "Schelltronic",
        2: "Urinal"
    }
    device_subsubtype_high_mapping = {
        0: "",
        1: "S",
        2: "M",
        3: "L"
    }
    device_subsubtype_low_mapping = {
        0: "",
        1: "HD-K",
        2: "HD-M",
        3: "ND-M",
        4: "HD-T",
        5: "HD-SP",
        6: "HD-SP"
    }
    device_type_name = device_type_mapping.get(device_type if device_type is not None else 0x00, "Unknown")
    if device_type_name == "Waschtisch":
        device_subtype_name = device_subtype_waschtisch_mapping.get(device_sub_type if device_sub_type is not None else 0x00, "Unbekannte Armatur")
    elif device_type_name == "Urinal":
        device_subtype_name = device_subtype_urinal_mapping.get(device_sub_type if device_sub_type is not None else 0x00, "Unbekannte Armatur")
    else:
        device_subtype_name = ""
    device_subsubtype_high_name = device_subsubtype_high_mapping.get((device_sub_sub_type if device_sub_sub_type is not None else 0x00 & 0xF0) >> 4, "")
    device_subsubtype_low_name = device_subsubtype_low_mapping.get(device_sub_sub_type if device_sub_sub_type is not None else 0x00 & 0x0F, "")
    return {
        "device_type_name": device_type_name,
        "device_subtype_name": device_subtype_name,
        "device_subsubtype_high_name": device_subsubtype_high_name,
        "device_subsubtype_low_name": device_subsubtype_low_name
    }

def calculate_device_name(serial_display_name: bytes|None) -> str:
    """
    If [0]==0x0D: bytes [1..5] are a packed BCD-like article number ("{0:X1}{1:X2}{2:X2}{3:X2}{4:X2}", hyphenated)
    If [0]==0x0A: bytes [3..8] form a 6-byte hex serial
    Otherwise the full 12 bytes are a CP1250-encoded free-text name, null-trimmed
    """
    device_name = ""
    if serial_display_name:
        data = serial_display_name
        if data[0] == 0x0D:
            device_name = "{0:X1}-{1:X2}-{2:X2}-{3:X2}-{4:X2}".format(data[1], data[2], data[3], data[4], data[5])
        elif data[0] == 0x0A:
            device_name = "".join("{:02X}".format(b) for b in data[3:9])
        else:
            device_name = data.decode("cp1250").rstrip("\x00")
    return device_name

def get_advertisement(data: bytes) -> dict[str, int|None|bytes|str|float]:
    if DEBUG_BYTES:
        print(f"Raw advertisement data: {data.hex(' ')}")
    advertisement = extract_advertisement(data)
    advertisement.update(map_device_types(advertisement["device_type"], advertisement["device_sub_type"], advertisement["device_sub_sub_type"]))
    advertisement["device_name"] = calculate_device_name(advertisement.get("serial_display_name"))
    advertisement.update(calculate_battery(advertisement["battery_voltage_adv"]))
    return advertisement

def parse_notify_response(characteristic: str, data: bytes):
    """
    Byte 0: Length
    Byte 1: Command/Opcode
    Byte 2..N: Payload (depends on the command)
    """
    if DEBUG_BYTES:
        print(f"Raw notify response data: {data.hex(' ')}")
    length = data[0]
    if length != len(data):
        raise ValueError("Invalid data length")
    command = data[1]
    payload = data[2:]
    if cmd_queries.get(characteristic) is None:
        return None
    original_request = cmd_queries.get(characteristic)[0]
    cmd_queries[characteristic] = (b"", cmd_queries.get(characteristic)[1])
    if characteristic == DEVICE_INFO_CHARACTERISTIC:
        if command == CMD_READ_ARRAY:
            """Request: Payload[0] = Index"""
            if payload[0] == 0x00:
                return get_telemetry(payload[1:])
            if payload[0] == 0x01:
                return get_firmware(payload[1:])
    elif characteristic == DEVICE_CONFIG_CHARACTERISTIC:
        if original_request is None:
            print("Original request is None for config")
            return None
        if command == CMD_READ_EE_BY_ADDR: # -> 00 3.8
            """Request: Request[2] = Address HI, Request[3] = Address LO, Request[4] = Length of the data to read"""
            return "config read"
        if command == CMD_WRITE_EE_BY_ADDR:
            """Request: Request[2] = Address HI, Request[3] = Address LO, Request[4] = Length of the data to write, Request[5..N] = Data to write"""
            return "config write"
        if command == CMD_DIG_WRITE_BIT:
            """Request: Request[2] = Address, Request[3] = Value to write"""
            return "config bit_write"
        if command == CMD_READ_ARRAY:
            """Request: Request[2] = Index, Request[3] = Length of the array to read"""
            return "config read_array"
    elif characteristic == SSC_CHARACTERISTIC:
        if original_request is None:
            print("Original request is None for SSC")
            return None
        if command == CMD_READ_MODULE_INFO:
            """Request: Request[8..9] = App Version, Request[10..15] = serial"""
            return {
                "app_version": parse_version(original_request[8:10]),
                "serial": original_request[10:16]
            }
        if command == CMD_READ_EE_BY_ADDR:
            """Request: Request[2] = Address HI, Request[3] = Address LO, Request[4] = Length of the data to read"""
            original_address = (original_request[2] << 8) | original_request[3]
            if original_address <= 0x03FF:
                return extract_eeprom(payload, original_address)
            elif 0x0A00 <= original_address <= 0x1569:
                return get_eeprom_stats(payload, original_address)
            elif 0x0400 <= original_address <= 0x09FF:
                return get_eeprom_event_history(payload, original_address)
            return "read"
        if command == CMD_DIG_READ_BYTE:
            """Request: Request[2] = Address, Request[3] = Value"""
            return parse_bit_read(payload[0], payload[1])
        if command == CMD_WRITE_EE_BY_ADDR:
            """Request: Request[2] = Address HI, Request[3] = Address LO, Request[4] = Length of the data to write, Request[5..N] = Data to write"""
            return "write"
        if command == CMD_DIG_WRITE_BIT:
            """Request: Request[2] = Address, Request[3] = Value to write"""
            return "bit_write"
        if command == CMD_READ_ARRAY:
            """Request: Request[2] = Index, Request[3] = Length of the array to read"""
            if original_request[2] == 0x06:
                return get_lifetime_stats(payload[1:])
            if original_request[2] == 0x0B:
                return get_eeprom_today_stats(payload[1:])
        return "unknown ssc command: " + str(command)
    print("Unknown command:", command, "payload:", payload.hex(' '))
    return None

def parse_bit_read(address_bit: int, value: int) -> tuple[str, str, bool]:
    if address_bit == 0x01:
        return ("Value", "open" if bool(value) else "closed", bool(value))
    if address_bit == 0x02:
        return ("ThermalDesinfectionCycle", "active" if bool(value) else "inactive", bool(value))
    if address_bit == 0x04:
        return ("StagnationFlush", "active" if bool(value) else "inactive", bool(value))
    if address_bit == 0x08:
        return ("Dauerlauf", "active" if bool(value) else "inactive", bool(value))
    if address_bit == 0x10:
        return ("CleaningStop", "active" if bool(value) else "inactive", bool(value))
    if address_bit == 0x20:
        return ("Error", "present" if bool(value) else "absent", bool(value))
    if address_bit == 0x40:
        return ("ErrorBattery", "low" if bool(value) else "ok", bool(value))
    if address_bit == 0x80:
        return ("ThermalDesinfectionSpecial", "active" if bool(value) else "inactive", bool(value))
    return ("Unknown", "active" if bool(value) else "inactive", bool(value))

def get_date_from_address(address: int) -> datetime.datetime:
    day_of_year_0_based = (address - 2560) // 8
    current_year = datetime.datetime.now().year
    return datetime.datetime(current_year, 1, 1) + datetime.timedelta(days=day_of_year_0_based)

def get_eeprom_today_stats(data):
    if len(data) > 8:
        print("Warning: data length for today's stats is greater than 8 bytes")
    return get_normalized_and_calculated_stats_chunk(data, True)

def get_eeprom_stats(data: bytes, address: int):
    #split data into 8-byte chunks
    chunks = [data[i:i+8] for i in range(0, len(data), 8)]
    return [(get_date_from_address(address + i * 8), get_normalized_and_calculated_stats_chunk(chunk)) for i, chunk in enumerate(chunks)]

def get_eeprom_event_history(data: bytes, address: int):
    if 1024 <= address <= 2047:
        logtype = "stagnation flush"
    elif 2048 <= address <= 2175:
        logtype = "thermal desinfection"
    elif 2176 <= address <= 2303:
        logtype = "dauerlauf"
    elif 2304 <= address <= 2431:
        logtype = "cleaning stop"
    else:
        logtype = "unknown"
    #split data into 8-byte chunks
    chunks = [data[i:i+8] for i in range(0, len(data), 8)]
    return {
        "logtype": logtype,
        "entries": [get_normalized_and_calculated_event_history_chunk(chunk) for i, chunk in enumerate(chunks)]
    }

def extract_event_history_chunk(chunk: bytes):
    log_entry = {}
    log_entry["year_raw"] = chunk[0]
    log_entry["mode_raw"] = (chunk[1] & 0b11110000) >> 4
    log_entry["month"] = (chunk[1] & 0b00001111)
    log_entry["status_raw"] = (chunk[2] & 0b11110000) >> 4
    log_entry["day"] = (chunk[2] & 0b00001111)
    log_entry["hour"] = chunk[3]
    log_entry["minute"] = chunk[4]
    log_entry["second"] = chunk[5]
    log_entry["duration"] = int.from_bytes(chunk[6:8], byteorder='little') # seconds
    return log_entry

def map_log_entry_stats(status_raw: int) -> str:
    return "success" if status_raw == 0 else "error/interrupted"

def calculate_log_entry_year(year_raw: int) -> int:
    return 2000 + year_raw

def get_normalized_and_calculated_event_history_chunk(chunk: bytes):
    log_entry = extract_event_history_chunk(chunk)
    log_entry["year"] = calculate_log_entry_year(log_entry["year_raw"])
    log_entry["status"] = map_log_entry_stats(log_entry["status_raw"])
    return log_entry
    

def extract_telemetry(data: bytes):
    telemetry = {}
    telemetry["temperature"] = int.from_bytes(data[0:4], byteorder='little') # 32-bit, LE
    telemetry["battery_voltage_raw"] = int.from_bytes(data[4:6], byteorder='little') # 16-bit, LE
    telemetry["vcc_raw"] = int.from_bytes(data[6:8], byteorder='little') # 16-bit, LE
    telemetry["3.3v"] = int.from_bytes(data[8:10], byteorder='little') # 16-bit, LE
    telemetry["year"] = int.from_bytes(data[10:12], byteorder='little') # 16-bit, LE
    telemetry["month"] = data[12] # 8-bit
    telemetry["day"] = data[13] # 8-bit
    telemetry["hour"] = data[14] # 8-bit
    telemetry["minute"] = data[15] # 8-bit
    telemetry["second"] = data[16] # 8-bit
    return telemetry

def extract_firmware(data: bytes) -> dict[str, bytes|None|str]:
    firmware = {}
    firmware["hardware_version_raw"] = data[0:2]
    firmware["bootloader_version_raw"] = data[2:4]
    firmware["reset_reason_raw"] = data[11:15]
    return firmware

def get_telemetry(data: bytes):
    telemetry = extract_telemetry(data)
    telemetry["battery"] = calculate_battery(telemetry["battery_voltage_raw"])
    telemetry["vcc"] = calculate_voltage(telemetry["vcc_raw"])
    telemetry["datetime"] = calculate_date_time(telemetry["year"], telemetry["month"], telemetry["day"], telemetry["hour"], telemetry["minute"], telemetry["second"])
    return telemetry

def calculate_voltage(vcc: int) -> float:
    return vcc / 1000.0 # Volts

def calculate_date_time(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, second)

def get_firmware(data: bytes) -> dict[str, str|None|bytes]:
    firmware = extract_firmware(data)
    firmware.update(map_version(firmware["hardware_version_raw"], firmware["bootloader_version_raw"]))
    firmware["reset_reason"] = parse_reset_reason(firmware["reset_reason_raw"])
    return firmware

def map_version(hardware_version: bytes, bootload_version: bytes) -> dict[str, str]:
    return {
        "hardware_version": parse_version(hardware_version),
        "bootloader_version": parse_version(bootload_version)
    }

def parse_version(data: bytes):
    if data[0] & 0b10000000:
        return f"T{data[0]&0x7F:D2}.{data[1]:D2}"
    else:
        return f"V{data[0]:D2}.{data[1]:D2}"

def extract_stats(data: bytes):
    stats = {}
    stats["count-normal"] = int.from_bytes(data[0:2], byteorder='little')
    stats["runtime-normal"] = int.from_bytes(data[2:4], byteorder='little')
    stats["count-stagnation"] = data[4]
    stats["runtime-stagnation"] = int.from_bytes(data[5:7], byteorder='little')
    stats["aerator-liters-per-minute"] = data[7]
    return stats

def normalize_stats(stats: dict):
    for key in ["count-normal", "runtime-normal", "runtime-stagnation"]:
        if stats[key] == 0xFFFF:
            stats[key] = 0
    for key in ["count-stagnation", "aerator-liters-per-minute"]:
        if stats[key] == 0xFF:
            stats[key] = 0
    return stats

def calculate_stats(stats: dict):
    stats["consumption-normal-liters"] = (stats["runtime-normal"] / 60) * stats["aerator-liters-per-minute"]
    stats["consumption-stagnation-liters"] = (stats["runtime-stagnation"] / 60) * stats["aerator-liters-per-minute"]
    return stats

def handle_today_variant(data: bytes):
    """
    Switch first two 16-bit fields as they are BE, keep the rest as is
    """
    if len(data) < 4:
        raise ValueError("Data too short for today variant")
    result = bytearray(data)
    result[0], result[1] = data[1], data[0]
    result[2], result[3] = data[3], data[2]
    return bytes(result)

def get_normalized_and_calculated_stats_chunk(data: bytes, today_variant: bool = False):
    if DEBUG_BYTES:
        print(f"Original stats data: {data.hex(' ')}")
    if today_variant:
        data = handle_today_variant(data)
    stats = extract_stats(data)
    stats = normalize_stats(stats)
    stats = calculate_stats(stats)
    return stats

def get_lifetime_stats(data: bytes):
    if DEBUG_BYTES:
        print(f"Lifetime stats data: {data.hex(' ')}")
    stats = {}
    stats["count-restart"] = int.from_bytes(data[0:4], byteorder='little')
    stats["count-lifetime"] = int.from_bytes(data[4:8], byteorder='little')
    return stats

def build_request(command: int, payload: bytes):
    request = bytearray()
    request.append( 1 + 1 + len(payload)) # Length = Byte for length + Byte for command + Payload length
    request.append(command)
    request.extend(payload)
    if DEBUG_BYTES:
        print(f"Built request: {request.hex(' ')}")
    return bytes(request)

def build_read_request(address: int, length: int):
    if address >= 0x4000:
        print("Warning: Actual address space only goes up to 0x4000. Afterwards it is wrapped around")
    if address < 0 or address > 0xFFFF:
        raise ValueError("Address must be between 0 and 65535")
    if length == 0:
        raise ValueError("Length cannot be zero")
    if length > 0xFF:
        raise ValueError("Length cannot exceed 255 bytes")
    payload = bytearray()
    payload.append(address >> 8) # 16-bit address, high byte first
    payload.append(address & 0xFF) # low byte
    payload.append(length)
    if DEBUG_BYTES:
        print(f"Read request payload: {payload.hex(" ")}")
    return build_request(CMD_READ_EE_BY_ADDR, bytes(payload))

def build_write_request(address: int, data: bytes):
    if len(data) == 0:
        raise ValueError("Data to write cannot be empty")
    if len(data) > 0xFF:
        raise ValueError("Data to write cannot exceed 255 bytes")
    if address < 0 or address > 0xFFFF:
        raise ValueError("Address must be between 0 and 65535")
    payload = bytearray()
    payload.append(address >> 8) # 16-bit address, high byte first
    payload.append(address & 0xFF) # low byte
    payload.append(len(data)) # length of the data to write
    payload.extend(data)
    if DEBUG_BYTES:
        print(f"Write request payload: {payload.hex(' ')}")
    return build_request(CMD_WRITE_EE_BY_ADDR, bytes(payload))

def build_write_bit_request(bit_address: int, value: int):
    """
    Address 1: Valve state (open/close)
    Address 2: LED red
    Address 4: LED orange
    Address 5: Thermal desinfection
    Address 6: Stagnation flush
    Address 7: Continous flush ("Dauerlauf")
    Address 8: Cleaning stop
    Address 9: TD special
    """
    if bit_address < 0 or bit_address > 0xFF:
        raise ValueError("Bit address must be between 0 and 255")
    if value not in (0, 1):
        raise ValueError("Value must be 0 or 1")
    payload = bytearray()
    payload.append(bit_address)
    payload.append(value)
    if DEBUG_BYTES:
        print(f"Write bit request payload: {payload.hex(' ')}")
    return build_request(CMD_DIG_WRITE_BIT, bytes(payload))

def build_read_array_request(index: int, length: int):
    if length == 0:
        raise ValueError("Length cannot be zero")
    if length > 0xFF:
        raise ValueError("Length cannot exceed 255 bytes")
    if index < 0 or index > 0xFF:
        raise ValueError("Index must be between 0 and 255")
    payload = bytearray()
    payload.append(index)
    payload.append(length)
    if DEBUG_BYTES:
        print(f"Read array request payload: {payload.hex(' ')}")
    return build_request(CMD_READ_ARRAY, bytes(payload))

def get_device_services(device: simplepyble.Peripheral):
    print("Successfully connected, listing services...")
    services = device.services()
    service_characteristic_pair = []
    for service in services:
        print(f"    Service UUID: {service.uuid()}")
        for characteristic in service.characteristics():
            print(f"      Characteristic UUID: {characteristic.uuid()}")
            print(f"        Characteristic capabilities: {characteristic.capabilities()}")
            print(f"        Characteristic writable command: {characteristic.can_write_command()}")
            print(f"        Characteristic writable request: {characteristic.can_write_request()}")
            service_characteristic_pair.append((service.uuid(), characteristic.uuid()))

    # Query the user to pick a service/characteristic pair
    print("Please select a service/characteristic pair:")
    for i, (service_uuid, characteristic) in enumerate(service_characteristic_pair):
        print(f"{i}: {service_uuid} {characteristic}")

    choice = int(input("Enter choice: "))
    service_uuid, characteristic_uuid = service_characteristic_pair[choice]
    return service_uuid, characteristic_uuid

def output_info_notification(data: bytes):
    if (data[2] == 0x00 and not SHOW_TELEMETRY):
        return
    print(f"Info Notification: {data.hex(' ')}")
    parsed = parse_notify_response(DEVICE_INFO_CHARACTERISTIC, data)
    print(f"Parsed: {parsed}")

def query_device(device: simplepyble.Peripheral):
    print(f"Querying device: {device.identifier()} [{device.address()}]")
    if device.is_connected():
        print("    Device is connected")

        if not device.is_connected():
            print("    Device is not connected")
            device.connect()

        print("    Device is now connected")

        device.notify(SERVICE_UUID, DEVICE_INFO_CHARACTERISTIC, output_info_notification)
        device.notify(SERVICE_UUID, SSC_CHARACTERISTIC, lambda data: print(f"SSC Notification: {data.hex(' ')}\nParsed: {parse_notify_response(SSC_CHARACTERISTIC, data)}"))
        print("Notification handler set up")

        # cmd_queries[SSC_CHARACTERISTIC] = (build_read_array_request(0x00, 0xFF), cmd_queries[SSC_CHARACTERISTIC][1])
        # device.write_command(SERVICE_UUID, SSC_CHARACTERISTIC, cmd_queries[SSC_CHARACTERISTIC][0])
        # print("Read request sent")

        eeprom_cmds = generate_cmds_for_eeprom_dump(0x0000, 0x3FFF)
        for cmd in eeprom_cmds:
            cmd_queries[SSC_CHARACTERISTIC][1].put(cmd)
        
        # array_cmds = generate_cmds_for_array_dimp(0x08, 0xff)
        # for cmd in array_cmds:
        #     cmd_queries[SSC_CHARACTERISTIC][1].put(cmd)

        while not cmd_queries[SSC_CHARACTERISTIC][1].empty():
            if cmd_queries[SSC_CHARACTERISTIC][0] == b"":
                print("---\nReceived previous response, sending next command...")
                cmd = cmd_queries[SSC_CHARACTERISTIC][1].get()
                cmd_queries[SSC_CHARACTERISTIC] = (cmd, cmd_queries[SSC_CHARACTERISTIC][1])
                device.write_command(SERVICE_UUID, SSC_CHARACTERISTIC, cmd_queries[SSC_CHARACTERISTIC][0])
            else:
                print(f"Waiting for previous command to be processed... | {cmd_queries[SSC_CHARACTERISTIC][1].qsize()} Waiting")
            time.sleep(0.1)
        time.sleep(1)

    else:
        print("    Device is not connected")

def display_SE2_device(device: simplepyble.Peripheral):
    print(f"Found SSC device: {device.identifier()} [{device.address()}]")
    if SCAN_DEBUG_SSC:
        print(f"    Connectable: {'Yes' if device.is_connectable() else 'No'}")
        print(f'    Address Type: {device.address_type()}')
        print(f'    Tx Power: {device.tx_power()} dBm')

        manufacturer_data = device.manufacturer_data()
        for manufacturer_id, value in manufacturer_data.items():
            print(f"    Manufacturer ID: {manufacturer_id}")
            print(f"    Manufacturer data: {value.hex(' ')}")

        services = device.services()
        for service in services:
            print(f"    Service UUID: {service.uuid()}")
            print(f"    Service data: {service.data().hex(' ')}")
    manufacturer_data = device.manufacturer_data()
    for manufacturer_id, value in manufacturer_data.items():
        print(get_advertisement(value))

def display_unknown_device(peripheral: simplepyble.Peripheral):
    print(f"Found unknown device ({'Connectable' if peripheral.is_connectable() else 'Non-Connectable'}): {peripheral.identifier()} [{peripheral.address()}]")
    print(f'    Address Type: {peripheral.address_type()}')
    print(f'    Tx Power: {peripheral.tx_power()} dBm')

    manufacturer_data = peripheral.manufacturer_data()
    for manufacturer_id, value in manufacturer_data.items():
        print(f"    Manufacturer ID: {manufacturer_id}")
        print(f"    Manufacturer data: {value.hex(' ')}")

    services = peripheral.services()
    for service in services:
        print(f"    Service UUID: {service.uuid()}")
        print(f"    Service data: {service.data().hex(" ")}")

adapters = simplepyble.Adapter.get_adapters()

if len(adapters) == 0 :
    print("No adapters found")
    exit()
if len(adapters) == 1 and adapters[0].identifier() == "test":
    print("Only test adapter found")
    exit()
elif len([adapter for adapter in adapters if adapter.identifier() != "test"]) == 1:
    adapter = [adapter for adapter in adapters if adapter.identifier() != "test"][0]
else:
    print("Multiple adapters found")
    for i, adapter in enumerate(adapters):
        if adapter.identifier() != "test":
            print(f"{i}: {adapter.identifier()} [{adapter.address()}]")
    choice = int(input("Enter choice: "))
    adapter = adapters[choice]

if not adapter:
    print("No valid adapter selected")
    exit()
print(f"Using adapter: {adapter.identifier()} [{adapter.address()}]")

adapter.set_callback_on_scan_start(lambda: print("Scan started"))
adapter.set_callback_on_scan_stop(lambda: print("Scan stopped"))
adapter.set_callback_on_scan_found(lambda device: print(f"Discovered {'SSC' if 'SE2' in device.identifier() else 'unknown'} device: {device.identifier()} [{device.address()}]") if (('SE2' in device.identifier() and SCAN_DEBUG_SSC) or ('SE2' not in device.identifier() and SCAN_SHOW_UNKNOWN)) else None)

print(f"Scan for {SCAN_DURATION} seconds")
adapter.scan_for(SCAN_DURATION * 1000)

devices = adapter.scan_get_results()
print(f"Found {len(devices)} devices, including {len([device for device in devices if 'SE2' in device.identifier()])} SSC devices")
for device in [device for device in devices if 'SE2' in device.identifier()]:
    display_SE2_device(device)
if SCAN_SHOW_UNKNOWN:
    for device in [device for device in devices if 'SE2' not in device.identifier()]:
        display_unknown_device(device)

if len([device for device in devices if 'SE2' in device.identifier()]) == 0:
    print("No SSC devices found")
    exit()

print("Select a SSC device(s) to connect to [split by comma]:")
ssc_devices = [device for device in devices if 'SE2' in device.identifier()]
for i, device in enumerate(ssc_devices):
    print(f"{i}: {device.identifier()} [{device.address()}]")
choice = input("Enter choice: ")
selected_devices = [ssc_devices[int(i)] for i in choice.split(",")]

for device in selected_devices:
    try:
        print(f"Connecting to {device.identifier()} [{device.address()}]")
        device.connect()
        query_device(device)
    except Exception as e:
        print(f"Failed to connect to {device.identifier()} [{device.address()}]: {e}")
    finally:
        if device.is_connected():
            device.disconnect()