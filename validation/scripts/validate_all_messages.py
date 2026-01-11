#!/usr/bin/env python3
"""
Batch validate all remaining UBX messages.

Processes messages that haven't been validated yet, with rate limiting
and progress tracking. Can be interrupted and resumed.

Usage:
    uv run python validation/scripts/validate_all_messages.py
    uv run python validation/scripts/validate_all_messages.py --limit 10
    uv run python validation/scripts/validate_all_messages.py --workers 4
    uv run python validation/scripts/validate_all_messages.py --status
    uv run python validation/scripts/validate_all_messages.py --revalidate UBX-NAV-PVT

    # Fix missing bitfields
    uv run python validation/scripts/validate_all_messages.py --fix-bitfields
    uv run python validation/scripts/validate_all_messages.py --fix-all --workers 2
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "validation"))

from validation.scripts.validate_message import (
    validate_message,
    load_canonical_messages,
    extract_missing_bitfields,
    apply_extracted_bitfields,
)

# Graceful shutdown flag
shutdown_requested = False


def signal_handler(signum, frame):
    global shutdown_requested
    print("\n\nShutdown requested, finishing current message...")
    shutdown_requested = True


def load_message_status() -> dict:
    """Load current validation status."""
    status_file = PROJECT_ROOT / "validation" / "reports" / "message_status.json"
    if status_file.exists():
        with open(status_file) as f:
            return json.load(f)
    return {"messages": {}}


def save_message_status(status: dict):
    """Save validation status."""
    status_file = PROJECT_ROOT / "validation" / "reports" / "message_status.json"
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, "w") as f:
        json.dump(status, f, indent=2)


def get_remaining_messages() -> list[str]:
    """Get list of messages not yet validated."""
    canonical = load_canonical_messages()
    all_messages = sorted(canonical.keys())

    status = load_message_status()
    validated = set(status.get("messages", {}).keys())

    return [m for m in all_messages if m not in validated]


def get_messages_with_missing_bitfields() -> list[str]:
    """Get list of messages with X-type fields missing bitfield definitions."""
    canonical = load_canonical_messages()
    missing = []

    for name, message in canonical.items():
        payload = message.get("payload", {})
        fields = payload.get("fields", [])

        for field in fields:
            data_type = field.get("data_type", "")
            if data_type.startswith("X") and "bitfield" not in field:
                missing.append(name)
                break

    return sorted(missing)


def fix_message_bitfields(message_name: str, dry_run: bool = False) -> dict:
    """Extract and apply missing bitfields for a message."""
    try:
        result = extract_missing_bitfields(message_name, verbose=False)

        if not result or not result.get("extracted"):
            return {
                "status": "no_extraction",
                "message": "No bitfields extracted",
            }

        extracted = result["extracted"]
        fields_fixed = len(extracted.get("fields", []))

        if dry_run:
            return {
                "status": "dry_run",
                "fields_fixed": fields_fixed,
                "message": f"Would fix {fields_fixed} fields",
            }

        # Apply the fix
        apply_extracted_bitfields(message_name, extracted)

        return {
            "status": "fixed",
            "fields_fixed": fields_fixed,
            "message": f"Fixed {fields_fixed} fields",
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }


def show_status():
    """Show current validation status."""
    canonical = load_canonical_messages()
    status = load_message_status()
    messages = status.get("messages", {})
    
    total = len(canonical)
    validated = len(messages)
    remaining = total - validated
    
    valid_count = sum(1 for m in messages.values() if m.get("status") == "valid")
    needs_review = sum(1 for m in messages.values() if m.get("status") == "needs_review")
    
    print(f"=== Validation Status ===")
    print(f"Total messages:    {total}")
    print(f"Validated:         {validated} ({100*validated/total:.1f}%)")
    print(f"  - Valid:         {valid_count}")
    print(f"  - Needs review:  {needs_review}")
    print(f"Remaining:         {remaining}")
    
    if needs_review > 0:
        print(f"\nMessages needing review:")
        for name, data in sorted(messages.items()):
            if data.get("status") == "needs_review":
                print(f"  {name}: {data.get('mismatches', 0)} mismatches")


# Thread-safe status updates
status_lock = threading.Lock()

# Shared resources - loaded once
_shared_resources = {
    "canonical_messages": None,
    "manuals": None,
    "metadata": None,
    "client": None,
}


def init_shared_resources():
    """Initialize shared resources once before parallel processing."""
    from google import genai
    from validation.scripts.validate_message import (
        load_canonical_messages,
        find_pdf_manuals,
        load_manual_metadata,
    )
    
    if _shared_resources["canonical_messages"] is None:
        print("Loading shared resources...")
        _shared_resources["canonical_messages"] = load_canonical_messages()
        _shared_resources["manuals"] = find_pdf_manuals()
        _shared_resources["metadata"] = load_manual_metadata()
        _shared_resources["client"] = genai.Client()
        print(f"  Loaded {len(_shared_resources['canonical_messages'])} messages")
        print(f"  Loaded {len(_shared_resources['manuals'])} manuals")


def validate_single_message_fast(message_name: str) -> tuple[str, dict]:
    """Validate a single message using shared resources. Thread-safe."""
    from google import genai
    from validation.scripts.validate_message import validate_message_against_manual
    
    try:
        canonical_messages = _shared_resources["canonical_messages"]
        manuals = _shared_resources["manuals"]
        all_metadata = _shared_resources["metadata"]
        
        # Each thread creates its own client (genai.Client not thread-safe)
        client = genai.Client()
        
        if message_name not in canonical_messages:
            return message_name, {"status": "error", "error": "Message not found"}
        
        message = canonical_messages[message_name]
        results = []
        
        for pdf_path in manuals:
            manual_name = pdf_path.stem
            metadata = all_metadata.get(manual_name)
            
            result = validate_message_against_manual(
                message=message,
                pdf_path=pdf_path,
                client=client,
                metadata=metadata,
                verbose=False,
            )
            results.append(result)
        
        if results:
            matches = sum(1 for r in results if r.matches is True)
            mismatches = sum(1 for r in results if r.matches is False)
            
            msg_status = "valid" if mismatches == 0 else "needs_review"
            
            return message_name, {
                "status": msg_status,
                "last_validated": datetime.now(timezone.utc).isoformat(),
                "manuals_checked": len(results),
                "matches": matches,
                "mismatches": mismatches,
            }
        return message_name, {"status": "no_results"}
        
    except Exception as e:
        return message_name, {
            "status": "error",
            "last_validated": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def validate_single_message(message_name: str) -> tuple[str, dict]:
    """Validate a single message and return result. Thread-safe."""
    try:
        results = validate_message(message_name, verbose=False, quiet=True)
        
        if results:
            matches = sum(1 for r in results if r.matches is True)
            mismatches = sum(1 for r in results if r.matches is False)
            
            msg_status = "valid" if mismatches == 0 else "needs_review"
            
            return message_name, {
                "status": msg_status,
                "last_validated": datetime.now(timezone.utc).isoformat(),
                "manuals_checked": len(results),
                "matches": matches,
                "mismatches": mismatches,
            }
        return message_name, {"status": "no_results"}
        
    except Exception as e:
        return message_name, {
            "status": "error",
            "last_validated": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


def validate_batch_parallel(
    messages: list[str],
    limit: int | None = None,
    workers: int = 4,
):
    """Validate messages in parallel using thread pool."""
    global shutdown_requested
    
    if limit:
        messages = messages[:limit]
    
    total = len(messages)
    print(f"Validating {total} messages with {workers} workers...")
    print(f"Press Ctrl+C to stop (may take a moment to finish current batch)\n")
    
    status = load_message_status()
    completed = [0]
    
    def process_result(future):
        """Process a completed future."""
        if shutdown_requested:
            return
        
        completed[0] += 1
        try:
            name, result = future.result(timeout=0.1)
            
            with status_lock:
                status["messages"][name] = result
                save_message_status(status)
            
            mismatches = result.get("mismatches", 0)
            manuals = result.get("manuals_checked", 0)
            if result.get("status") == "error":
                print(f"[{completed[0]}/{total}] {name}: ERROR - {result.get('error', '')[:50]}")
            elif mismatches > 0:
                print(f"[{completed[0]}/{total}] {name}: ⚠ {mismatches} mismatches ({manuals} manuals)")
            else:
                print(f"[{completed[0]}/{total}] {name}: ✓ ({manuals} manuals)")
                
        except Exception as e:
            print(f"[{completed[0]}/{total}] ERROR - {e}")
    
    # Process in batches for better Ctrl+C handling
    batch_size = workers * 2
    for batch_start in range(0, len(messages), batch_size):
        if shutdown_requested:
            print("\nShutdown requested, stopping...")
            break
        
        batch = messages[batch_start:batch_start + batch_size]
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(validate_single_message, msg) for msg in batch]
            
            for future in as_completed(futures):
                if shutdown_requested:
                    break
                process_result(future)
    
    print(f"\n=== Complete ===")
    show_status()


def fix_batch(
    messages: list[str],
    limit: int | None = None,
    delay: float = 2.0,
    dry_run: bool = False,
):
    """Fix missing bitfields for a batch of messages."""
    global shutdown_requested

    if limit:
        messages = messages[:limit]

    total = len(messages)
    action = "Would fix" if dry_run else "Fixing"
    print(f"{action} {total} messages with missing bitfields...\n")

    fixed_count = 0
    error_count = 0

    for i, message_name in enumerate(messages, 1):
        if shutdown_requested:
            print(f"\nStopped after {i-1} messages (Ctrl+C)")
            break

        print(f"[{i}/{total}] {message_name}...", end=" ", flush=True)

        result = fix_message_bitfields(message_name, dry_run=dry_run)

        status = result.get("status")
        if status == "fixed":
            fixed_count += 1
            print(f"✓ {result.get('message', '')}")
        elif status == "dry_run":
            fixed_count += 1
            print(f"[DRY RUN] {result.get('message', '')}")
        elif status == "no_extraction":
            print(f"- {result.get('message', '')}")
        elif status == "error":
            error_count += 1
            print(f"ERROR: {result.get('error', '')[:50]}")
        else:
            print(f"? {result}")

        # Rate limiting between messages (API calls are expensive)
        if i < total and not shutdown_requested:
            time.sleep(delay)

    print(f"\n=== Complete ===")
    print(f"Messages processed: {total}")
    print(f"Fixed: {fixed_count}")
    print(f"Errors: {error_count}")


def validate_batch(
    messages: list[str],
    limit: int | None = None,
    delay: float = 1.0,
):
    """Validate a batch of messages sequentially."""
    global shutdown_requested
    
    if limit:
        messages = messages[:limit]
    
    total = len(messages)
    print(f"Validating {total} messages...\n")
    
    status = load_message_status()
    
    for i, message_name in enumerate(messages, 1):
        if shutdown_requested:
            print(f"\nStopped after {i-1} messages (Ctrl+C)")
            break
        
        print(f"[{i}/{total}] {message_name}")
        
        try:
            results = validate_message(message_name, verbose=False)
            
            if results:
                matches = sum(1 for r in results if r.matches is True)
                mismatches = sum(1 for r in results if r.matches is False)
                
                msg_status = "valid" if mismatches == 0 else "needs_review"
                
                status["messages"][message_name] = {
                    "status": msg_status,
                    "last_validated": datetime.now(timezone.utc).isoformat(),
                    "manuals_checked": len(results),
                    "matches": matches,
                    "mismatches": mismatches,
                }
                
                # Save after each message (allows resume)
                save_message_status(status)
                
                if mismatches > 0:
                    print(f"        ⚠ {mismatches} mismatches - needs review")
            
        except Exception as e:
            print(f"        ERROR: {e}")
            status["messages"][message_name] = {
                "status": "error",
                "last_validated": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }
            save_message_status(status)
        
        # Rate limiting between messages
        if i < total and not shutdown_requested:
            time.sleep(delay)
    
    print(f"\n=== Complete ===")
    show_status()


def main():
    parser = argparse.ArgumentParser(
        description="Batch validate all UBX messages"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current validation status"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of messages to process"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between messages in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--revalidate",
        help="Revalidate a specific message"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Revalidate all messages (not just remaining)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1, sequential)"
    )
    parser.add_argument(
        "--fix-bitfields",
        action="store_true",
        help="Extract and apply missing bitfield definitions"
    )
    parser.add_argument(
        "--fix-all",
        action="store_true",
        help="Fix all messages (same as --fix-bitfields --all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes"
    )

    args = parser.parse_args()
    
    if args.status:
        show_status()
        return 0

    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Handle fix modes
    if args.fix_bitfields or args.fix_all:
        messages = get_messages_with_missing_bitfields()
        if not messages:
            print("No messages with missing bitfields found.")
            return 0

        print(f"Found {len(messages)} messages with missing bitfields:")
        for m in messages[:10]:
            print(f"  - {m}")
        if len(messages) > 10:
            print(f"  ... and {len(messages) - 10} more")
        print()

        fix_batch(
            messages=messages,
            limit=args.limit,
            delay=args.delay,
            dry_run=args.dry_run,
        )
        return 0

    if args.revalidate:
        # Revalidate specific message
        messages = [args.revalidate]
    elif args.all:
        # Revalidate all messages
        canonical = load_canonical_messages()
        messages = sorted(canonical.keys())
    else:
        # Only remaining messages
        messages = get_remaining_messages()
    
    if not messages:
        print("No messages to validate.")
        show_status()
        return 0
    
    if args.workers > 1:
        validate_batch_parallel(
            messages=messages,
            limit=args.limit,
            workers=args.workers,
        )
    else:
        validate_batch(
            messages=messages,
            limit=args.limit,
            delay=args.delay,
        )
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
