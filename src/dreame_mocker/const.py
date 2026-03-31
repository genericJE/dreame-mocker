"""Constants for Dreame API — SIID/PIID/AIID mappings, crypto, and device definitions."""

from __future__ import annotations

# --- X50 Ultra Complete model identifiers ---
X50_ULTRA_COMPLETE_MODELS = [
    "dreame.vacuum.r2532a",
    "dreame.vacuum.r2532d",
    "dreame.vacuum.r2532h",
    "dreame.vacuum.r2532v",
    "dreame.vacuum.r2532z",
    "dreame.vacuum.r2538a",
    "dreame.vacuum.r2538z",
]

DEFAULT_MODEL = "dreame.vacuum.r2532a"

# --- Dreamehome cloud paths ---
AUTH_PATH = "/dreame-auth/oauth/token"
EMAIL_CODE_PATH = "/dreame-auth/oauth/email"
DEVICE_LIST_PATH = "/dreame-user-iot/iotuserbind/device/listV2"
SEND_COMMAND_PATH = "/dreame-iot-com-10000/device/sendCommand"
PROPERTIES_PATH = "/dreame-iot-com-10000/device/properties"
MAP_DOWNLOAD_URL_PATH = "/dreame-user-iot/iotfile/getDownloadUrl"

# --- Crypto ---
CLIENT_CREDENTIALS_B64 = "ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
PASSWORD_SALT = "RAylYC%fmSKp7%Tq"
AES_KEY = b"EETjszu*XI5znHsI"

# --- SIID definitions (service instance IDs) ---
SIID_VACUUM = 2
SIID_BATTERY = 3
SIID_CLEAN = 4
SIID_MAP = 6
SIID_AUTO_EMPTY = 15

# --- Property keys: (siid, piid) ---
class Property:
    STATE = (2, 1)
    ERROR = (2, 2)
    BATTERY_LEVEL = (3, 1)
    CHARGING_STATUS = (3, 2)
    SUCTION_LEVEL = (4, 4)
    WATER_VOLUME = (4, 5)
    CLEANING_MODE = (4, 23)
    SELF_WASH_BASE_STATUS = (4, 25)
    CLEANING_TIME = (4, 2)
    CLEANING_AREA = (4, 3)
    DUST_COLLECTION = (15, 3)
    AUTO_EMPTY_STATUS = (15, 5)
    MAIN_BRUSH_TIME_LEFT = (9, 1)
    MAIN_BRUSH_LIFE_LEVEL = (9, 2)
    SIDE_BRUSH_TIME_LEFT = (10, 1)
    SIDE_BRUSH_LIFE_LEVEL = (10, 2)
    FILTER_TIME_LEFT = (11, 1)
    FILTER_LIFE_LEVEL = (11, 2)
    MOP_PAD_TIME_LEFT = (16, 1)
    MOP_PAD_LIFE_LEVEL = (16, 2)
    DND_ENABLED = (12, 1)
    DND_START_HOUR = (12, 2)
    DND_START_MINUTE = (12, 3)
    DND_END_HOUR = (12, 4)
    DND_END_MINUTE = (12, 5)
    VOLUME = (7, 1)
    VOICE_PACKET_ID = (7, 3)
    TIMEZONE = (7, 5)
    # Map service (SIID 6)
    MAP_DATA = (6, 1)
    FRAME_INFO = (6, 2)
    OBJECT_NAME = (6, 3)
    MAP_EXTEND_DATA = (6, 4)
    ROBOT_TIME = (6, 5)
    RESULT_CODE = (6, 6)
    MULTI_FLOOR_MAP = (6, 7)
    MAP_LIST = (6, 8)
    RECOVERY_MAP_LIST = (6, 9)

# --- Action keys: (siid, aiid) ---
class Action:
    START = (2, 1)
    PAUSE = (2, 2)
    CHARGE = (3, 1)
    START_CUSTOM = (4, 1)
    STOP = (4, 2)
    START_WASHING = (4, 4)
    START_DRYING = (4, 5)
    START_AUTO_EMPTY = (15, 1)
    REQUEST_MAP = (6, 1)
    UPDATE_MAP_DATA = (6, 2)

# --- Device states ---
class DeviceState:
    SWEEPING = 1
    IDLE = 2
    PAUSED = 3
    ERROR = 4
    RETURNING = 5
    CHARGING = 6
    MOPPING = 7
    DRYING = 8
    WASHING = 9
    SWEEP_AND_MOP = 12
    CHARGE_COMPLETE = 13
    MOP_WASHING = 20
    MOP_WASHING_PAUSED = 21

STATES: dict[int, str] = {
    1: "Sweeping",
    2: "Idle",
    3: "Paused",
    4: "Error",
    5: "Returning",
    6: "Charging",
    7: "Mopping",
    8: "Drying",
    9: "Washing",
    12: "Sweep+Mop",
    13: "Charge Complete",
    20: "Mop Washing",
    21: "Mop Washing Paused",
}

# --- Suction levels ---
class SuctionLevel:
    QUIET = 0
    STANDARD = 1
    STRONG = 2
    TURBO = 3

# --- Water volume ---
class WaterVolume:
    LOW = 1
    MEDIUM = 2
    HIGH = 3

# --- Cleaning mode ---
class CleaningMode:
    SWEEPING = 0
    MOPPING = 1
    SWEEP_AND_MOP = 2
