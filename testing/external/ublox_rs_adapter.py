#!/usr/bin/env python3
"""
Adapter for comparing our schema against ublox-rs supported messages.

ublox-rs is a Rust crate that implements UBX protocol parsing.
This adapter provides:
1. A list of messages supported by ublox-rs for coverage comparison
2. Cross-validation by calling the ublox-rs validator binary

Source: https://github.com/ublox-rs/ublox
"""

import json
import subprocess
from pathlib import Path

# Path to the ublox-rs validator binary
VALIDATOR_PATH = Path(__file__).parent / "ublox_rs_validator" / "target" / "release" / "validate_ubx"


def is_validator_available() -> bool:
    """Check if the ublox-rs validator binary is available."""
    return VALIDATOR_PATH.exists()


def parse_ubx_bytes_with_ublox_rs(data: bytes) -> dict:
    """
    Parse UBX bytes using the ublox-rs validator.
    
    Args:
        data: Raw UBX message bytes
        
    Returns:
        Dict with parsing result: {parsed, message_class, message_id, payload_len, error}
    """
    if not is_validator_available():
        return {"error": "ublox-rs validator not built", "parsed": False}
    
    try:
        hex_data = data.hex()
        result = subprocess.run(
            [str(VALIDATOR_PATH), hex_data],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"error": f"Validator failed: {result.stderr}", "parsed": False}
            
    except subprocess.TimeoutExpired:
        return {"error": "Validator timeout", "parsed": False}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON from validator: {e}", "parsed": False}
    except Exception as e:
        return {"error": str(e), "parsed": False}

# Messages supported by ublox-rs (extracted from source tree)
# Format: UBX message name as we use it
UBLOX_RS_MESSAGES = {
    # ACK class
    "UBX-ACK-ACK",
    "UBX-ACK-NAK",
    
    # AID class (legacy)
    "UBX-AID-INI",
    
    # CFG class
    "UBX-CFG-ANT",
    "UBX-CFG-GNSS",
    "UBX-CFG-INF",
    "UBX-CFG-ITFM",
    "UBX-CFG-MSG",
    "UBX-CFG-NAV5",
    "UBX-CFG-NAVX5",
    "UBX-CFG-ODO",
    "UBX-CFG-PRT",
    "UBX-CFG-RATE",
    "UBX-CFG-RST",
    "UBX-CFG-SMGR",
    "UBX-CFG-TMODE2",
    "UBX-CFG-TMODE3",
    "UBX-CFG-TP5",
    "UBX-CFG-VALGET",
    "UBX-CFG-VALSET",
    "UBX-CFG-VALDEL",
    
    # ESF class
    "UBX-ESF-ALG",
    "UBX-ESF-INS",
    "UBX-ESF-MEAS",
    "UBX-ESF-RAW",
    "UBX-ESF-STATUS",
    
    # HNR class
    "UBX-HNR-ATT",
    "UBX-HNR-INS",
    "UBX-HNR-PVT",
    
    # INF class
    "UBX-INF-DEBUG",
    "UBX-INF-ERROR",
    "UBX-INF-NOTICE",
    "UBX-INF-TEST",
    "UBX-INF-WARNING",
    
    # MGA class
    "UBX-MGA-ACK",
    "UBX-MGA-BDS-EPH",
    "UBX-MGA-BDS-IONO",
    "UBX-MGA-BDS-UTC",
    "UBX-MGA-GAL-EPH",
    "UBX-MGA-GAL-TIMEOFFSET",
    "UBX-MGA-GLO-EPH",
    "UBX-MGA-GPS-EPH",
    "UBX-MGA-GPS-IONO",
    "UBX-MGA-GPS-UTC",
    
    # MON class
    "UBX-MON-COMMS",
    "UBX-MON-GNSS",
    "UBX-MON-HW",
    "UBX-MON-HW2",
    "UBX-MON-HW3",
    "UBX-MON-IO",
    "UBX-MON-RF",
    "UBX-MON-VER",
    
    # NAV class
    "UBX-NAV-ATT",
    "UBX-NAV-CLOCK",
    "UBX-NAV-COV",
    "UBX-NAV-DOP",
    "UBX-NAV-HPPOSECEF",
    "UBX-NAV-HPPOSLLH",
    "UBX-NAV-PL",
    "UBX-NAV-POSECEF",
    "UBX-NAV-POSLLH",
    "UBX-NAV-PVT",
    "UBX-NAV-RELPOSNED",
    "UBX-NAV-SAT",
    "UBX-NAV-SIG",
    "UBX-NAV-SOL",
    "UBX-NAV-STATUS",
    "UBX-NAV-TIMELS",
    "UBX-NAV-TIMEUTC",
    "UBX-NAV-VELNED",
    "UBX-NAV-EOE",
    "UBX-NAV-GEOFENCE",
    "UBX-NAV-ODO",
    "UBX-NAV-ORB",
    "UBX-NAV-SBAS",
    "UBX-NAV-SVIN",
    "UBX-NAV-TIMEBDS",
    "UBX-NAV-TIMEGAL",
    "UBX-NAV-TIMEGLO",
    "UBX-NAV-TIMEGPS",
    "UBX-NAV-VELECEF",
    
    # RXM class
    "UBX-RXM-COR",
    "UBX-RXM-RAWX",
    "UBX-RXM-RTCM",
    "UBX-RXM-SFRBX",
    
    # SEC class
    "UBX-SEC-SIG",
    "UBX-SEC-SIGLOG",
    "UBX-SEC-UNIQID",
    
    # TIM class
    "UBX-TIM-SVIN",
    "UBX-TIM-TM2",
    "UBX-TIM-TOS",
    "UBX-TIM-TP",
}

# Alternative name mappings (ublox-rs uses slightly different names)
UBLOX_RS_NAME_MAP = {
    "UBX-NAV-HPPOSECEF": ["UBX-NAV-HPPOSECEF"],
    "UBX-NAV-HPPOSLLH": ["UBX-NAV-HPPOSLLH"],
    "UBX-NAV-RELPOSNED": ["UBX-NAV-RELPOSNED"],
    "UBX-NAV-TIMELS": ["UBX-NAV-TIMELS"],
    "UBX-NAV-TIMEUTC": ["UBX-NAV-TIMEUTC"],
    "UBX-NAV-VELNED": ["UBX-NAV-VELNED"],
    "UBX-SEC-UNIQID": ["UBX-SEC-UNIQID"],
    "UBX-MGA-GAL-TIMEOFFSET": ["UBX-MGA-GAL-TIMEOFFSET"],
}


def get_ublox_rs_messages() -> set[str]:
    """Return the set of messages supported by ublox-rs."""
    return UBLOX_RS_MESSAGES.copy()


def normalize_message_name(name: str) -> str:
    """Normalize message name for comparison."""
    # Remove spaces and convert to uppercase
    return name.upper().replace(" ", "-").replace("_", "-")


def is_in_ublox_rs(message_name: str) -> bool:
    """Check if a message is supported by ublox-rs."""
    normalized = normalize_message_name(message_name)
    if normalized in UBLOX_RS_MESSAGES:
        return True
    # Check alternative names
    for alt_names in UBLOX_RS_NAME_MAP.values():
        if normalized in alt_names:
            return True
    return False


if __name__ == "__main__":
    print(f"ublox-rs supports {len(UBLOX_RS_MESSAGES)} messages")
    for msg in sorted(UBLOX_RS_MESSAGES):
        print(f"  {msg}")
