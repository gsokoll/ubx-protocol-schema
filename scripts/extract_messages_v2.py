#!/usr/bin/env python3
"""UBX message extraction with multi-shot conversations and self-review.

Workflow v2 Implementation:
- Stage 1: Initial extraction with Gemini 2.5 Flash, saving conversation history
- Stage 2: Voting/preliminary structure determination (separate script)
- Stage 3: Self-review with Gemini 3 Flash, continuing original conversations
- Stage 4: Final determination (separate script)

This script handles Stage 1 (extraction) and Stage 3 (self-review).

Conversation storage format:
{
    "manual": "filename.pdf",
    "message_name": "UBX-NAV-PVT",
    "extraction_timestamp": "2026-01-04T10:30:00Z",
    "model": "gemini-2.5-flash",
    "pdf_pages": {"start": 123, "end": 127},
    "conversation": [
        {"role": "user", "parts": [...]},
        {"role": "model", "parts": [...]}
    ],
    "extracted_structure": {...},
    "review": null  // Populated in Stage 3
}

Usage:
    # Stage 1: Initial extraction
    uv run python scripts/extract_messages_v2.py extract --pdf-path <path> --all-messages
    
    # Stage 3: Self-review (after voting)
    uv run python scripts/extract_messages_v2.py review --pdf-path <path> --preliminary-dir <path>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

# Import from existing extraction script
from extract_messages_with_gemini import (
    build_extraction_prompt,
    post_process_message,
    validate_message,
)

# Available models
GEMINI_MODELS = {
    "flash-lite": "gemini-2.5-flash-lite",
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
    "3-flash": "gemini-3-flash-preview",
    "3-pro": "gemini-3-pro-preview",
}

PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3-pro-preview": {"input": 1.25, "output": 10.00},
}

# Default models per stage (as per workflow proposal)
DEFAULT_EXTRACTION_MODEL = "flash"  # Gemini 2.5 Flash
DEFAULT_REVIEW_MODEL = "3-flash"    # Gemini 3 Flash


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    
    def cost(self, model: str) -> float:
        pricing = PRICING.get(model, PRICING["gemini-2.5-flash"])
        return (self.input_tokens * pricing["input"] + self.output_tokens * pricing["output"]) / 1_000_000


@dataclass 
class MessageLocation:
    """Location of a UBX message in the PDF."""
    name: str
    page_start: int
    page_end: int
    class_id: str = ""
    message_id: str = ""


@dataclass
class ConversationRecord:
    """Persistent record of an extraction conversation."""
    manual: str
    message_name: str
    extraction_timestamp: str
    model: str
    pdf_pages: dict[str, int]
    conversation: list[dict[str, Any]]
    extracted_structure: dict[str, Any] | None
    review: dict[str, Any] | None = None
    uploaded_file_name: str | None = None  # Gemini file reference for Stage 3
    
    def to_dict(self) -> dict:
        return {
            "manual": self.manual,
            "message_name": self.message_name,
            "extraction_timestamp": self.extraction_timestamp,
            "model": self.model,
            "pdf_pages": self.pdf_pages,
            "conversation": self.conversation,
            "extracted_structure": self.extracted_structure,
            "review": self.review,
            "uploaded_file_name": self.uploaded_file_name,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ConversationRecord":
        return cls(
            manual=data["manual"],
            message_name=data["message_name"],
            extraction_timestamp=data["extraction_timestamp"],
            model=data["model"],
            pdf_pages=data["pdf_pages"],
            conversation=data["conversation"],
            extracted_structure=data.get("extracted_structure"),
            review=data.get("review"),
            uploaded_file_name=data.get("uploaded_file_name"),
        )


class ConversationStore:
    """Manages persistent storage of extraction conversations."""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_path(self, manual_stem: str, message_name: str) -> Path:
        """Get path to conversation file."""
        # Sanitize message name for filesystem
        safe_name = message_name.replace("-", "_")
        return self.base_dir / manual_stem / f"{safe_name}.json"
    
    def save(self, record: ConversationRecord) -> Path:
        """Save a conversation record."""
        manual_stem = Path(record.manual).stem
        path = self._get_path(manual_stem, record.message_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w") as f:
            json.dump(record.to_dict(), f, indent=2)
        
        return path
    
    def load(self, manual_stem: str, message_name: str) -> ConversationRecord | None:
        """Load a conversation record."""
        path = self._get_path(manual_stem, message_name)
        if not path.exists():
            return None
        
        with open(path) as f:
            data = json.load(f)
        
        return ConversationRecord.from_dict(data)
    
    def list_conversations(self, manual_stem: str) -> list[str]:
        """List all message names with conversations for a manual."""
        manual_dir = self.base_dir / manual_stem
        if not manual_dir.exists():
            return []
        
        messages = []
        for path in manual_dir.glob("*.json"):
            # Convert back from filesystem name to message name
            msg_name = path.stem.replace("_", "-")
            messages.append(msg_name)
        
        return sorted(messages)


# Import variant mappings from existing script
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
    "UBX-MGA-INI-POS-XYZ": "UBX-MGA-INI",
    "UBX-MGA-INI-POS-LLH": "UBX-MGA-INI",
    "UBX-MGA-INI-TIME-UTC": "UBX-MGA-INI",
    "UBX-MGA-INI-TIME-GNSS": "UBX-MGA-INI",
    "UBX-MGA-INI-CLKD": "UBX-MGA-INI",
    "UBX-MGA-INI-FREQ": "UBX-MGA-INI",
    "UBX-MGA-INI-EOP": "UBX-MGA-INI",
}

MULTI_VARIANT_MESSAGES = {
    "UBX-CFG-INF": ["", "-POLL"],
    "UBX-CFG-DAT": ["-POLL", "-SET", "-GET"],
    "UBX-LOG-FINDTIME": ["-INPUT", "-OUTPUT"],
    "UBX-RXM-RLM": ["-SHORT", "-LONG"],
    "UBX-RXM-PMREQ": ["-V0", "-V1"],
    "UBX-TIM-VCOCAL": ["-SET", "-GET"],
}


def discover_message_locations(pdf_path: Path) -> dict[str, MessageLocation]:
    """Discover UBX message locations from PDF TOC."""
    
    doc = fitz.open(str(pdf_path))
    toc = doc.get_toc()
    doc.close()
    
    ubx_sections: list[dict[str, Any]] = []
    
    for level, title, page in toc:
        if "UBX-" in title:
            match = re.search(
                r"(UBX-[A-Z]+-[A-Z0-9]+(?:-[A-Z0-9]+)?)\s*\((0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\)",
                title,
            )
            if match:
                ubx_sections.append({
                    "name": match.group(1),
                    "class_id": match.group(2),
                    "msg_id": match.group(3),
                    "page": page,
                    "level": level,
                })
    
    ubx_sections.sort(key=lambda x: x["page"])
    
    base_locations: dict[str, MessageLocation] = {}
    
    for i, section in enumerate(ubx_sections):
        page_start = section["page"]
        if i + 1 < len(ubx_sections):
            page_end = min(section["page"] + 5, ubx_sections[i + 1]["page"])
        else:
            page_end = section["page"] + 5
        
        base_locations[section["name"]] = MessageLocation(
            name=section["name"],
            page_start=page_start,
            page_end=page_end,
            class_id=section["class_id"],
            message_id=section["msg_id"],
        )
    
    # Expand parents to variants
    parents_with_variants = set(VARIANT_TO_PARENT.values())
    locations: dict[str, MessageLocation] = {}
    
    for name, loc in base_locations.items():
        variants_for_parent = [v for v, p in VARIANT_TO_PARENT.items() if p == name]
        
        if variants_for_parent:
            for variant in variants_for_parent:
                locations[variant] = MessageLocation(
                    name=variant,
                    page_start=loc.page_start,
                    page_end=loc.page_end,
                    class_id=loc.class_id,
                    message_id=loc.message_id,
                )
        else:
            locations[name] = loc
    
    return locations


def create_message_pdf(source_pdf: Path, page_start: int, page_end: int) -> Path:
    """Extract message pages to a temp PDF."""
    
    doc = fitz.open(str(source_pdf))
    new_doc = fitz.open()
    
    for page_num in range(page_start - 1, min(page_end, len(doc))):
        if page_num < len(doc):
            new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
    
    temp_path = tempfile.mktemp(suffix=".pdf")
    new_doc.save(temp_path)
    new_doc.close()
    doc.close()
    
    return Path(temp_path)


def build_review_prompt(
    preliminary_structure: dict,
    other_extractions: list[dict],
    message_version: str | None = None,
) -> str:
    """Build the self-review prompt for Stage 3."""
    
    # Format preliminary structure
    preliminary_json = json.dumps(preliminary_structure, indent=2)
    
    # Format other extractions (same version only)
    others_text = ""
    if other_extractions:
        others_text = "\n\n=== OTHER MANUAL EXTRACTIONS (same version) ===\n"
        for i, ext in enumerate(other_extractions, 1):
            source = ext.get("source", f"Manual {i}")
            structure = ext.get("structure", {})
            others_text += f"\n--- {source} ---\n{json.dumps(structure, indent=2)}\n"
    
    version_note = ""
    if message_version:
        version_note = f"\nMessage version being compared: {message_version}"
    
    return f"""Please review your earlier extraction against the consensus structure from multiple manuals.
{version_note}

=== CONSENSUS (PRELIMINARY) STRUCTURE ===
{preliminary_json}
{others_text}

=== REVIEW TASK ===

Compare your original extraction (from earlier in this conversation) against:
1. The PDF pages you originally read
2. The consensus structure shown above
3. The extractions from other manuals (if shown)

Determine which category applies:

- **correct**: Your extraction matches the consensus structure
- **extraction_error**: You made a mistake in your original extraction
- **valid_change**: The protocol genuinely differs in this manual (documented change)
- **version_bump**: This is a different version of the message (v0 vs v1 etc.)

=== RESPONSE FORMAT ===

Return a JSON object:
{{
  "verdict": "correct" | "extraction_error" | "valid_change" | "version_bump",
  "confidence": "high" | "medium" | "low",
  "reasoning": "Explanation of your determination",
  "corrected_structure": null,  // or corrected JSON if extraction_error
  "change_details": null  // or details if valid_change/version_bump
}}

If verdict is "extraction_error", provide the corrected structure in corrected_structure.
If verdict is "valid_change" or "version_bump", explain the difference in change_details."""


def call_gemini_with_chat(
    client,
    uploaded_file,
    conversation_history: list[dict],
    new_prompt: str,
    model: str,
    verbose: bool = True,
) -> tuple[str, list[dict], TokenUsage]:
    """Make a Gemini API call using the chats API for multi-turn conversation.
    
    Args:
        client: Gemini client
        uploaded_file: Uploaded file reference
        conversation_history: List of previous turns (for continuation)
        new_prompt: The new user prompt to send
        model: Model name
        verbose: Print progress
    
    Returns:
        (response_text, updated_conversation, token_usage)
    """
    from google.genai import types
    
    # Build history from stored conversation
    history = []
    for turn in conversation_history:
        role = turn["role"]
        parts = []
        for p in turn["parts"]:
            if isinstance(p, str):
                parts.append(types.Part.from_text(text=p))
            else:
                parts.append(p)
        history.append(types.Content(role=role, parts=parts))
    
    # Create chat with history
    chat = client.chats.create(
        model=model,
        history=history,
        config={
            "response_mime_type": "application/json",
            "max_output_tokens": 16384,
        },
    )
    
    # Build message with file if provided
    if uploaded_file is not None:
        message = [uploaded_file, new_prompt]
    else:
        message = new_prompt
    
    # Send message with retry
    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = chat.send_message(message)
            break
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = 30 * (2 ** attempt)
                if verbose:
                    print(f"rate limited, waiting {wait_time}s...", end=" ", flush=True)
                time.sleep(wait_time)
                if attempt == max_retries - 1:
                    raise
            else:
                raise
    
    # Extract response text
    response_text = response.text or ""
    
    # Build updated conversation history (store as serializable format)
    new_history = list(conversation_history)
    
    # Add user turn (text only for storage - file is referenced separately)
    new_history.append({
        "role": "user",
        "parts": [new_prompt],
    })
    
    # Add model response
    new_history.append({
        "role": "model", 
        "parts": [response_text],
    })
    
    # Get usage
    usage = TokenUsage()
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        usage.input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        usage.output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    
    return response_text, new_history, usage


def extract_message_with_conversation(
    client,
    pdf_path: Path,
    location: MessageLocation,
    model: str,
    max_pages: int = 5,
    verbose: bool = True,
) -> tuple[ConversationRecord, TokenUsage]:
    """Extract a message and save the conversation for later review."""
    
    page_end = min(location.page_end, location.page_start + max_pages)
    page_count = page_end - location.page_start + 1
    
    if verbose:
        print(f"  Extracting {location.name} (pages {location.page_start}-{page_end}, {page_count} pages)...", end=" ", flush=True)
    
    # Create temp PDF
    temp_pdf = create_message_pdf(pdf_path, location.page_start, page_end)
    
    try:
        # Upload PDF
        uploaded_file = client.files.upload(file=temp_pdf)
        
        # Build extraction prompt
        prompt = build_extraction_prompt(
            message_name=location.name,
            expected_class_id=location.class_id,
            expected_message_id=location.message_id,
        )
        
        start_time = time.time()
        
        # Make initial extraction call
        response_text, conversation, usage = call_gemini_with_chat(
            client=client,
            uploaded_file=uploaded_file,
            conversation_history=[],
            new_prompt=prompt,
            model=model,
            verbose=verbose,
        )
        
        elapsed = time.time() - start_time
        
        # Parse response
        try:
            extracted = json.loads(response_text)
            
            # Handle list response
            if isinstance(extracted, list):
                if extracted:
                    extracted = extracted[0]
                else:
                    raise ValueError("Empty list response")
            
            # Handle None/non-dict response
            if not isinstance(extracted, dict):
                raise ValueError(f"Expected dict, got {type(extracted).__name__}")
            
            # Apply post-processing fixes
            extracted = post_process_message(extracted)
            
            payload = extracted.get("payload") or {}
            fields = payload.get("fields", []) if isinstance(payload, dict) else []
            field_count = len(fields)
            if verbose:
                print(f"✓ {field_count} fields ({elapsed:.1f}s)")
                
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
            if verbose:
                print(f"✗ parse error: {e}")
            extracted = {"error": str(e), "name": location.name}
        
        # Create conversation record - store file name for Stage 3 reuse
        record = ConversationRecord(
            manual=pdf_path.name,
            message_name=location.name,
            extraction_timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            pdf_pages={"start": location.page_start, "end": page_end},
            conversation=conversation,
            extracted_structure=extracted,
            review=None,
            uploaded_file_name=uploaded_file.name,  # Keep for Stage 3
        )
        
        return record, usage
        
    finally:
        # Clean up local temp file only - keep Gemini file for Stage 3
        os.unlink(temp_pdf)


def run_extraction(args) -> int:
    """Run Stage 1: Initial extraction."""
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    model = GEMINI_MODELS[args.model]
    print(f"Model: {model}")
    print(f"Processing: {args.pdf_path.name}")
    
    # Initialize stores
    conv_store = ConversationStore(args.conv_dir)
    
    # Discover messages
    locations = discover_message_locations(args.pdf_path)
    print(f"Found {len(locations)} messages in TOC")
    
    # Filter to requested messages
    if args.message:
        if args.message not in locations:
            print(f"Error: {args.message} not found in PDF TOC")
            return 1
        target_messages = [args.message]
    else:
        target_messages = sorted(locations.keys())
    
    # Expand multi-variant messages
    expanded = []
    for msg in target_messages:
        if msg in MULTI_VARIANT_MESSAGES:
            for suffix in MULTI_VARIANT_MESSAGES[msg]:
                expanded.append(msg + suffix)
        else:
            expanded.append(msg)
    target_messages = expanded
    
    if args.dry_run:
        print(f"\n[DRY RUN] Would extract {len(target_messages)} messages")
        for name in target_messages[:20]:
            loc = locations.get(name)
            if loc:
                print(f"  {name}: pages {loc.page_start}-{loc.page_end}")
        if len(target_messages) > 20:
            print(f"  ... and {len(target_messages) - 20} more")
        return 0
    
    # Initialize client
    from google import genai
    client = genai.Client()
    
    # Extract messages
    total_usage = TokenUsage()
    success_count = 0
    manual_stem = args.pdf_path.stem
    
    print(f"\nExtracting {len(target_messages)} messages:")
    
    for msg_name in target_messages:
        # Skip if already extracted (unless --force)
        if not args.force:
            existing = conv_store.load(manual_stem, msg_name)
            if existing and existing.extracted_structure and "error" not in existing.extracted_structure:
                print(f"  {msg_name}: skipped (already extracted)")
                continue
        
        # Get location (handle variants)
        base_name = msg_name
        for base, variants in MULTI_VARIANT_MESSAGES.items():
            for suffix in variants:
                if msg_name == base + suffix:
                    base_name = base
                    break
        
        location = locations.get(base_name) or locations.get(msg_name)
        if not location:
            print(f"  {msg_name}: ✗ location not found")
            continue
        
        # Create variant location
        variant_loc = MessageLocation(
            name=msg_name,
            page_start=location.page_start,
            page_end=location.page_end,
            class_id=location.class_id,
            message_id=location.message_id,
        )
        
        record, usage = extract_message_with_conversation(
            client=client,
            pdf_path=args.pdf_path,
            location=variant_loc,
            model=model,
            max_pages=args.max_pages,
            verbose=True,
        )
        
        total_usage.input_tokens += usage.input_tokens
        total_usage.output_tokens += usage.output_tokens
        
        # Save conversation
        conv_store.save(record)
        
        if record.extracted_structure and "error" not in record.extracted_structure:
            success_count += 1
    
    # Summary
    cost = total_usage.cost(model)
    print(f"\n=== Summary ===")
    print(f"  Messages extracted: {success_count}/{len(target_messages)}")
    print(f"  Input tokens: {total_usage.input_tokens:,}")
    print(f"  Output tokens: {total_usage.output_tokens:,}")
    print(f"  Estimated cost: ${cost:.4f}")
    print(f"  Conversations saved to: {args.conv_dir}")
    
    return 0


def run_review(args) -> int:
    """Run Stage 3: Self-review."""
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    model = GEMINI_MODELS[args.model]
    print(f"Review model: {model}")
    print(f"Processing: {args.pdf_path.name}")
    
    # Initialize stores
    conv_store = ConversationStore(args.conv_dir)
    manual_stem = args.pdf_path.stem
    
    # Load preliminary structures
    preliminary_dir = Path(args.preliminary_dir)
    if not preliminary_dir.exists():
        print(f"Error: Preliminary directory not found: {preliminary_dir}")
        return 1
    
    # Find messages to review
    messages_to_review = conv_store.list_conversations(manual_stem)
    if args.message:
        if args.message not in messages_to_review:
            print(f"Error: No conversation found for {args.message}")
            return 1
        messages_to_review = [args.message]
    
    print(f"Found {len(messages_to_review)} messages to review")
    
    if args.dry_run:
        print(f"\n[DRY RUN] Would review {len(messages_to_review)} messages")
        return 0
    
    # Initialize client
    from google import genai
    client = genai.Client()
    
    total_usage = TokenUsage()
    reviewed_count = 0
    
    for msg_name in messages_to_review:
        # Load conversation
        record = conv_store.load(manual_stem, msg_name)
        if not record:
            print(f"  {msg_name}: ✗ no conversation found")
            continue
        
        if record.review and not args.force:
            print(f"  {msg_name}: skipped (already reviewed)")
            continue
        
        # Detect version from extracted structure
        extracted_version = 0
        if record.extracted_structure and isinstance(record.extracted_structure, dict):
            # Try to detect version from the structure
            payload = record.extracted_structure.get("payload") or {}
            version_field = payload.get("fields", []) if isinstance(payload, dict) else []
            for fld in version_field:
                if fld.get("name", "").lower() == "version":
                    # Version field exists, try to get default value
                    break
            # For now, default to v0
        
        # Load preliminary structure for this message/version
        safe_name = msg_name.replace("-", "_")
        prelim_path = preliminary_dir / "by_version" / f"{safe_name}_v{extracted_version}.json"
        
        # Also try without by_version subfolder
        if not prelim_path.exists():
            prelim_path = preliminary_dir / f"{safe_name}_v{extracted_version}.json"
        if not prelim_path.exists():
            prelim_path = preliminary_dir / f"{safe_name}.json"
        
        if not prelim_path.exists():
            print(f"  {msg_name}: ✗ no preliminary structure found")
            continue
        
        with open(prelim_path) as f:
            preliminary = json.load(f)
        
        # Extract other manual extractions for same version (for context)
        other_extractions = []
        for ext in preliminary.get("all_extractions", []):
            if ext.get("source") != manual_stem:
                other_extractions.append({
                    "source": ext.get("source", "unknown"),
                    "structure": ext.get("structure", {}),
                })
        
        # Build review prompt
        review_prompt = build_review_prompt(
            preliminary_structure=preliminary.get("winning_structure", preliminary.get("structure", preliminary)),
            other_extractions=other_extractions,
            message_version=f"v{extracted_version}",
        )
        
        print(f"  Reviewing {msg_name}...", end=" ", flush=True)
        
        # Try to reuse uploaded file, or re-upload if expired
        uploaded_file = None
        temp_pdf = None
        
        if record.uploaded_file_name:
            try:
                uploaded_file = client.files.get(name=record.uploaded_file_name)
            except Exception:
                pass  # File expired, will re-upload
        
        if uploaded_file is None:
            # Re-upload the PDF pages
            page_start = record.pdf_pages["start"]
            page_end = record.pdf_pages["end"]
            temp_pdf = create_message_pdf(args.pdf_path, page_start, page_end)
            try:
                uploaded_file = client.files.upload(file=temp_pdf)
            except Exception as e:
                print(f"✗ upload failed: {e}")
                if temp_pdf:
                    os.unlink(temp_pdf)
                continue
        
        start_time = time.time()
        
        try:
            response_text, updated_conv, usage = call_gemini_with_chat(
                client=client,
                uploaded_file=uploaded_file,
                conversation_history=record.conversation,
                new_prompt=review_prompt,
                model=model,
                verbose=True,
            )
            
            elapsed = time.time() - start_time
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            
            # Parse review response
            try:
                review_result = json.loads(response_text)
                verdict = review_result.get("verdict", "unknown")
                confidence = review_result.get("confidence", "unknown")
                print(f"✓ {verdict} ({confidence}) ({elapsed:.1f}s)")
            except json.JSONDecodeError as e:
                print(f"✗ parse error: {e}")
                review_result = {"error": str(e), "raw": response_text[:500]}
            
            # Update record and delete the file now that review is complete
            record.conversation = updated_conv
            record.review = review_result
            conv_store.save(record)
            reviewed_count += 1
            
            # Clean up files after successful review
            if temp_pdf:
                os.unlink(temp_pdf)
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
                
        except Exception as e:
            print(f"✗ API error: {e}")
            if temp_pdf and os.path.exists(temp_pdf):
                os.unlink(temp_pdf)
    
    # Summary
    cost = total_usage.cost(model)
    print(f"\n=== Summary ===")
    print(f"  Messages reviewed: {reviewed_count}/{len(messages_to_review)}")
    print(f"  Input tokens: {total_usage.input_tokens:,}")
    print(f"  Output tokens: {total_usage.output_tokens:,}")
    print(f"  Estimated cost: ${cost:.4f}")
    
    return 0


def _review_single_message(task: dict) -> dict:
    """Review a single message (worker function for parallel execution)."""
    from google import genai
    
    prelim_file = task["prelim_file"]
    conv_dir = task["conv_dir"]
    model = task["model"]
    force = task["force"]
    
    result = {"status": "error", "msg_name": "", "version": 0}
    
    # Parse message name and version from filename
    stem = prelim_file.stem
    parts = stem.rsplit("_v", 1)
    if len(parts) != 2:
        result["error"] = "invalid filename format"
        return result
    
    msg_name_safe = parts[0]
    msg_name = msg_name_safe.replace("_", "-")
    version = int(parts[1])
    result["msg_name"] = msg_name
    result["version"] = version
    
    # Load preliminary structure
    preliminary = json.loads(prelim_file.read_text())
    
    # Find an extraction to review
    conv_store = ConversationStore(conv_dir)
    best_record = None
    best_pdf_path = None
    winning_sources = preliminary.get("sources", [])
    
    for manual_dir in conv_dir.iterdir():
        if not manual_dir.is_dir():
            continue
        
        record = conv_store.load(manual_dir.name, msg_name)
        if not record:
            continue
        
        # Check if already reviewed
        if record.review and not force:
            verdict = record.review.get("verdict", "")
            if verdict in ["correct", "extraction_error", "valid_change", "version_bump"]:
                result["status"] = "skipped"
                return result
        
        if best_record is None or manual_dir.name in str(winning_sources):
            best_record = record
            for pdf_dir in Path("interface_manuals").rglob("*.pdf"):
                if manual_dir.name in pdf_dir.stem:
                    best_pdf_path = pdf_dir
                    break
    
    if not best_record:
        result["error"] = "no extraction found"
        return result
    
    if not best_pdf_path:
        result["error"] = f"PDF not found for {best_record.manual}"
        return result
    
    # Build review prompt
    other_extractions = []
    for ext in preliminary.get("all_extractions", []):
        if ext.get("source") != best_record.manual.replace(".pdf", ""):
            other_extractions.append({
                "source": ext.get("source", "unknown"),
                "structure": ext.get("structure", {}),
            })
    
    review_prompt = build_review_prompt(
        preliminary_structure=preliminary.get("winning_structure", preliminary.get("structure", preliminary)),
        other_extractions=other_extractions,
        message_version=f"v{version}",
    )
    
    # Re-upload the PDF pages
    page_start = best_record.pdf_pages["start"]
    page_end = best_record.pdf_pages["end"]
    temp_pdf = create_message_pdf(best_pdf_path, page_start, page_end)
    
    client = genai.Client()
    try:
        uploaded_file = client.files.upload(file=temp_pdf)
    except Exception as e:
        os.unlink(temp_pdf)
        result["error"] = f"upload failed: {e}"
        return result
    
    start_time = time.time()
    
    try:
        response_text, updated_conv, usage = call_gemini_with_chat(
            client=client,
            uploaded_file=uploaded_file,
            conversation_history=best_record.conversation,
            new_prompt=review_prompt,
            model=model,
            verbose=False,
        )
        
        elapsed = time.time() - start_time
        result["elapsed"] = elapsed
        result["usage"] = {"input": usage.input_tokens, "output": usage.output_tokens}
        
        # Parse review response
        try:
            review_result = json.loads(response_text)
            verdict = review_result.get("verdict", "unknown")
            confidence = review_result.get("confidence", "unknown")
            result["verdict"] = verdict
            result["confidence"] = confidence
            result["status"] = "reviewed"
        except json.JSONDecodeError as e:
            review_result = {"error": str(e), "raw": response_text[:500]}
            result["status"] = "parse_error"
            result["error"] = str(e)
        
        # Update record
        best_record.conversation = updated_conv
        best_record.review = review_result
        conv_store.save(best_record)
        
    except Exception as e:
        result["error"] = f"API error: {e}"
    finally:
        os.unlink(temp_pdf)
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
    
    return result


def run_review_all(args) -> int:
    """Run Stage 3: Review each unique message/version ONCE (not per-manual)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    model = GEMINI_MODELS[args.model]
    parallel = args.parallel
    print(f"Review model: {model}")
    print(f"Parallel workers: {parallel}")
    
    conv_dir = args.conv_dir
    preliminary_dir = args.preliminary_dir
    
    if not preliminary_dir.exists():
        print(f"Error: Preliminary directory not found: {preliminary_dir}")
        return 1
    
    # Load all preliminary structures (one per message/version)
    prelim_files = list((preliminary_dir / "by_version").glob("*.json"))
    print(f"Found {len(prelim_files)} unique message/version combinations to review")
    
    if not prelim_files:
        print("No preliminary structures found")
        return 1
    
    # Build task list
    tasks = [
        {
            "prelim_file": pf,
            "conv_dir": conv_dir,
            "model": model,
            "force": args.force,
        }
        for pf in sorted(prelim_files)
    ]
    
    # Process in parallel
    total_input = 0
    total_output = 0
    reviewed_count = 0
    skipped_count = 0
    error_count = 0
    
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {executor.submit(_review_single_message, task): task for task in tasks}
        
        for future in as_completed(futures):
            result = future.result()
            msg_name = result.get("msg_name", "?")
            version = result.get("version", 0)
            
            if result["status"] == "skipped":
                skipped_count += 1
            elif result["status"] == "reviewed":
                reviewed_count += 1
                total_input += result.get("usage", {}).get("input", 0)
                total_output += result.get("usage", {}).get("output", 0)
                elapsed = result.get("elapsed", 0)
                verdict = result.get("verdict", "?")
                confidence = result.get("confidence", "?")
                print(f"  {msg_name} v{version}: ✓ {verdict} ({confidence}) ({elapsed:.1f}s)")
            elif result["status"] == "parse_error":
                error_count += 1
                print(f"  {msg_name} v{version}: ✗ parse error: {result.get('error', '?')}")
            else:
                error_count += 1
                print(f"  {msg_name} v{version}: ✗ {result.get('error', 'unknown error')}")
    
    # Summary
    usage = TokenUsage(input_tokens=total_input, output_tokens=total_output)
    cost = usage.cost(model)
    print(f"\n=== Summary ===")
    print(f"  Messages reviewed: {reviewed_count}")
    print(f"  Already reviewed (skipped): {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"  Input tokens: {total_input:,}")
    print(f"  Output tokens: {total_output:,}")
    print(f"  Estimated cost: ${cost:.4f}")
    
    return 0


def _review_single_extraction(task: dict) -> dict:
    """Review a single extraction (worker function for parallel execution)."""
    from google import genai
    
    conv_file = task["conv_file"]
    preliminary_dir = task["preliminary_dir"]
    model = task["model"]
    force = task["force"]
    
    result = {"status": "error", "manual": "", "msg_name": ""}
    
    # Load the conversation record
    try:
        data = json.loads(conv_file.read_text())
        record = ConversationRecord(**data)
    except Exception as e:
        result["error"] = f"load error: {e}"
        return result
    
    result["manual"] = record.manual
    result["msg_name"] = record.message_name
    
    # Check if already reviewed
    if record.review and not force:
        verdict = record.review.get("verdict", "")
        if verdict in ["correct", "extraction_error", "valid_change", "version_bump"]:
            result["status"] = "skipped"
            return result
    
    # Find preliminary structure for this message
    safe_name = record.message_name.replace("-", "_")
    prelim_candidates = list(preliminary_dir.glob(f"by_version/{safe_name}_v*.json"))
    if not prelim_candidates:
        result["error"] = "no preliminary structure"
        return result
    
    # Use first match (typically v0)
    prelim_file = prelim_candidates[0]
    preliminary = json.loads(prelim_file.read_text())
    
    # Find PDF path
    pdf_path = None
    for pdf in Path("interface_manuals").rglob("*.pdf"):
        manual_stem = record.manual.replace(".pdf", "")
        if manual_stem in pdf.stem:
            pdf_path = pdf
            break
    
    if not pdf_path:
        result["error"] = f"PDF not found for {record.manual}"
        return result
    
    # Build review prompt
    other_extractions = []
    for ext in preliminary.get("all_extractions", []):
        if ext.get("source") != record.manual.replace(".pdf", ""):
            other_extractions.append({
                "source": ext.get("source", "unknown"),
                "structure": ext.get("structure", {}),
            })
    
    review_prompt = build_review_prompt(
        preliminary_structure=preliminary.get("winning_structure", preliminary.get("structure", preliminary)),
        other_extractions=other_extractions[:3],  # Limit to 3 to save tokens
        message_version="v0",
    )
    
    # Upload PDF pages
    page_start = record.pdf_pages["start"]
    page_end = record.pdf_pages["end"]
    temp_pdf = create_message_pdf(pdf_path, page_start, page_end)
    
    client = genai.Client()
    try:
        uploaded_file = client.files.upload(file=temp_pdf)
    except Exception as e:
        os.unlink(temp_pdf)
        result["error"] = f"upload failed: {e}"
        return result
    
    start_time = time.time()
    
    try:
        response_text, updated_conv, usage = call_gemini_with_chat(
            client=client,
            uploaded_file=uploaded_file,
            conversation_history=record.conversation,
            new_prompt=review_prompt,
            model=model,
            verbose=False,
        )
        
        elapsed = time.time() - start_time
        result["elapsed"] = elapsed
        result["usage"] = {"input": usage.input_tokens, "output": usage.output_tokens}
        
        # Parse review response
        try:
            review_result = json.loads(response_text)
            verdict = review_result.get("verdict", "unknown")
            confidence = review_result.get("confidence", "unknown")
            result["verdict"] = verdict
            result["confidence"] = confidence
            result["status"] = "reviewed"
        except json.JSONDecodeError as e:
            review_result = {"error": str(e), "raw": response_text[:500]}
            result["status"] = "parse_error"
            result["error"] = str(e)
        
        # Update record
        record.conversation = updated_conv
        record.review = review_result
        conv_file.write_text(json.dumps(asdict(record), indent=2))
        
    except Exception as e:
        result["error"] = f"API error: {e}"
    finally:
        os.unlink(temp_pdf)
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
    
    return result


def run_review_all_extractions(args) -> int:
    """Run Stage 3b: Review ALL extractions (every conversation file)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    model = GEMINI_MODELS[args.model]
    parallel = args.parallel
    print(f"Review model: {model}")
    print(f"Parallel workers: {parallel}")
    
    conv_dir = args.conv_dir
    preliminary_dir = args.preliminary_dir
    
    if not preliminary_dir.exists():
        print(f"Error: Preliminary directory not found: {preliminary_dir}")
        return 1
    
    # Find ALL conversation files
    conv_files = list(conv_dir.rglob("*.json"))
    print(f"Found {len(conv_files)} total extractions to review")
    
    if not conv_files:
        print("No conversation files found")
        return 1
    
    # Build task list
    tasks = [
        {
            "conv_file": cf,
            "preliminary_dir": preliminary_dir,
            "model": model,
            "force": args.force,
        }
        for cf in sorted(conv_files)
    ]
    
    # Process in parallel
    total_input = 0
    total_output = 0
    reviewed_count = 0
    skipped_count = 0
    error_count = 0
    
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {executor.submit(_review_single_extraction, task): task for task in tasks}
        
        for future in as_completed(futures):
            result = future.result()
            manual = result.get("manual", "?")[:30]
            msg_name = result.get("msg_name", "?")
            
            if result["status"] == "skipped":
                skipped_count += 1
            elif result["status"] == "reviewed":
                reviewed_count += 1
                total_input += result.get("usage", {}).get("input", 0)
                total_output += result.get("usage", {}).get("output", 0)
                elapsed = result.get("elapsed", 0)
                verdict = result.get("verdict", "?")
                print(f"  {msg_name} ({manual}): ✓ {verdict} ({elapsed:.1f}s)")
            elif result["status"] == "parse_error":
                error_count += 1
                print(f"  {msg_name} ({manual}): ✗ parse error")
            else:
                error_count += 1
                err = result.get("error", "unknown")[:50]
                print(f"  {msg_name} ({manual}): ✗ {err}")
    
    # Summary
    usage = TokenUsage(input_tokens=total_input, output_tokens=total_output)
    cost = usage.cost(model)
    print(f"\n=== Summary ===")
    print(f"  Extractions reviewed: {reviewed_count}")
    print(f"  Already reviewed (skipped): {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"  Input tokens: {total_input:,}")
    print(f"  Output tokens: {total_output:,}")
    print(f"  Estimated cost: ${cost:.4f}")
    
    return 0


def build_adjudication_prompt(message_name: str, all_extractions: list) -> str:
    """Build prompt for adjudicating ALL extractions of a message at once."""
    extractions_text = ""
    for i, ext in enumerate(all_extractions, 1):
        source = ext.get("source", f"Source {i}")
        structure = ext.get("structure", {})
        extractions_text += f"\n=== EXTRACTION {i}: {source} ===\n"
        extractions_text += json.dumps(structure, indent=2) + "\n"
    
    return f'''You are adjudicating multiple LLM extractions of the UBX message "{message_name}" from different PDF manuals.

{extractions_text}

=== ADJUDICATION TASK ===

Analyze ALL {len(all_extractions)} extractions above and determine:

1. **Canonical Structure**: What is the correct structure for this message?
2. **Per-Extraction Verdict**: For each extraction, is it correct, has errors, or represents a valid variant?
3. **Valid Variations**: Are there legitimate protocol variations (different receiver versions)?

=== RESPONSE FORMAT ===

Return a JSON object:
{{
  "canonical_structure": {{ ... }},
  "canonical_confidence": "high" | "medium" | "low",
  "extraction_verdicts": [
    {{
      "source": "source_name",
      "verdict": "correct" | "extraction_error" | "valid_variation",
      "issues": ["list of specific errors if any"]
    }}
  ],
  "valid_variations": [
    {{
      "sources": ["list of sources with this variant"],
      "structure": {{ ... }},
      "reason": "Why this is a valid variant"
    }}
  ],
  "reasoning": "Overall explanation of your adjudication"
}}'''


def run_adjudicate(args) -> int:
    """Run adjudication: ALL extractions per message in ONE query."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from google import genai
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    model = GEMINI_MODELS[args.model]
    parallel = args.parallel
    print(f"Adjudication model: {model}")
    print(f"Parallel workers: {parallel}")
    
    conv_dir = args.conv_dir
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Group all extractions by message name
    print("Grouping extractions by message...")
    extractions_by_msg = defaultdict(list)
    
    for manual_dir in conv_dir.iterdir():
        if not manual_dir.is_dir():
            continue
        for conv_file in manual_dir.glob("*.json"):
            try:
                data = json.loads(conv_file.read_text())
                msg_name = data.get("message_name", "")
                structure = data.get("extracted_structure", {})
                if msg_name and structure:
                    extractions_by_msg[msg_name].append({
                        "source": manual_dir.name,
                        "structure": structure,
                    })
            except Exception:
                continue
    
    # Skip already-adjudicated messages
    already_done = set()
    for f in output_dir.glob("*.json"):
        already_done.add(f.stem.replace("_", "-"))
    
    to_adjudicate = {k: v for k, v in extractions_by_msg.items() if k not in already_done}
    print(f"Found {len(extractions_by_msg)} unique messages, {len(already_done)} already done, {len(to_adjudicate)} to adjudicate")
    
    if not to_adjudicate:
        print("All messages already adjudicated!")
        return 0
    
    client = genai.Client()
    total_usage = TokenUsage()
    adjudicated_count = 0
    error_count = 0
    
    def adjudicate_message(msg_name: str, extractions: list) -> dict:
        result = {"msg_name": msg_name, "status": "error"}
        prompt = build_adjudication_prompt(msg_name, extractions)
        
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config={"response_mime_type": "application/json", "max_output_tokens": 16384},
            )
            
            result["usage"] = {
                "input": response.usage_metadata.prompt_token_count,
                "output": response.usage_metadata.candidates_token_count,
            }
            
            adjudication = json.loads(response.text)
            result["adjudication"] = adjudication
            result["status"] = "success"
            result["confidence"] = adjudication.get("canonical_confidence", "unknown")
            result["num_variations"] = len(adjudication.get("valid_variations", []))
            
        except json.JSONDecodeError as e:
            result["error"] = f"parse error: {e}"
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    tasks = [(msg, exts) for msg, exts in sorted(extractions_by_msg.items())]
    
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {executor.submit(adjudicate_message, msg, exts): msg for msg, exts in tasks}
        
        for future in as_completed(futures):
            result = future.result()
            msg_name = result["msg_name"]
            
            if result["status"] == "success":
                adjudicated_count += 1
                total_usage.input_tokens += result.get("usage", {}).get("input", 0)
                total_usage.output_tokens += result.get("usage", {}).get("output", 0)
                conf = result.get("confidence", "?")
                num_var = result.get("num_variations", 0)
                var_str = f" ({num_var} variations)" if num_var > 0 else ""
                print(f"  {msg_name}: done ({conf}){var_str}")
                
                out_file = output_dir / f"{msg_name.replace('-', '_')}.json"
                out_file.write_text(json.dumps({
                    "message_name": msg_name,
                    "num_extractions": len(extractions_by_msg[msg_name]),
                    "adjudication": result["adjudication"],
                }, indent=2))
            else:
                error_count += 1
                err = result.get("error", "unknown")[:50]
                print(f"  {msg_name}: ERROR - {err}")
    
    cost = total_usage.cost(model)
    print(f"\n=== Summary ===")
    print(f"  Messages adjudicated: {adjudicated_count}")
    print(f"  Errors: {error_count}")
    print(f"  Input tokens: {total_usage.input_tokens:,}")
    print(f"  Output tokens: {total_usage.output_tokens:,}")
    print(f"  Estimated cost: ${cost:.4f}")
    print(f"  Results saved to: {output_dir}")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="UBX message extraction with multi-shot conversations (Workflow v2)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Extract subcommand
    extract_parser = subparsers.add_parser("extract", help="Stage 1: Initial extraction")
    extract_parser.add_argument("--pdf-path", type=Path, required=True, help="Path to PDF manual")
    extract_parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()), 
                                default=DEFAULT_EXTRACTION_MODEL, help="Model to use")
    extract_parser.add_argument("--conv-dir", type=Path, default=Path("_working/stage1_extractions"),
                                help="Directory for conversation storage")
    extract_parser.add_argument("--message", type=str, help="Extract specific message only")
    extract_parser.add_argument("--all-messages", action="store_true", help="Extract all messages")
    extract_parser.add_argument("--max-pages", type=int, default=5, help="Max pages per message")
    extract_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    extract_parser.add_argument("--force", action="store_true", help="Re-extract even if cached")
    
    # Review subcommand (per-PDF, legacy)
    review_parser = subparsers.add_parser("review", help="Stage 3: Self-review (per-PDF)")
    review_parser.add_argument("--pdf-path", type=Path, required=True, help="Path to PDF manual")
    review_parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()),
                               default=DEFAULT_REVIEW_MODEL, help="Model to use")
    review_parser.add_argument("--conv-dir", type=Path, default=Path("_working/stage1_extractions"),
                               help="Directory for conversation storage")
    review_parser.add_argument("--preliminary-dir", type=Path, required=True,
                               help="Directory with preliminary structures from voting")
    review_parser.add_argument("--message", type=str, help="Review specific message only")
    review_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    review_parser.add_argument("--force", action="store_true", help="Re-review even if done")
    
    # Review-all subcommand (reviews each message/version ONCE)
    review_all_parser = subparsers.add_parser("review-all", help="Stage 3: Review each message once")
    review_all_parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()),
                                   default=DEFAULT_REVIEW_MODEL, help="Model to use")
    review_all_parser.add_argument("--conv-dir", type=Path, default=Path("_working/stage1_extractions"),
                                   help="Directory for conversation storage")
    review_all_parser.add_argument("--preliminary-dir", type=Path, required=True,
                                   help="Directory with preliminary structures from voting")
    review_all_parser.add_argument("--parallel", type=int, default=1, help="Parallel workers")
    review_all_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    review_all_parser.add_argument("--force", action="store_true", help="Re-review even if done")
    
    # Review-all-extractions subcommand (reviews EVERY extraction, not just one per message)
    review_all_ext_parser = subparsers.add_parser("review-all-extractions", 
                                                   help="Stage 3b: Review ALL extractions")
    review_all_ext_parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()),
                                       default=DEFAULT_REVIEW_MODEL, help="Model to use")
    review_all_ext_parser.add_argument("--conv-dir", type=Path, default=Path("_working/stage1_extractions"),
                                       help="Directory for conversation storage")
    review_all_ext_parser.add_argument("--preliminary-dir", type=Path, required=True,
                                       help="Directory with preliminary structures from voting")
    review_all_ext_parser.add_argument("--parallel", type=int, default=1, help="Parallel workers")
    review_all_ext_parser.add_argument("--force", action="store_true", help="Re-review even if done")
    
    # Adjudicate subcommand (ALL extractions per message in ONE query)
    adjudicate_parser = subparsers.add_parser("adjudicate", 
                                               help="Adjudicate all extractions per message in one query")
    adjudicate_parser.add_argument("--model", choices=list(GEMINI_MODELS.keys()),
                                   default="3-pro", help="Model to use (default: 3-pro)")
    adjudicate_parser.add_argument("--conv-dir", type=Path, default=Path("_working/stage1_extractions"),
                                   help="Directory for conversation storage")
    adjudicate_parser.add_argument("--output-dir", type=Path, default=Path("_working/stage3_adjudication"),
                                   help="Directory for adjudication results")
    adjudicate_parser.add_argument("--parallel", type=int, default=10, help="Parallel workers")
    
    args = parser.parse_args()
    
    if args.command == "extract":
        if not args.message and not args.all_messages:
            print("Error: specify --message or --all-messages")
            return 1
        return run_extraction(args)
    elif args.command == "review":
        return run_review(args)
    elif args.command == "review-all":
        return run_review_all(args)
    elif args.command == "review-all-extractions":
        return run_review_all_extractions(args)
    elif args.command == "adjudicate":
        return run_adjudicate(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
