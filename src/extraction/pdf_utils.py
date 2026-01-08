from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests


@dataclass
class ManualMetadata:
    """Firmware and protocol version metadata extracted from manual front matter."""
    firmware_version: str | None = None
    protocol_version: str | None = None
    version_identifier: str | None = None
    extraction_method: str | None = None


# Variant messages that need to map to their parent in the TOC
# Format: variant_name -> parent_name_in_toc
VARIANT_TO_PARENT = {
    "UBX-LOG-FINDTIME-INPUT": "UBX-LOG-FINDTIME",
    "UBX-LOG-FINDTIME-OUTPUT": "UBX-LOG-FINDTIME",
    "UBX-RXM-RLM-SHORT": "UBX-RXM-RLM",
    "UBX-RXM-RLM-LONG": "UBX-RXM-RLM",
    "UBX-RXM-PMREQ-CMD": "UBX-RXM-PMREQ",
    "UBX-TIM-VCOCAL-SET": "UBX-TIM-VCOCAL",
    "UBX-TIM-VCOCAL-GET": "UBX-TIM-VCOCAL",
    "UBX-CFG-DAT-POLL": "UBX-CFG-DAT",
    "UBX-CFG-DAT-SET": "UBX-CFG-DAT",
    "UBX-CFG-DAT-GET": "UBX-CFG-DAT",
    # NOTE: MON-GNSS V1/V2 NOT auto-expanded - version determined from payload length
    # "UBX-MON-GNSS-V1": "UBX-MON-GNSS",
    # "UBX-MON-GNSS-V2": "UBX-MON-GNSS",
    # NOTE: NAV-RELPOSNED V0/V1 NOT auto-expanded - version determined from payload length
    # "UBX-NAV-RELPOSNED-V0": "UBX-NAV-RELPOSNED",
    # "UBX-NAV-RELPOSNED-V1": "UBX-NAV-RELPOSNED",
    # MGA ephemeris variants
    "UBX-MGA-BDS-EPH": "UBX-MGA-BDS",
    "UBX-MGA-BDS-ALM": "UBX-MGA-BDS",
    "UBX-MGA-BDS-HEALTH": "UBX-MGA-BDS",
    "UBX-MGA-BDS-UTC": "UBX-MGA-BDS",
    "UBX-MGA-BDS-IONO": "UBX-MGA-BDS",
    "UBX-MGA-GAL-EPH": "UBX-MGA-GAL",
    "UBX-MGA-GAL-ALM": "UBX-MGA-GAL",
    "UBX-MGA-GAL-TIMEOFFSET": "UBX-MGA-GAL",
    "UBX-MGA-GAL-UTC": "UBX-MGA-GAL",
    "UBX-MGA-GLO-EPH": "UBX-MGA-GLO",
    "UBX-MGA-GLO-ALM": "UBX-MGA-GLO",
    "UBX-MGA-GLO-TIMEOFFSET": "UBX-MGA-GLO",
    "UBX-MGA-GPS-EPH": "UBX-MGA-GPS",
    "UBX-MGA-GPS-ALM": "UBX-MGA-GPS",
    "UBX-MGA-GPS-HEALTH": "UBX-MGA-GPS",
    "UBX-MGA-GPS-UTC": "UBX-MGA-GPS",
    "UBX-MGA-GPS-IONO": "UBX-MGA-GPS",
    "UBX-MGA-GPS-TIMEOFFSET": "UBX-MGA-GPS",
    "UBX-MGA-QZSS-EPH": "UBX-MGA-QZSS",
    "UBX-MGA-QZSS-ALM": "UBX-MGA-QZSS",
    "UBX-MGA-QZSS-HEALTH": "UBX-MGA-QZSS",
    # MGA-INI variants
    "UBX-MGA-INI-POS-XYZ": "UBX-MGA-INI",
    "UBX-MGA-INI-POS-LLH": "UBX-MGA-INI",
    "UBX-MGA-INI-TIME-UTC": "UBX-MGA-INI",
    "UBX-MGA-INI-TIME-GNSS": "UBX-MGA-INI",
    "UBX-MGA-INI-CLKD": "UBX-MGA-INI",
    "UBX-MGA-INI-FREQ": "UBX-MGA-INI",
    "UBX-MGA-INI-EOP": "UBX-MGA-INI",
}


@dataclass
class MessageLocation:
    name: str
    page_start: int
    page_end: int
    class_id: str
    message_id: str


def download_pdf(url: str, cache_dir: Path) -> Path:
    filename = url.split("/")[-1]
    cache_path = cache_dir / filename

    if cache_path.exists():
        print(f"  Using cached: {filename}")
        return cache_path

    print(f"  Downloading: {filename}")
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    cache_path.write_bytes(response.content)
    return cache_path


def discover_messages_from_toc(pdf_path: Path) -> list[str]:
    """Discover all UBX message names from the PDF table of contents.
    
    Returns a list of message names found in the TOC, plus any known variants
    that should be extracted separately.
    """
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    
    message_names: list[str] = []
    for level, title, page in toc:
        if "UBX-" in title:
            match = re.search(
                r"(UBX-[A-Z]+-[A-Z0-9]+(?:-[A-Z0-9]+)?)\s*\(?(0x[0-9A-Fa-f]+)?\s*(0x[0-9A-Fa-f]+)?\)?",
                title,
            )
            if match and match.group(2) and match.group(3):  # Has class_id and msg_id
                message_names.append(match.group(1))
    
    doc.close()
    
    # Expand parent messages to include known variants, replacing parent with variants
    # Build set of parents that have variants
    parents_with_variants = set(VARIANT_TO_PARENT.values())
    
    expanded: list[str] = []
    for name in message_names:
        # Check if this parent has known variants
        variants_for_parent = [v for v, p in VARIANT_TO_PARENT.items() if p == name]
        if variants_for_parent:
            # Replace parent with its variants
            for variant in variants_for_parent:
                if variant not in expanded:
                    expanded.append(variant)
        else:
            # No variants, keep the original message
            expanded.append(name)
    
    return expanded


def find_message_locations(pdf_path: Path, message_names: list[str]) -> dict[str, MessageLocation]:
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()

    ubx_sections: list[dict[str, Any]] = []
    for level, title, page in toc:
        if "UBX-" in title:
            match = re.search(
                r"(UBX-[A-Z]+-[A-Z0-9]+(?:-[A-Z0-9]+)?)\s*\(?(0x[0-9A-Fa-f]+)?\s*(0x[0-9A-Fa-f]+)?\)?",
                title,
            )
            if match:
                ubx_sections.append(
                    {
                        "name": match.group(1),
                        "class_id": match.group(2) or "",
                        "msg_id": match.group(3) or "",
                        "page": page,
                        "level": level,
                    }
                )

    doc.close()

    ubx_sections.sort(key=lambda x: x["page"])

    locations: dict[str, MessageLocation] = {}
    for target_name in message_names:
        # Check if this is a variant that maps to a parent in the TOC
        lookup_name = VARIANT_TO_PARENT.get(target_name, target_name)
        
        for i, section in enumerate(ubx_sections):
            if section["name"] == lookup_name and section["msg_id"]:
                page_start = section["page"]
                page_end = page_start + 5
                if i + 1 < len(ubx_sections):
                    page_end = min(page_end, ubx_sections[i + 1]["page"])

                # Use the original target_name (variant name) in the result
                locations[target_name] = MessageLocation(
                    name=target_name,
                    page_start=page_start,
                    page_end=page_end,
                    class_id=section["class_id"],
                    message_id=section["msg_id"],
                )
                break

    return locations


def extract_pages_as_images(pdf_path: Path, page_start: int, page_end: int, *, dpi: int = 150) -> list[bytes]:
    doc = fitz.open(str(pdf_path))
    images: list[bytes] = []

    for page_num in range(page_start - 1, min(page_end, len(doc))):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)
        images.append(pix.tobytes("png"))

    doc.close()
    return images


def extract_pages_as_images_cropped(
    pdf_path: Path,
    page_start: int,
    page_end: int,
    *,
    crop_top_ratio: float,
    crop_bottom_ratio: float,
    dpi: int = 150,
) -> list[bytes]:
    doc = fitz.open(str(pdf_path))
    images: list[bytes] = []

    crop_top_ratio = max(0.0, min(0.49, float(crop_top_ratio)))
    crop_bottom_ratio = max(0.0, min(0.49, float(crop_bottom_ratio)))

    for page_num in range(page_start - 1, min(page_end, len(doc))):
        page = doc[page_num]
        rect = page.rect

        top = rect.y0 + rect.height * crop_top_ratio
        bottom = rect.y1 - rect.height * crop_bottom_ratio

        if bottom <= top:
            clip = rect
        else:
            clip = fitz.Rect(rect.x0, top, rect.x1, bottom)

        pix = page.get_pixmap(dpi=dpi, clip=clip)
        images.append(pix.tobytes("png"))

    doc.close()
    return images


# Firmware type identifiers used in u-blox manuals
# SPG=Standard Precision, HPG=High Precision, HPS=High Precision Sensor, LAP=Lane Accurate
# DBD=Dual Band Dead Reckoning, ADR=Automotive Dead Reckoning, MDR=Multi-mode Dead Reckoning
# HDG=Heading, TIM=Timing, UDR=Untethered Dead Reckoning, FTS=Timing (older naming)
_FIRMWARE_TYPES = r"HPG|SPG|HPS|LAP|DBD|ADR|MDR|HDG|TIM|UDR|FTS"


def extract_manual_metadata(pdf_path: Path, search_pages: int = 30) -> ManualMetadata:
    """Extract firmware and protocol version metadata from manual front matter.
    
    Searches the first N pages for the firmware/protocol version table that appears
    in u-blox interface description manuals.
    
    Args:
        pdf_path: Path to the PDF manual
        search_pages: Number of pages to search (default 30)
        
    Returns:
        ManualMetadata with extracted version information, or empty if not found
    """
    doc = fitz.open(str(pdf_path))
    
    # Extract text from first N pages
    text_parts = []
    actual_pages = min(search_pages, len(doc))
    for page_num in range(actual_pages):
        text_parts.append(doc[page_num].get_text())
    text = "\n".join(text_parts)
    doc.close()
    
    metadata = ManualMetadata()
    
    # Pattern 1: F9 format with EXT CORE
    # "HPG 1.50" | "EXT CORE 1.00 (504a0d)" | "27.50"
    # Also handles: "HPG L1L5 1.40", "HDG 1.12"
    pattern1 = re.compile(
        rf"((?:{_FIRMWARE_TYPES})(?:\s+L1L5)?\s+\d+\.\d+)\s+"
        rf"(EXT\s+CORE\s+\d+\.\d+\s*\([^)]+\))\s+"
        rf"(\d+\.\d+)",
        re.IGNORECASE
    )
    match = pattern1.search(text)
    if match:
        metadata.firmware_version = match.group(1).strip()
        metadata.version_identifier = match.group(2).strip()
        metadata.protocol_version = match.group(3).strip()
        metadata.extraction_method = "ext_core_table"
        return metadata
    
    # Pattern 2: M10/F10 format with ROM prefix
    # "SPG 5.10" | "ROM SPG 5.10 (7b202e)" | "34.10"
    # Also handles F10 SPGL1L5 format
    pattern2 = re.compile(
        rf"((?:{_FIRMWARE_TYPES})\s+\d+\.\d+)\s+"
        rf"((?:ROM|EXT)\s+(?:{_FIRMWARE_TYPES}|SPGL1L5|HPGL1L5)\s*\d+\.\d+\s*\([^)]+\))\s+"
        rf"(\d+\.\d+)",
        re.IGNORECASE
    )
    match = pattern2.search(text)
    if match:
        metadata.firmware_version = match.group(1).strip()
        metadata.version_identifier = match.group(2).strip()
        metadata.protocol_version = match.group(3).strip()
        metadata.extraction_method = "rom_prefix_table"
        return metadata
    
    # Pattern 3: X20 format - no ROM/EXT prefix
    # "HPG 2.02" | "HPG 2.02 (43e74c)" | "50.10"
    # Also handles B suffix: "HPG 2.00B02" | "HPG 2.00B002 (d5e4b7)" | "50.01"
    pattern3 = re.compile(
        rf"((?:{_FIRMWARE_TYPES})\s+\d+\.\d+(?:B\d+)?)\s+"
        rf"((?:{_FIRMWARE_TYPES})\s+\d+\.\d+(?:B\d+)?\s*\([^)]+\))\s+"
        rf"(\d+\.\d+)",
        re.IGNORECASE
    )
    match = pattern3.search(text)
    if match:
        metadata.firmware_version = match.group(1).strip()
        metadata.version_identifier = match.group(2).strip()
        metadata.protocol_version = match.group(3).strip()
        metadata.extraction_method = "simple_table"
        return metadata
    
    return metadata
