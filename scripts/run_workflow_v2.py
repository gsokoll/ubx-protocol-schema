#!/usr/bin/env python3
"""Workflow v2 Orchestrator: Multi-shot extraction with self-review.

This script orchestrates the full workflow:
  Stage 1: Initial extraction (Gemini 2.5 Flash)
  Stage 2: Preliminary voting/structure determination
  Stage 3: LLM self-review (Gemini 3 Flash)
  Stage 4: Final automated determination

Usage:
    # Run full workflow on all PDFs
    uv run python scripts/run_workflow_v2.py --pdf-dir interface_manuals

    # Run specific stage only
    uv run python scripts/run_workflow_v2.py --stage 1 --pdf-dir interface_manuals
    uv run python scripts/run_workflow_v2.py --stage 2
    uv run python scripts/run_workflow_v2.py --stage 3 --pdf-dir interface_manuals
    uv run python scripts/run_workflow_v2.py --stage 4

    # Dry run to see what would happen
    uv run python scripts/run_workflow_v2.py --dry-run --pdf-dir interface_manuals
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def find_pdf_manuals(pdf_dir: Path) -> list[Path]:
    """Find all interface manual PDFs."""
    pdfs = list(pdf_dir.rglob("*.pdf"))
    # Filter to likely interface manuals
    interface_pdfs = [p for p in pdfs if "interface" in p.name.lower() or "ubx" in p.name.lower()]
    if not interface_pdfs:
        interface_pdfs = pdfs
    return sorted(interface_pdfs)


def run_stage_1(args, pdfs: list[Path]) -> int:
    """Run Stage 1: Initial extraction."""
    print("\n" + "="*60)
    print("STAGE 1: Initial Extraction (Gemini 2.5 Flash)")
    print("="*60)
    
    for pdf in pdfs:
        print(f"\nProcessing: {pdf.name}")
        
        cmd = [
            sys.executable, "scripts/extract_messages_v2.py", "extract",
            "--pdf-path", str(pdf),
            "--all-messages",
            "--conv-dir", str(args.conv_dir),
            "--model", "flash",
        ]
        
        if args.dry_run:
            cmd.append("--dry-run")
        
        result = subprocess.run(cmd, cwd=args.project_dir)
        if result.returncode != 0:
            print(f"Warning: Extraction failed for {pdf.name}")
    
    return 0


def run_stage_2(args) -> int:
    """Run Stage 2: Preliminary voting."""
    print("\n" + "="*60)
    print("STAGE 2: Preliminary Voting")
    print("="*60)
    
    cmd = [
        sys.executable, "scripts/vote_preliminary_v2.py",
        "--conv-dir", str(args.conv_dir),
        "--output-dir", str(args.preliminary_dir),
    ]
    
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    
    result = subprocess.run(cmd, cwd=args.project_dir)
    return result.returncode


def run_stage_3(args, pdfs: list[Path]) -> int:
    """Run Stage 3: Self-review."""
    print("\n" + "="*60)
    print("STAGE 3: LLM Self-Review (Gemini 3 Flash)")
    print("="*60)
    
    for pdf in pdfs:
        print(f"\nReviewing extractions for: {pdf.name}")
        
        cmd = [
            sys.executable, "scripts/extract_messages_v2.py", "review",
            "--pdf-path", str(pdf),
            "--conv-dir", str(args.conv_dir),
            "--preliminary-dir", str(args.preliminary_dir),
            "--model", "3-flash",
        ]
        
        if args.dry_run:
            cmd.append("--dry-run")
        
        result = subprocess.run(cmd, cwd=args.project_dir)
        if result.returncode != 0:
            print(f"Warning: Review failed for {pdf.name}")
    
    return 0


def run_stage_4(args) -> int:
    """Run Stage 4: Final determination."""
    print("\n" + "="*60)
    print("STAGE 4: Final Automated Determination")
    print("="*60)
    
    cmd = [
        sys.executable, "scripts/final_determination_v2.py",
        "--conv-dir", str(args.conv_dir),
        "--output-dir", str(args.output_dir),
        "--reports-dir", str(args.reports_dir),
    ]
    
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    
    result = subprocess.run(cmd, cwd=args.project_dir)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Workflow v2 Orchestrator: Multi-shot extraction with self-review"
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=Path("interface_manuals"),
        help="Directory containing PDF manuals",
    )
    parser.add_argument(
        "--stage",
        type=int,
        choices=[1, 2, 3, 4],
        help="Run specific stage only (1-4)",
    )
    parser.add_argument(
        "--conv-dir",
        type=Path,
        default=Path("_working/stage1_extractions"),
        help="Directory for conversation storage",
    )
    parser.add_argument(
        "--preliminary-dir",
        type=Path,
        default=Path("data/preliminary"),
        help="Directory for preliminary structures",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/final"),
        help="Directory for final output",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=Path("analysis_reports/v2"),
        help="Directory for reports",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    
    args = parser.parse_args()
    
    # Set project directory
    args.project_dir = Path(__file__).parent.parent
    
    # Validate PDF directory for stages that need it
    pdfs = []
    if args.stage in (1, 3, None):
        if not args.pdf_dir.exists():
            print(f"Error: PDF directory not found: {args.pdf_dir}")
            return 1
        pdfs = find_pdf_manuals(args.pdf_dir)
        if not pdfs:
            print(f"Error: No PDF files found in {args.pdf_dir}")
            return 1
        print(f"Found {len(pdfs)} PDF manuals")
    
    print("\n" + "#"*60)
    print("# WORKFLOW V2: Multi-shot Extraction with Self-Review")
    print("#"*60)
    
    if args.dry_run:
        print("\n[DRY RUN MODE - No changes will be made]")
    
    # Run stages
    if args.stage:
        # Run single stage
        if args.stage == 1:
            return run_stage_1(args, pdfs)
        elif args.stage == 2:
            return run_stage_2(args)
        elif args.stage == 3:
            return run_stage_3(args, pdfs)
        elif args.stage == 4:
            return run_stage_4(args)
    else:
        # Run all stages
        ret = run_stage_1(args, pdfs)
        if ret != 0:
            return ret
        
        ret = run_stage_2(args)
        if ret != 0:
            return ret
        
        ret = run_stage_3(args, pdfs)
        if ret != 0:
            return ret
        
        ret = run_stage_4(args)
        if ret != 0:
            return ret
    
    print("\n" + "#"*60)
    print("# WORKFLOW COMPLETE")
    print("#"*60)
    
    print(f"\nOutputs:")
    print(f"  Conversations:     {args.conv_dir}")
    print(f"  Preliminary:       {args.preliminary_dir}")
    print(f"  Final structures:  {args.output_dir}")
    print(f"  Reports:           {args.reports_dir}")
    
    # Check for manual adjudication needed
    adj_report = args.reports_dir / "manual_adjudication_required.json"
    if adj_report.exists():
        print(f"\n⚠️  Manual adjudication may be required. See: {adj_report}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
