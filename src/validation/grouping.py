"""Grouping logic for UBX message extractions.

Groups extracted messages by (message_name, protocol_version) to enable
voting within groups of messages that should be structurally identical.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .fingerprint import compute_message_fingerprint, compute_message_fingerprint_detailed
from .version_detect import detect_version_field, get_protocol_version


@dataclass
class ExtractionSource:
    """Metadata about an extraction source."""
    filename: str
    family: str      # e.g., "F9", "M10", "X20"
    firmware_type: str  # e.g., "HPG", "SPG"
    firmware_version: str  # e.g., "1.51"
    
    @property
    def short_name(self) -> str:
        """Short identifier like 'F9-HPG-1.51'."""
        return f"{self.family}-{self.firmware_type}-{self.firmware_version}"


@dataclass
class GroupedMessage:
    """A message instance within a group."""
    source: ExtractionSource
    message_data: dict
    fingerprint: str
    fingerprint_detailed: dict
    protocol_version: int
    version_field_info: dict


@dataclass
class MessageGroup:
    """A group of messages with same (name, protocol_version)."""
    message_name: str
    protocol_version: int
    messages: list[GroupedMessage] = field(default_factory=list)
    
    @property
    def fingerprint_counts(self) -> dict[str, int]:
        """Count occurrences of each fingerprint."""
        counts: dict[str, int] = defaultdict(int)
        for msg in self.messages:
            counts[msg.fingerprint] += 1
        return dict(counts)
    
    @property
    def source_count(self) -> int:
        """Number of sources in this group."""
        return len(self.messages)
    
    @property
    def unique_fingerprints(self) -> int:
        """Number of unique fingerprints (1 = full agreement)."""
        return len(self.fingerprint_counts)


def parse_source_from_filename(filename: str) -> ExtractionSource:
    """Extract source metadata from extraction filename.
    
    Examples:
        "u-blox-F9-HPG-1.51_InterfaceDescription_..." -> F9, HPG, 1.51
        "u-blox-20-HPG-2.00_..." -> X20, HPG, 2.00
        "u-blox8-M8_ReceiverDescrProtSpec_..." -> M8, SPG, 0.0
        "F9-HPS-1.21_InterfaceDescription_..." -> F9, HPS, 1.21
        "M9-ADR-5.10_InterfaceDescription_..." -> M9, ADR, 5.10
    """
    # X20 pattern (u-blox-20-HPG-2.00)
    match = re.search(r'u-blox-20-([A-Z]+)-(\d+\.\d+)', filename)
    if match:
        return ExtractionSource(
            filename=filename,
            family="X20",
            firmware_type=match.group(1),
            firmware_version=match.group(2),
        )
    
    # F9/F10/M9/M10 pattern with u-blox prefix
    match = re.search(r'u-blox-?(F9|F10|M9|M10|X20)-([A-Z0-9]+(?:-[A-Z0-9]+)?)-(\d+\.\d+)', filename)
    if match:
        return ExtractionSource(
            filename=filename,
            family=match.group(1),
            firmware_type=match.group(2),
            firmware_version=match.group(3),
        )
    
    # Pattern without u-blox prefix: F9-HPS-1.21, M9-ADR-5.10, M9-MDR-2.10
    match = re.search(r'^(F9|F10|M9|M10)-([A-Z]+)-(\d+\.\d+)', filename)
    if match:
        return ExtractionSource(
            filename=filename,
            family=match.group(1),
            firmware_type=match.group(2),
            firmware_version=match.group(3),
        )
    
    # Legacy 120 pattern: F9-HPS120, LAP120 (version 1.20)
    match = re.search(r'(F9-)?([A-Z]+)120', filename)
    if match:
        fw_type = match.group(2)
        family = "F9" if match.group(1) or fw_type in ("HPS", "LAP") else "UNKNOWN"
        return ExtractionSource(
            filename=filename,
            family=family,
            firmware_type=fw_type,
            firmware_version="1.20",
        )
    
    # ZED-F9H pattern
    if "ZED-F9H" in filename:
        return ExtractionSource(
            filename=filename,
            family="F9",
            firmware_type="F9H",
            firmware_version="1.0",
        )
    
    # M8 pattern
    if "M8" in filename or "u-blox8" in filename:
        return ExtractionSource(
            filename=filename,
            family="M8",
            firmware_type="SPG",
            firmware_version="0.0",
        )
    
    return ExtractionSource(
        filename=filename,
        family="UNKNOWN",
        firmware_type="UNKNOWN",
        firmware_version="0.0",
    )


def load_extraction(filepath: Path) -> tuple[ExtractionSource, list[dict]]:
    """Load an extraction file and return source info + messages.
    
    Args:
        filepath: Path to extraction JSON file
    
    Returns:
        (ExtractionSource, list of message dicts)
    """
    source = parse_source_from_filename(filepath.name)
    
    with open(filepath) as f:
        data = json.load(f)
    
    messages = data.get('messages', [])
    return source, messages


def group_extractions(extractions_dir: Path) -> dict[tuple[str, int], MessageGroup]:
    """Load all extractions and group by (message_name, protocol_version).
    
    Args:
        extractions_dir: Directory containing *_anthropic.json and *_gemini.json files
    
    Returns:
        Dict mapping (message_name, protocol_version) to MessageGroup
    """
    groups: dict[tuple[str, int], MessageGroup] = {}
    
    # Load both Anthropic and Gemini extractions for validation voting
    anthropic_files = sorted(extractions_dir.glob("*_anthropic.json"))
    gemini_files = sorted(extractions_dir.glob("*_gemini.json"))
    extraction_files = anthropic_files + gemini_files
    
    for filepath in extraction_files:
        source, messages = load_extraction(filepath)
        
        for msg in messages:
            msg_name = msg.get('name', '')
            if not msg_name:
                continue
            
            # Detect protocol version using the proper function
            version_info = detect_version_field(msg)
            protocol_version = get_protocol_version(msg)
            
            # Compute fingerprint
            fingerprint = compute_message_fingerprint(msg)
            fingerprint_detailed = compute_message_fingerprint_detailed(msg)
            
            # Create grouped message
            grouped = GroupedMessage(
                source=source,
                message_data=msg,
                fingerprint=fingerprint,
                fingerprint_detailed=fingerprint_detailed,
                protocol_version=protocol_version,
                version_field_info={
                    'detected': version_info.detected,
                    'field_name': version_info.field_name,
                    'byte_offset': version_info.byte_offset,
                    'confidence': version_info.confidence,
                    'reason': version_info.reason,
                },
            )
            
            # Add to group
            key = (msg_name, protocol_version)
            if key not in groups:
                groups[key] = MessageGroup(
                    message_name=msg_name,
                    protocol_version=protocol_version,
                )
            groups[key].messages.append(grouped)
    
    return groups


def get_group_summary(groups: dict[tuple[str, int], MessageGroup]) -> dict:
    """Generate summary statistics for grouped extractions.
    
    Args:
        groups: Result from group_extractions
    
    Returns:
        Dict with summary statistics
    """
    total_groups = len(groups)
    total_messages = sum(g.source_count for g in groups.values())
    
    # Count groups by agreement level
    full_agreement = 0  # All sources have same fingerprint
    partial_agreement = 0  # Majority agrees
    no_consensus = 0  # No clear majority
    single_source = 0  # Only one source
    
    for group in groups.values():
        if group.source_count == 1:
            single_source += 1
        elif group.unique_fingerprints == 1:
            full_agreement += 1
        else:
            # Check if there's a majority
            counts = group.fingerprint_counts
            max_count = max(counts.values())
            if max_count / group.source_count >= 0.75:
                partial_agreement += 1
            else:
                no_consensus += 1
    
    # Messages by protocol version
    by_version: dict[int, int] = defaultdict(int)
    for (name, version), group in groups.items():
        by_version[version] += 1
    
    return {
        'total_groups': total_groups,
        'total_message_instances': total_messages,
        'full_agreement': full_agreement,
        'partial_agreement': partial_agreement,
        'no_consensus': no_consensus,
        'single_source': single_source,
        'by_protocol_version': dict(by_version),
    }
