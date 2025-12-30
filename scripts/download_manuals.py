#!/usr/bin/env python3
"""Download all interface manuals from interface_manual_urls.json.

Downloads PDFs to device-specific subdirectories under interface_manuals/.
The same PDF may be downloaded to multiple device directories if shared.
"""

import json
from pathlib import Path

import requests


def main():
    # Look for URLs file in interface_manuals/ directory
    script_dir = Path(__file__).parent.parent
    urls_file = script_dir / "interface_manuals" / "manuals.json"
    data = json.loads(urls_file.read_text(encoding="utf-8"))

    # Collect all download tasks (url -> list of local_paths)
    download_tasks: list[tuple[str, Path]] = []
    for module, info in data.items():
        for manual in info.get("manuals", []):
            url = manual["url"]
            local_path = Path(manual.get("local_path", ""))
            if local_path:
                download_tasks.append((url, local_path))

    print(f"Found {len(download_tasks)} manual locations to check")

    downloaded = 0
    skipped = 0
    failed = 0

    # Cache downloaded content to avoid re-downloading same URL
    url_cache: dict[str, bytes] = {}

    for url, local_path in sorted(download_tasks, key=lambda x: str(x[1])):
        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if local_path.exists():
            print(f"  [SKIP] {local_path}")
            skipped += 1
            continue

        print(f"  [DOWN] {local_path}...")
        try:
            # Use cached content if already downloaded
            if url in url_cache:
                content = url_cache[url]
            else:
                response = requests.get(url, timeout=120)
                response.raise_for_status()
                content = response.content
                url_cache[url] = content

            local_path.write_bytes(content)
            downloaded += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            failed += 1

    print(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed")
    
    # Count total PDFs across all subdirectories
    out_dir = Path("interface_manuals")
    total_pdfs = len(list(out_dir.glob("**/*.pdf")))
    print(f"Total PDF files in {out_dir}: {total_pdfs}")


if __name__ == "__main__":
    main()
