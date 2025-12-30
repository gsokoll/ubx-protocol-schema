#!/usr/bin/env python3
"""Extract UBX message definitions from PDF pages using Anthropic Claude.

This script uses Claude's vision capabilities to parse PDF page images
and extract structured UBX message definitions into JSON format.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extraction.extractor import (
    ExtractionResult,
    TokenUsage,
    call_claude_for_extraction,
    compute_cache_key,
    hash_image,
    normalize_extraction,
)
from src.extraction.pdf_utils import (
    discover_messages_from_toc,
    download_pdf,
    extract_pages_as_images,
    extract_pages_as_images_cropped,
    find_message_locations,
)


def load_cache(cache_dir: Path) -> dict[str, Any]:
    """Load extraction cache from disk."""
    cache_file = cache_dir / "extraction_cache.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache_dir: Path, cache: dict[str, Any]) -> None:
    """Save extraction cache to disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "extraction_cache.json"
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def select_messages_from_json(extracted_path: Path) -> list[str]:
    """Get all message names from an existing extracted JSON file."""
    data = json.loads(extracted_path.read_text(encoding="utf-8"))
    messages = data.get("messages", [])
    return [m.get("name") for m in messages if m.get("name")]


def get_unique_manuals_from_json(manuals_json: Path) -> list[dict]:
    """Get unique interface description manuals from manuals.json."""
    data = json.loads(manuals_json.read_text(encoding="utf-8"))
    
    seen_titles = set()
    unique_manuals = []
    
    for module_name, module_data in data.items():
        for manual in module_data.get("manuals", []):
            title = manual.get("title", "")
            # Only include interface description manuals (case-insensitive)
            title_lower = title.lower()
            if "interfacedescription" not in title_lower and "protspec" not in title_lower:
                continue
            
            if title not in seen_titles:
                seen_titles.add(title)
                unique_manuals.append({
                    "title": title,
                    "local_path": manual.get("local_path"),
                    "url": manual.get("url"),
                })
    
    return unique_manuals


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract UBX message definitions from PDF pages using Claude."
    )

    parser.add_argument(
        "--extracted-json",
        type=Path,
        help="Path to existing extracted JSON (for message list reference)",
    )

    pdf_group = parser.add_mutually_exclusive_group(required=False)
    pdf_group.add_argument("--pdf-url", type=str, help="PDF URL to download/cache")
    pdf_group.add_argument("--pdf-path", type=Path, help="Path to a local PDF")

    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Extract specific UBX message(s) by name (repeatable)",
    )
    parser.add_argument(
        "--all-messages",
        action="store_true",
        help="Extract all UBX messages found in --extracted-json",
    )
    parser.add_argument(
        "--scan-toc",
        action="store_true",
        help="Discover and extract all UBX messages from PDF table of contents (no reference JSON needed)",
    )
    parser.add_argument(
        "--all-manuals",
        action="store_true",
        help="Extract from all manuals listed in interface_manuals/manuals.json",
    )

    parser.add_argument("--model", type=str, default="claude-sonnet-4-20250514")
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum pages to render per message (default: 3)",
    )

    parser.add_argument(
        "--crop-top-ratio",
        type=float,
        default=0.095,
        help="Crop fraction from top of pages (default: 0.095)",
    )
    parser.add_argument(
        "--crop-bottom-ratio",
        type=float,
        default=0.085,
        help="Crop fraction from bottom of pages (default: 0.085)",
    )
    parser.add_argument(
        "--no-crop",
        action="store_true",
        help="Disable page cropping",
    )

    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("extracted_anthropic"),
        help="Output directory for extracted JSON files",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cached extractions if available",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-extraction even if cached",
    )

    return parser.parse_args()


def extract_single_pdf(
    pdf_path: Path,
    target_names: list[str],
    args: argparse.Namespace,
    cache: dict,
    cache_dir: Path,
) -> tuple[int, int, list[dict]]:
    """Extract messages from a single PDF. Returns (success_count, total_count, messages)."""
    from src.extraction.extractor import TokenUsage
    
    locations = find_message_locations(pdf_path, target_names)
    print(f"Found PDF locations for {len(locations)} of {len(target_names)} messages")

    results: list[ExtractionResult] = []
    extracted_messages: list[dict] = []
    total_usage = TokenUsage()

    for msg_name in target_names:
        if msg_name not in locations:
            print(f"Skipping {msg_name}: not found in PDF TOC")
            results.append(ExtractionResult(
                message_name=msg_name,
                success=False,
                errors=["Message not found in PDF TOC"],
            ))
            continue

        loc = locations[msg_name]
        page_end = min(loc.page_end, loc.page_start + max(1, args.max_pages))

        print(f"\nExtracting {msg_name} (pages {loc.page_start}-{page_end})")

        if args.no_crop:
            images = extract_pages_as_images(pdf_path, loc.page_start, page_end)
        else:
            images = extract_pages_as_images_cropped(
                pdf_path,
                loc.page_start,
                page_end,
                crop_top_ratio=args.crop_top_ratio,
                crop_bottom_ratio=args.crop_bottom_ratio,
            )

        page_hashes = [hash_image(img) for img in images]
        cache_key = compute_cache_key(
            pdf_path=str(pdf_path),
            message_name=msg_name,
            page_hashes=page_hashes,
            model=args.model,
        )

        if args.use_cache and not args.force and cache_key in cache:
            print(f"  Using cached extraction (key: {cache_key})")
            cached = cache[cache_key]
            result = normalize_extraction(cached, msg_name, cache_key)
        else:
            print(f"  Calling Claude ({len(images)} pages)...")
            try:
                raw, usage = call_claude_for_extraction(
                    images=images,
                    message_name=msg_name,
                    expected_class_id=loc.class_id or None,
                    expected_message_id=loc.message_id or None,
                    model=args.model,
                    max_tokens=args.max_tokens,
                )
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens
                total_usage.cache_read_tokens += usage.cache_read_tokens
                total_usage.cache_creation_tokens += usage.cache_creation_tokens
            except Exception as e:
                raw = {"error": str(e)}

            result = normalize_extraction(raw, msg_name, cache_key)

            if result.success and args.use_cache:
                cache[cache_key] = raw
                save_cache(cache_dir, cache)

        results.append(result)

        status = "✅" if result.success else "❌"
        print(f"  Result: {status}")
        if result.errors:
            for err in result.errors[:3]:
                print(f"    Error: {err}")
        if result.warnings:
            for warn in result.warnings[:3]:
                print(f"    Warning: {warn}")

        if result.success and result.message:
            if result.message.get("name") != msg_name:
                result.message["name"] = msg_name
            extracted_messages.append(result.message)

    success_count = sum(1 for r in results if r.success)
    
    # Print token usage
    if total_usage.input_tokens > 0 or total_usage.output_tokens > 0:
        print(f"\nToken usage:")
        print(f"  Input tokens:  {total_usage.input_tokens:,}")
        print(f"  Output tokens: {total_usage.output_tokens:,}")
        if total_usage.cache_read_tokens:
            print(f"  Cache read:    {total_usage.cache_read_tokens:,}")
        if total_usage.cache_creation_tokens:
            print(f"  Cache create:  {total_usage.cache_creation_tokens:,}")
        input_cost = total_usage.input_tokens * 3.0 / 1_000_000
        output_cost = total_usage.output_tokens * 15.0 / 1_000_000
        total_cost = input_cost + output_cost
        print(f"  Estimated cost: ${total_cost:.2f}")

    # Write output
    if extracted_messages:
        pdf_stem = pdf_path.stem
        out_file = args.out_dir / f"{pdf_stem}_anthropic.json"

        output = {
            "schema_version": "1.1",
            "source_document": {"filename": pdf_path.name},
            "extraction_metadata": {
                "model": args.model,
                "max_pages": args.max_pages,
                "cropping": {
                    "enabled": not args.no_crop,
                    "top_ratio": 0.0 if args.no_crop else args.crop_top_ratio,
                    "bottom_ratio": 0.0 if args.no_crop else args.crop_bottom_ratio,
                },
            },
            "messages": extracted_messages,
        }

        out_file.write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"Wrote {len(extracted_messages)} messages to {out_file}")

    # Write errors
    failed = [r for r in results if not r.success]
    if failed:
        errors_file = args.out_dir / f"{pdf_path.stem}_errors.json"
        errors_data = [
            {"message": r.message_name, "errors": r.errors, "warnings": r.warnings}
            for r in failed
        ]
        errors_file.write_text(json.dumps(errors_data, indent=2), encoding="utf-8")
        print(f"Wrote {len(failed)} errors to {errors_file}")

    return success_count, len(results), extracted_messages


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        return 2

    args = _parse_args()
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    cache_dir = script_dir / ".extraction_cache"
    pdf_cache_dir = script_dir / ".pdf_cache"
    pdf_cache_dir.mkdir(exist_ok=True)
    
    # Handle --all-manuals mode
    if args.all_manuals:
        manuals_json = project_root / "interface_manuals" / "manuals.json"
        if not manuals_json.exists():
            print(f"Error: {manuals_json} not found")
            return 2
        
        manuals = get_unique_manuals_from_json(manuals_json)
        print(f"Found {len(manuals)} unique interface description manuals\n")
        
        args.out_dir.mkdir(parents=True, exist_ok=True)
        
        # Check which need extraction
        to_extract = []
        for manual in manuals:
            title = manual["title"]
            output_file = args.out_dir / f"{title}_anthropic.json"
            
            if output_file.exists() and not args.force:
                print(f"  [SKIP] {title} (already exists)")
            else:
                to_extract.append(manual)
                print(f"  [TODO] {title}")
        
        print(f"\n{len(to_extract)} manuals to extract, {len(manuals) - len(to_extract)} skipped")
        
        if not to_extract:
            print("\nNothing to extract. Use --force to re-extract.")
            return 0
        
        # Estimate cost and confirm
        print(f"\nEstimated cost: ~${len(to_extract) * 2.50:.2f} (varies by manual size)")
        response = input("Proceed with extraction? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            return 0
        
        cache = load_cache(cache_dir) if args.use_cache else {}
        total_success = 0
        total_count = 0
        
        for i, manual in enumerate(to_extract, 1):
            title = manual["title"]
            local_path = project_root / manual["local_path"]
            
            print(f"\n{'='*60}")
            print(f"[{i}/{len(to_extract)}] Extracting: {title}")
            print(f"{'='*60}")
            
            if not local_path.exists():
                print(f"  ERROR: PDF not found: {local_path}")
                print(f"  Run: uv run python scripts/download_manuals.py")
                continue
            
            target_names = discover_messages_from_toc(local_path)
            print(f"Discovered {len(target_names)} messages from PDF TOC")
            
            try:
                success, total, _ = extract_single_pdf(
                    local_path, target_names, args, cache, cache_dir
                )
                total_success += success
                total_count += total
                print(f"\n✓ {title}: {success}/{total} successful")
            except KeyboardInterrupt:
                print("\n\nInterrupted by user")
                break
            except Exception as e:
                print(f"\n✗ {title}: Failed with error: {e}")
        
        print(f"\n{'='*60}")
        print(f"BATCH EXTRACTION COMPLETE: {total_success}/{total_count} messages")
        return 0
    
    # Single PDF mode - require pdf-url or pdf-path
    if not args.pdf_url and not args.pdf_path:
        print("Error: --pdf-url or --pdf-path required (or use --all-manuals)")
        return 2

    if args.pdf_url:
        try:
            pdf_path = download_pdf(args.pdf_url, pdf_cache_dir)
        except Exception as e:
            print(f"Error: failed to download PDF: {e}")
            return 2
    else:
        pdf_path = args.pdf_path
        if not pdf_path.exists():
            print(f"Error: PDF not found: {pdf_path}")
            return 2

    if args.message:
        target_names = args.message
    elif args.scan_toc:
        target_names = discover_messages_from_toc(pdf_path)
        print(f"Discovered {len(target_names)} messages from PDF TOC (including variants)")
    elif args.all_messages and args.extracted_json:
        target_names = select_messages_from_json(args.extracted_json)
        print(f"Found {len(target_names)} messages in {args.extracted_json}")
    else:
        print("Error: specify --message, --scan-toc, or --all-messages with --extracted-json")
        return 2

    print(f"Target messages: {len(target_names)}")

    cache = load_cache(cache_dir) if args.use_cache else {}
    args.out_dir.mkdir(parents=True, exist_ok=True)

    success_count, total_count, _ = extract_single_pdf(
        pdf_path, target_names, args, cache, cache_dir
    )

    print(f"\n{'='*50}")
    print(f"Extraction complete: {success_count}/{total_count} successful")
    return 0 if success_count == total_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
