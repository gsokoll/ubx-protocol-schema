#!/usr/bin/env python3
"""Generate a coverage report showing which messages have been tested."""

import json
import sys
from pathlib import Path
from datetime import datetime

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.schema_loader import get_all_messages, parse_hex_id
from lib.ubx_generator import generate_ubx_message, generate_test_values
from lib.ubx_parser import parse_ubx_message, UBXParseError

try:
    from external.pyubx2_adapter import (
        is_available as pyubx2_available,
        parse_ubx_bytes,
        get_supported_messages,
    )
except ImportError:
    pyubx2_available = lambda: False
    parse_ubx_bytes = None
    get_supported_messages = lambda: []

try:
    from external.ublox_rs_adapter import (
        get_ublox_rs_messages,
        is_in_ublox_rs,
        is_validator_available as ublox_rs_validator_available,
        parse_ubx_bytes_with_ublox_rs,
    )
    UBLOX_RS_AVAILABLE = True
except ImportError:
    UBLOX_RS_AVAILABLE = False
    get_ublox_rs_messages = lambda: set()
    is_in_ublox_rs = lambda x: False
    ublox_rs_validator_available = lambda: False
    parse_ubx_bytes_with_ublox_rs = None


def run_coverage_analysis():
    """Run coverage analysis and generate report."""
    messages = get_all_messages()
    pyubx2_msgs = set(get_supported_messages()) if pyubx2_available() else set()
    ublox_rs_msgs = get_ublox_rs_messages() if UBLOX_RS_AVAILABLE else set()
    
    results = {
        "generated": datetime.now().isoformat(),
        "total_messages": len(messages),
        "pyubx2_available": pyubx2_available(),
        "pyubx2_messages": len(pyubx2_msgs),
        "ublox_rs_available": UBLOX_RS_AVAILABLE,
        "ublox_rs_messages": len(ublox_rs_msgs),
        "tests": [],
        "summary": {
            "round_trip_pass": 0,
            "round_trip_fail": 0,
            "pyubx2_pass": 0,
            "pyubx2_fail": 0,
            "pyubx2_not_supported": 0,
            "ublox_rs_covered": 0,
            "ublox_rs_not_covered": 0,
            "ublox_rs_pass": 0,
            "ublox_rs_fail": 0,
            "ublox_rs_not_tested": 0,
        }
    }
    
    # Check if ublox-rs validator is available
    ublox_rs_can_test = UBLOX_RS_AVAILABLE and ublox_rs_validator_available()
    results["ublox_rs_validator_available"] = ublox_rs_can_test
    
    for msg in messages:
        name = msg.get("name", "UNKNOWN")
        msg_result = {
            "name": name,
            "class_id": msg.get("class_id"),
            "message_id": msg.get("message_id"),
            "round_trip": None,
            "pyubx2": None,
            "in_pyubx2": name in pyubx2_msgs or name.replace("UBX-", "") in pyubx2_msgs,
            "in_ublox_rs": is_in_ublox_rs(name),
            "ublox_rs": None,
        }
        
        # Track ublox-rs coverage
        if msg_result["in_ublox_rs"]:
            results["summary"]["ublox_rs_covered"] += 1
        else:
            results["summary"]["ublox_rs_not_covered"] += 1
        
        # Test round-trip
        try:
            values = generate_test_values(msg)
            data = generate_ubx_message(msg, values)
            parsed = parse_ubx_message(data, msg)
            
            if parsed["parsed"]:
                msg_result["round_trip"] = "pass"
                results["summary"]["round_trip_pass"] += 1
            else:
                msg_result["round_trip"] = "fail"
                results["summary"]["round_trip_fail"] += 1
        except Exception as e:
            msg_result["round_trip"] = f"error: {str(e)[:50]}"
            results["summary"]["round_trip_fail"] += 1
        
        # Test with pyubx2
        if pyubx2_available() and parse_ubx_bytes:
            try:
                if msg_result.get("in_pyubx2"):
                    values = generate_test_values(msg)
                    data = generate_ubx_message(msg, values)
                    msg_type = msg.get("message_type", "output")
                    result = parse_ubx_bytes(data, msg_type)
                    
                    if result and result.get("parsed"):
                        msg_result["pyubx2"] = "pass"
                        results["summary"]["pyubx2_pass"] += 1
                    else:
                        msg_result["pyubx2"] = f"fail: {result.get('error', 'unknown')[:50]}"
                        results["summary"]["pyubx2_fail"] += 1
                else:
                    msg_result["pyubx2"] = "not_supported"
                    results["summary"]["pyubx2_not_supported"] += 1
            except Exception as e:
                msg_result["pyubx2"] = f"error: {str(e)[:50]}"
                results["summary"]["pyubx2_fail"] += 1
        
        # Test with ublox-rs validator
        if ublox_rs_can_test and parse_ubx_bytes_with_ublox_rs:
            try:
                if msg_result.get("in_ublox_rs"):
                    values = generate_test_values(msg)
                    data = generate_ubx_message(msg, values)
                    result = parse_ubx_bytes_with_ublox_rs(data)
                    
                    if result and result.get("parsed"):
                        msg_result["ublox_rs"] = "pass"
                        results["summary"]["ublox_rs_pass"] += 1
                    else:
                        msg_result["ublox_rs"] = f"fail: {result.get('error', 'unknown')[:50]}"
                        results["summary"]["ublox_rs_fail"] += 1
                else:
                    msg_result["ublox_rs"] = "not_supported"
                    results["summary"]["ublox_rs_not_tested"] += 1
            except Exception as e:
                msg_result["ublox_rs"] = f"error: {str(e)[:50]}"
                results["summary"]["ublox_rs_fail"] += 1
        
        results["tests"].append(msg_result)
    
    return results


def print_summary(results: dict):
    """Print a summary of the coverage report."""
    print("\n" + "=" * 60)
    print("UBX SCHEMA COVERAGE REPORT")
    print("=" * 60)
    
    summary = results["summary"]
    total = results["total_messages"]
    
    print(f"\nTotal messages in schema: {total}")
    print(f"pyubx2 available: {results['pyubx2_available']}")
    if results["pyubx2_available"]:
        print(f"pyubx2 messages: {results['pyubx2_messages']}")
    
    print("\n--- Round-Trip Tests (Our Generator → Our Parser) ---")
    rt_pass = summary["round_trip_pass"]
    rt_fail = summary["round_trip_fail"]
    print(f"  Pass: {rt_pass} ({rt_pass/total*100:.1f}%)")
    print(f"  Fail: {rt_fail} ({rt_fail/total*100:.1f}%)")
    
    if results["pyubx2_available"]:
        print("\n--- Cross-Validation (Our Generator → pyubx2 Parser) ---")
        py_pass = summary["pyubx2_pass"]
        py_fail = summary["pyubx2_fail"]
        py_skip = summary["pyubx2_not_supported"]
        tested = py_pass + py_fail
        print(f"  Pass: {py_pass} ({py_pass/tested*100:.1f}% of tested)" if tested else "  Pass: 0")
        print(f"  Fail: {py_fail}")
        print(f"  Not in pyubx2: {py_skip}")
    
    if results.get("ublox_rs_available"):
        print("\n--- ublox-rs Coverage Comparison ---")
        rs_covered = summary["ublox_rs_covered"]
        rs_not_covered = summary["ublox_rs_not_covered"]
        rs_total = results["ublox_rs_messages"]
        print(f"  ublox-rs total messages: {rs_total}")
        print(f"  Our messages also in ublox-rs: {rs_covered} ({rs_covered/total*100:.1f}%)")
        print(f"  Our messages NOT in ublox-rs: {rs_not_covered} (we have more coverage)")
        
        if results.get("ublox_rs_validator_available"):
            print("\n--- Cross-Validation (Our Generator → ublox-rs Parser) ---")
            rs_pass = summary["ublox_rs_pass"]
            rs_fail = summary["ublox_rs_fail"]
            rs_skip = summary["ublox_rs_not_tested"]
            tested = rs_pass + rs_fail
            print(f"  Pass: {rs_pass} ({rs_pass/tested*100:.1f}% of tested)" if tested else "  Pass: 0")
            print(f"  Fail: {rs_fail}")
            print(f"  Not in ublox-rs: {rs_skip}")
    
    # Show failures
    failures = [t for t in results["tests"] if t["round_trip"] and "fail" in str(t["round_trip"]).lower()]
    if failures:
        print(f"\n--- Round-Trip Failures (first 10) ---")
        for f in failures[:10]:
            print(f"  {f['name']}: {f['round_trip']}")
    
    print("\n" + "=" * 60)


def main():
    """Main entry point."""
    print("Running coverage analysis...")
    results = run_coverage_analysis()
    
    # Print summary
    print_summary(results)
    
    # Save report
    reports_dir = Path(__file__).parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    
    report_file = reports_dir / "coverage_report.json"
    with open(report_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nFull report saved to: {report_file}")


if __name__ == "__main__":
    main()
