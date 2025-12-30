"""Output generation for validated canonical messages.

Generates per-message JSON files with consensus metadata for incremental updates.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .voting import ConsensusResult


def consensus_to_canonical(result: ConsensusResult) -> dict:
    """Convert a ConsensusResult to canonical output format.
    
    Includes voting provenance metadata for future incremental updates.
    
    Args:
        result: ConsensusResult from voting
    
    Returns:
        Canonical message dict with consensus metadata
    """
    if not result.winning_message:
        return {
            'name': result.message_name,
            'protocol_version': result.protocol_version,
            'error': 'No winning message available',
        }
    
    msg = result.winning_message
    
    # Build canonical output
    canonical = {
        'name': result.message_name,
        'protocol_version': result.protocol_version,
        'fingerprint': result.winning_fingerprint,
        
        # Consensus metadata for incremental updates
        'consensus': {
            'sources': result.sources,
            'agreement_count': result.agreement_count,
            'total_count': result.total_count,
            'confidence': result.confidence,
            'confidence_score': round(result.confidence_score, 3),
            'last_validated': result.last_validated,
            'outliers': [
                {
                    'source': o.source,
                    'fingerprint': o.fingerprint,
                    'discrepancy': o.discrepancy_summary,
                }
                for o in result.outliers
            ],
        },
        
        # Message metadata from winning source
        'class_id': msg.get('class_id'),
        'message_id': msg.get('message_id'),
        'description': msg.get('description'),
        'payload_length': msg.get('payload_length'),
        
        # Fields from winning source
        'fields': msg.get('fields', []),
        
        # Annotations for code generation (warnings, notes, deprecation, etc.)
        # These can be used by code generators to add comments or handle special cases
        'annotations': [],
    }
    
    # Handle nested payload structure
    if not canonical['fields'] and msg.get('payload'):
        canonical['fields'] = msg['payload'].get('fields', [])
    
    # Add annotations from protocol notes if available
    canonical['annotations'] = _get_annotations(result.message_name, result.protocol_version)
    
    return canonical


# Protocol annotations for code generation
# These document known issues, evolution notes, and warnings
PROTOCOL_ANNOTATIONS = {
    ('UBX-MGA-INI-TIME-UTC', 0): [
        {
            'type': 'evolution',
            'severity': 'info',
            'field': 'bitfield0',
            'offset': 11,
            'message': 'Field at offset 11 changed from reserved to bitfield with trustedSource bit in newer firmware without version bump.',
            'details': 'Older firmware has reserved0 (U1), newer firmware has bitfield0 (X1) with trustedSource bit for replay attack detection.',
        }
    ],
    ('UBX-MGA-INI-TIME-GNSS', 0): [
        {
            'type': 'evolution',
            'severity': 'info', 
            'field': 'bitfield0',
            'offset': 11,
            'message': 'Field at offset 11 changed from reserved to bitfield with trustedSource bit in newer firmware without version bump.',
        }
    ],
    ('UBX-SEC-SIG', 1): [
        {
            'type': 'evolution',
            'severity': 'warning',
            'field': 'sigSecFlags',
            'offset': 1,
            'message': 'Field at offset 1 varies between reserved and sigSecFlags within same protocol version.',
            'details': 'Some v1 firmware has reserved0, others have sigSecFlags bitfield. Check firmware version.',
        }
    ],
    ('UBX-RXM-PMREQ', 0): [
        {
            'type': 'variant',
            'severity': 'warning',
            'message': 'V0 format (8 bytes, no version field) differs significantly from V1 format (16 bytes, with version field).',
            'details': 'V0 starts with duration@0, V1 starts with version@0. Both may be labeled as "version 0" in some manuals.',
        }
    ],
}


def _get_annotations(message_name: str, protocol_version: int) -> list:
    """Get annotations for a message from protocol notes."""
    # Normalize message name
    name = message_name
    if not name.startswith('UBX-'):
        name = f'UBX-{name}'
    
    return PROTOCOL_ANNOTATIONS.get((name, protocol_version), [])


def generate_canonical_filename(message_name: str, protocol_version: int) -> str:
    """Generate filename for canonical message JSON.
    
    Examples:
        ("UBX-NAV-PVT", 0) -> "NAV-PVT-v0.json"
        ("UBX-CFG-VALSET", 1) -> "CFG-VALSET-v1.json"
    """
    # Remove UBX- prefix if present
    name = message_name
    if name.startswith("UBX-"):
        name = name[4:]
    
    return f"{name}-v{protocol_version}.json"


def write_canonical_messages(
    results: dict[tuple[str, int], ConsensusResult],
    output_dir: Path,
    require_consensus: bool = True,
    min_confidence: str | None = None,
) -> dict:
    """Write validated canonical messages to output directory.
    
    Args:
        results: Voting results from vote_on_all_groups
        output_dir: Directory to write canonical JSON files
        require_consensus: Only write messages with consensus
        min_confidence: Minimum confidence level to include
    
    Returns:
        Manifest dict with written files
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    messages_dir = output_dir / "messages"
    messages_dir.mkdir(exist_ok=True)
    
    confidence_levels = ["no_consensus", "single_source", "low", "medium", "high"]
    min_level_idx = 0
    if min_confidence:
        min_level_idx = confidence_levels.index(min_confidence)
    
    manifest = {
        'generated_at': datetime.now().isoformat(),
        'config': {
            'require_consensus': require_consensus,
            'min_confidence': min_confidence,
        },
        'messages': {},
        'stats': {
            'written': 0,
            'skipped_no_consensus': 0,
            'skipped_low_confidence': 0,
        },
    }
    
    for (msg_name, version), result in sorted(results.items()):
        # Check consensus requirement
        if require_consensus and not result.has_consensus:
            manifest['stats']['skipped_no_consensus'] += 1
            continue
        
        # Check confidence level
        result_level_idx = confidence_levels.index(result.confidence)
        if result_level_idx < min_level_idx:
            manifest['stats']['skipped_low_confidence'] += 1
            continue
        
        # Generate canonical output
        canonical = consensus_to_canonical(result)
        
        # Write file
        filename = generate_canonical_filename(msg_name, version)
        filepath = messages_dir / filename
        
        with open(filepath, 'w') as f:
            json.dump(canonical, f, indent=2)
        
        # Add to manifest
        manifest['messages'][f"{msg_name}-v{version}"] = {
            'file': f"messages/{filename}",
            'fingerprint': result.winning_fingerprint,
            'confidence': result.confidence,
            'confidence_score': round(result.confidence_score, 3),
            'sources': len(result.sources),
            'outliers': len(result.outliers),
        }
        manifest['stats']['written'] += 1
    
    # Write manifest
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    return manifest


def update_canonical_with_new_source(
    existing_path: Path,
    new_message: dict,
    new_source: str,
    new_fingerprint: str,
) -> dict:
    """Update an existing canonical message with a new extraction source.
    
    For incremental validation when adding new manuals.
    
    Args:
        existing_path: Path to existing canonical JSON
        new_message: New message extraction to compare
        new_source: Source identifier (e.g., "F9-HPG-1.52")
        new_fingerprint: Fingerprint of new extraction
    
    Returns:
        Updated canonical dict
    """
    with open(existing_path) as f:
        canonical = json.load(f)
    
    consensus = canonical.get('consensus', {})
    existing_fingerprint = canonical.get('fingerprint')
    
    if new_fingerprint == existing_fingerprint:
        # Agreement - add to sources, increase confidence
        if new_source not in consensus.get('sources', []):
            consensus.setdefault('sources', []).append(new_source)
            consensus['agreement_count'] = consensus.get('agreement_count', 1) + 1
            consensus['total_count'] = consensus.get('total_count', 1) + 1
            
            # Recalculate confidence score
            ratio = consensus['agreement_count'] / consensus['total_count']
            consensus['confidence_score'] = round(ratio, 3)
            
            # Update confidence level
            if ratio >= 0.9 and consensus['total_count'] >= 3:
                consensus['confidence'] = 'high'
            elif ratio >= 0.75 and consensus['total_count'] >= 3:
                consensus['confidence'] = 'medium'
            elif ratio >= 0.75:
                consensus['confidence'] = 'low'
    else:
        # Disagreement - add as outlier
        outliers = consensus.setdefault('outliers', [])
        if not any(o['source'] == new_source for o in outliers):
            outliers.append({
                'source': new_source,
                'fingerprint': new_fingerprint,
                'discrepancy': 'Fingerprint mismatch with consensus',
            })
            consensus['total_count'] = consensus.get('total_count', 1) + 1
            
            # Recalculate confidence score
            ratio = consensus['agreement_count'] / consensus['total_count']
            consensus['confidence_score'] = round(ratio, 3)
    
    consensus['last_validated'] = datetime.now().isoformat()[:10]
    canonical['consensus'] = consensus
    
    return canonical
