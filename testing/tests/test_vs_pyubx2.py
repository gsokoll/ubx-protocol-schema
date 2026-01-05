"""Cross-validation tests against pyubx2 library."""

import pytest
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.schema_loader import get_all_messages, get_message_by_name, parse_hex_id
from lib.ubx_generator import generate_ubx_message, generate_test_values
from lib.ubx_parser import parse_ubx_message
from external.pyubx2_adapter import (
    is_available as pyubx2_available,
    parse_ubx_bytes,
    generate_ubx_message as pyubx2_generate,
    get_supported_messages,
    get_message_definition,
)


# Skip all tests if pyubx2 not installed
pytestmark = pytest.mark.skipif(
    not pyubx2_available(),
    reason="pyubx2 not installed"
)


def get_common_messages():
    """Get messages that exist in both our schema and pyubx2."""
    if not pyubx2_available():
        return []
    
    our_messages = get_all_messages()
    pyubx2_messages = set(get_supported_messages())
    
    common = []
    for msg in our_messages:
        name = msg.get("name", "")
        # Try various name formats
        if name in pyubx2_messages:
            common.append(msg)
        elif name.replace("UBX-", "") in pyubx2_messages:
            common.append(msg)
    
    return common


class TestOurGeneratorPyubx2Parser:
    """Test: Our schema → Generate → pyubx2 parses."""
    
    def test_pyubx2_can_parse_our_ack_ack(self):
        """Test that pyubx2 can parse our ACK-ACK message."""
        msg = get_message_by_name("UBX-ACK-ACK")
        if msg is None:
            pytest.skip("UBX-ACK-ACK not in schema")
        
        # Generate with known values
        values = {"clsID": 0x06, "msgID": 0x01}
        data = generate_ubx_message(msg, values)
        
        # Parse with pyubx2
        result = parse_ubx_bytes(data)
        
        assert result is not None
        assert result.get("parsed"), f"pyubx2 failed to parse: {result.get('error')}"
        assert "ACK-ACK" in result.get("name", "")
    
    def test_pyubx2_can_parse_our_nav_pvt(self):
        """Test that pyubx2 can parse our NAV-PVT message."""
        msg = get_message_by_name("UBX-NAV-PVT")
        if msg is None:
            pytest.skip("UBX-NAV-PVT not in schema")
        
        # Generate with test values
        values = generate_test_values(msg)
        data = generate_ubx_message(msg, values)
        
        # Parse with pyubx2
        result = parse_ubx_bytes(data)
        
        assert result is not None
        assert result.get("parsed"), f"pyubx2 failed to parse: {result.get('error')}"
        assert "NAV-PVT" in result.get("name", "")
    
    @pytest.mark.parametrize("msg_name", [
        "UBX-NAV-POSLLH",
        "UBX-NAV-STATUS",
        "UBX-NAV-DOP",
        "UBX-NAV-CLOCK",
        "UBX-CFG-RATE",
        "UBX-MON-VER",
        "UBX-INF-DEBUG",
    ])
    def test_pyubx2_parses_common_messages(self, msg_name):
        """Test that pyubx2 can parse common messages from our schema."""
        msg = get_message_by_name(msg_name)
        if msg is None:
            pytest.skip(f"{msg_name} not in schema")
        
        values = generate_test_values(msg)
        data = generate_ubx_message(msg, values)
        
        result = parse_ubx_bytes(data)
        
        assert result is not None
        assert result.get("parsed"), f"pyubx2 failed to parse {msg_name}: {result.get('error')}"


class TestPyubx2GeneratorOurParser:
    """Test: pyubx2 generates → Our parser parses."""
    
    def test_our_parser_handles_pyubx2_ack_ack(self):
        """Test that our parser can parse pyubx2-generated ACK-ACK."""
        data = pyubx2_generate("ACK-ACK", {"clsID": 0x06, "msgID": 0x01})
        if data is None:
            pytest.skip("pyubx2 couldn't generate ACK-ACK")
        
        msg_def = get_message_by_name("UBX-ACK-ACK")
        result = parse_ubx_message(data, msg_def)
        
        assert result["parsed"]
        assert result["fields"].get("clsID") == 0x06
        assert result["fields"].get("msgID") == 0x01
    
    def test_our_parser_handles_pyubx2_nav_posllh(self):
        """Test that our parser can parse pyubx2-generated NAV-POSLLH."""
        values = {
            "iTOW": 123456789,
            "lon": 1234567,
            "lat": 7654321,
            "height": 100000,
            "hMSL": 99000,
            "hAcc": 5000,
            "vAcc": 8000,
        }
        data = pyubx2_generate("NAV-POSLLH", values)
        if data is None:
            pytest.skip("pyubx2 couldn't generate NAV-POSLLH")
        
        msg_def = get_message_by_name("UBX-NAV-POSLLH")
        result = parse_ubx_message(data, msg_def)
        
        assert result["parsed"]
        assert result["fields"].get("iTOW") == 123456789


class TestSchemaComparison:
    """Compare our schema definitions with pyubx2's."""
    
    def test_count_common_messages(self):
        """Count how many messages we share with pyubx2."""
        common = get_common_messages()
        our_total = len(get_all_messages())
        pyubx2_total = len(get_supported_messages())
        
        print(f"\nSchema overlap:")
        print(f"  Our messages: {our_total}")
        print(f"  pyubx2 messages: {pyubx2_total}")
        print(f"  Common: {len(common)}")
        print(f"  Coverage: {len(common)/our_total*100:.1f}%")
        
        # Should have significant overlap
        assert len(common) > 50, "Too few common messages"
    
    def test_nav_pvt_field_comparison(self):
        """Compare NAV-PVT fields between our schema and pyubx2."""
        our_msg = get_message_by_name("UBX-NAV-PVT")
        if our_msg is None:
            pytest.skip("UBX-NAV-PVT not in schema")
        
        pyubx2_def = get_message_definition("NAV-PVT")
        if pyubx2_def is None:
            pytest.skip("NAV-PVT not in pyubx2")
        
        our_fields = {f["name"] for f in our_msg.get("payload", {}).get("fields", [])}
        pyubx2_fields = set(pyubx2_def.get("fields", {}).keys())
        
        common = our_fields & pyubx2_fields
        our_only = our_fields - pyubx2_fields
        pyubx2_only = pyubx2_fields - our_fields
        
        print(f"\nNAV-PVT field comparison:")
        print(f"  Common: {len(common)}")
        print(f"  Our only: {our_only}")
        print(f"  pyubx2 only: {pyubx2_only}")
        
        # Most fields should match
        assert len(common) > len(our_only), "Too few matching fields"


class TestBulkValidation:
    """Bulk validation of all compatible messages."""
    
    def test_all_fixed_length_messages_parse_with_pyubx2(self):
        """Test all fixed-length messages can be parsed by pyubx2."""
        messages = get_all_messages()
        
        passed = 0
        failed = 0
        skipped = 0
        failures = []
        
        for msg in messages:
            name = msg.get("name", "UNKNOWN")
            payload = msg.get("payload", {})
            length = payload.get("length", {})
            
            # Skip variable length
            if not (isinstance(length, dict) and "fixed" in length):
                if not isinstance(length, int):
                    skipped += 1
                    continue
            
            try:
                values = generate_test_values(msg)
                data = generate_ubx_message(msg, values)
                result = parse_ubx_bytes(data)
                
                if result and result.get("parsed"):
                    passed += 1
                else:
                    failed += 1
                    failures.append((name, result.get("error", "unknown")))
            except Exception as e:
                failed += 1
                failures.append((name, str(e)))
        
        print(f"\nBulk validation results:")
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        print(f"  Skipped (variable length): {skipped}")
        
        if failures:
            print(f"\nFailures (first 10):")
            for name, error in failures[:10]:
                print(f"  {name}: {error}")
        
        # Allow some failures (pyubx2 may not support all messages)
        pass_rate = passed / (passed + failed) if (passed + failed) > 0 else 0
        assert pass_rate > 0.5, f"Pass rate too low: {pass_rate:.1%}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
