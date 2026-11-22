import simplepyble

SCAN_DURATION = 10
SCAN_DEBUG_SSC = True
SCAN_SHOW_UNKNOWN = True

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

# EEPROM regions [addr, len]
EEPROM_ArticleNumber = [32, 5],
EEPROM_CleaningStop_enabled = [108, 1],
EEPROM_CleaningStop_runtime = [109, 2],
EEPROM_StagnationAndFollowUp = [112, 2],
EEPROM_FollowUpRuntime = [114, 2],
EEPROM_StagnationFlushInterval_mode = [118, 1],
EEPROM_StagnationFlushInterval_hours = [119, 2],
EEPROM_StagnationFlushInterval_runtime = [121, 2],
EEPROM_HybridMode = [128, 1],
EEPROM_HybridInterval = [129, 1],
EEPROM_HybridRuntime = [130, 1],
EEPROM_PreFlushMode = [146, 1],
EEPROM_PreFlushStart = [147, 1],
EEPROM_SensorRange = [148, 1],
EEPROM_Scenario = [149, 1],
EEPROM_PreFlushRuntime = [158, 1],
EEPROM_ThermalAndContinuous = [160, None],
EEPROM_StadionMode = [162, 1],
EEPROM_OdourStopMode = [163, 1],
EEPROM_OdourStopInterval = [164, 1],
EEPROM_StadionRuntime = [167, 1],
EEPROM_ContinuousEnabled = [168, 1],
EEPROM_ContinuousRuntime = [169, 2],
EEPROM_ThermalEnabled = [171, 1],
EEPROM_ThermalRuntime = [172, 2],
EEPROM_OdourStopRuntime = [174, 1],
EEPROM_Installer = [176, 15],
EEPROM_InstallationDate = [192, 3],
EEPROM_WcFlushDuration = [200, 1],
EEPROM_Location = [208, 15],
EEPROM_ConfigStart = [256, None],
EEPROM_AmbiantSensorEnabled = [276, 1],
EEPROM_LongRangeMode = [284, 2],
EEPROM_RaweId = [288, 10],
EEPROM_RangeMode = [336, None],
EEPROM_LongRangeModeInterval = [347, 2],
EEPROM_UserDetectionModeInterval = [349, 2],
EEPROM_HandDetectTime = [362, 2],
EEPROM_SwitchOffInterval = [370, 2],
EEPROM_ConfigEnd = [383, None],
EEPROM_DeviceName = [512, 12],
EEPROM_DevicePassword = [528, 7],
EEPROM_Password = [535, 7],
EEPROM_FlowRate = [594, 1],
EEPROM_SensorExpertMode = [606, 1],
EEPROM_CalendarStart = [768, 112],
EEPROM_CalendarEnd = [880, None],
EEPROM_NeedBased = [896, 8],



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

def parse_advertisement(data: bytes):
    """
    Byte 0: DeviceType
    Byte 1: DeviceSubType
    Byte 16: DeviceSubSubType
    Byte 2..13: Serial/DisplayName
    Byte 18: Battery voltage
    Last Byte: Battery (update?)
    """
    advertisement = {}
    advertisement["device_type"] = data[0]
    advertisement["device_sub_type"] = data[1]
    advertisement["serial_display_name"] = data[2:14].decode("utf-8").rstrip("\x00")
    advertisement["device_sub_sub_type"] = data[16]
    advertisement["battery_voltage_adv"] = data[18]
    return advertisement

def calculate_battery_advertisement(advertisement: dict):
    advertisement["battery_voltage"] = advertisement.get("battery_voltage_adv", 0) / 10
    if advertisement["battery_voltage"] <= 4.5:
        advertisement["battery_level"] = 0
    elif advertisement["battery_voltage"] > 7.5: # saturated
        advertisement["battery_level"] = 100
    elif advertisement["battery_voltage"] > 6:
        advertisement["battery_level"] = 100
    else:
        # Linear interpolation between 4.5V and 6 from 0% to 100% battery level
        advertisement["battery_level"] = int((advertisement["battery_voltage"] - 4.5) / (6 - 4.5) * 100)
    return advertisement

def map_device_types_advertisement(advertisement: dict):
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
    advertisement["device_type_name"] = device_type_mapping.get(advertisement.get("device_type", 0x00), "Unknown")
    if advertisement["device_type_name"] == "Waschtisch":
        advertisement["device_subtype_name"] = device_subtype_waschtisch_mapping.get(advertisement.get("device_sub_type", 0x00), "Unbekannte Armatur")
    elif advertisement["device_type_name"] == "Urinal":
        advertisement["device_subtype_name"] = device_subtype_urinal_mapping.get(advertisement.get("device_sub_type", 0x00), "Unbekannte Armatur")
    else:
        advertisement["device_subtype_name"] = ""
    advertisement["device_subsubtype_high_name"] = device_subsubtype_high_mapping.get((advertisement.get("device_sub_sub_type", 0x00) & 0xF0) >> 4, "")
    advertisement["device_subsubtype_low_name"] = device_subsubtype_low_mapping.get(advertisement.get("device_sub_sub_type", 0x00) & 0x0F, "")
    return advertisement

def calculate_device_name_advertisement(advertisement: dict):
    """
    If [0]==0x0D: bytes [1..5] are a packed BCD-like article number ("{0:X1}{1:X2}{2:X2}{3:X2}{4:X2}", hyphenated)
    If [0]==0x0A: bytes [3..8] form a 6-byte hex serial
    Otherwise the full 12 bytes are a CP1250-encoded free-text name, null-trimmed
    """
    device_name = ""
    if advertisement.get("serial_display_name"):
        data = advertisement["serial_display_name"]
        if data[0] == 0x0D:
            device_name = "{0:X1}-{1:X2}-{2:X2}-{3:X2}-{4:X2}".format(data[1], data[2], data[3], data[4], data[5])
        elif data[0] == 0x0A:
            device_name = "".join("{:02X}".format(b) for b in data[3:9])
        else:
            device_name = data.decode("cp1250").rstrip("\x00")
    advertisement["device_name"] = device_name
    return advertisement

def get_advertisement(data: bytes):
    advertisement = parse_advertisement(data)
    advertisement = map_device_types_advertisement(advertisement)
    advertisement = calculate_device_name_advertisement(advertisement)
    advertisement = calculate_battery_advertisement(advertisement)
    return advertisement

def parse_notify_response(characteristic: str, data: bytes):
    """
    Byte 0: Length
    Byte 1: Command/Opcode
    Byte 2..N: Payload (depends on the command)
    """
    length = data[0]
    if length != len(data):
        raise ValueError("Invalid data length")
    command = data[1]
    payload = data[2:]
    if command == CMD_READ_ARRAY:
        """Request: Payload[0] = Index, Payload[1] = Length of the array to read"""
        if payload[0] == 0x6:
            return get_lifetime_stats(payload[1:])
    print("Unknown command:", command, "payload:", payload)
    return None

def parse_stats(data: bytes):
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

def get_normalized_and_calculated_stats(data: bytes, today_variant: bool = False):
    if today_variant:
        data = handle_today_variant(data)
    stats = parse_stats(data)
    stats = normalize_stats(stats)
    stats = calculate_stats(stats)
    return stats

def get_lifetime_stats(data: bytes):
    stats = {}
    stats["count-restart"] = int.from_bytes(data[0:4], byteorder='little')
    stats["count-lifetime"] = int.from_bytes(data[4:8], byteorder='little')
    return stats

def build_request(command: int, payload: bytes):
    request = bytearray()
    request.append( 1 + 1 + len(payload)) # Length = Byte for length + Byte for command + Payload length
    request.append(command)
    request.extend(payload)
    return bytes(request)

def build_read_request(address: int, length: int):
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
    return build_request(CMD_READ_ARRAY, bytes(payload))

def display_SE2_device(device: simplepyble.Peripheral):
    print(f"Found SSC device: {device.identifier()} [{device.address()}]")
    if SCAN_DEBUG_SSC:
        print(f"    Connectable: {'Yes' if device.is_connectable() else 'No'}")
        print(f'    Address Type: {device.address_type()}')
        print(f'    Tx Power: {device.tx_power()} dBm')

        manufacturer_data = device.manufacturer_data()
        for manufacturer_id, value in manufacturer_data.items():
            print(f"    Manufacturer ID: {manufacturer_id}")
            print(f"    Manufacturer data: {value}")

        services = device.services()
        for service in services:
            print(f"    Service UUID: {service.uuid()}")
            print(f"    Service data: {service.data()}")
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
        print(f"    Manufacturer data: {value}")

    services = peripheral.services()
    for service in services:
        print(f"    Service UUID: {service.uuid()}")
        print(f"    Service data: {service.data()}")

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

adapter.scan_for(SCAN_DURATION)

devices = adapter.scan_get_results()
print(f"Found {len(devices)} devices, including {len([device for device in devices if 'SE2' in device.identifier()])} SSC devices")
for device in [device for device in devices if 'SE2' in device.identifier()]:
    display_SE2_device(device)
if SCAN_SHOW_UNKNOWN:
    for device in [device for device in devices if 'SE2' not in device.identifier()]:
        display_unknown_device(device)