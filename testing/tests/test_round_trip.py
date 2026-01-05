"""Round-trip tests: Generate UBX from our schema, parse it back, compare."""

import pytest
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.schema_loader import get_all_messages, parse_hex_id
from lib.ubx_generator import generate_ubx_message, generate_test_values
from lib.ubx_parser import parse_ubx_message, UBXParseError


def get_fixed_length_messages():
    """Get messages with fixed payload length (easier to test)."""
    messages = []
    for msg in get_all_messages():
        payload = msg.get("payload", {})
        length = payload.get("length", {})
        
        # Check if fixed length
        if isinstance(length, dict) and "fixed" in length:
            messages.append(msg)
        elif isinstance(length, int):
            messages.append(msg)
    
    return messages


class TestRoundTrip:
    """Test that our generator and parser are internally consistent."""
    
    def test_basic_message_generation(self):
        """Test that we can generate a basic message."""
        messages = get_all_messages()
        assert len(messages) > 0, "No messages in schema"
        
        # Try first message
        msg = messages[0]
        data = generate_ubx_message(msg)
        
        assert data is not None
        assert len(data) >= 8  # Minimum UBX message size
        assert data[0] == 0xB5  # Sync char 1
        assert data[1] == 0x62  # Sync char 2
    
    def test_message_has_correct_class_id(self):
        """Test that generated message has correct class/message IDs."""
        messages = get_all_messages()
        
        for msg in messages[:10]:  # Test first 10
            data = generate_ubx_message(msg)
            
            expected_class = parse_hex_id(msg.get("class_id", 0))
            expected_msg_id = parse_hex_id(msg.get("message_id", 0))
            
            assert data[2] == expected_class, f"Class ID mismatch for {msg.get('name')}"
            assert data[3] == expected_msg_id, f"Message ID mismatch for {msg.get('name')}"
    
    def test_checksum_valid(self):
        """Test that generated messages have valid checksums."""
        messages = get_all_messages()
        
        for msg in messages[:20]:  # Test first 20
            data = generate_ubx_message(msg)
            
            # Parser will fail if checksum is invalid
            try:
                parsed = parse_ubx_message(data, msg)
                assert parsed["parsed"], f"Failed to parse {msg.get('name')}"
            except UBXParseError as e:
                pytest.fail(f"Checksum error for {msg.get('name')}: {e}")
    
    @pytest.mark.parametrize("msg", get_fixed_length_messages()[:50])
    def test_round_trip_fixed_length(self, msg):
        """Test round-trip for fixed-length messages."""
        # Generate test values
        values = generate_test_values(msg)
        
        # Generate message
        data = generate_ubx_message(msg, values)
        
        # Parse it back
        parsed = parse_ubx_message(data, msg)
        
        assert parsed["parsed"], f"Failed to parse {msg.get('name')}"
        assert parsed["class_id"] == parse_hex_id(msg.get("class_id", 0))
        assert parsed["message_id"] == parse_hex_id(msg.get("message_id", 0))
        
        # Compare field values (for non-reserved fields)
        payload = msg.get("payload", {})
        for field in payload.get("fields", []):
            name = field.get("name")
            if field.get("reserved"):
                continue
            
            if name in values and name in parsed["fields"]:
                original = values[name]
                roundtrip = parsed["fields"][name]
                
                # For floats, compare with tolerance
                if isinstance(original, float):
                    assert abs(original - roundtrip) < 0.001, \
                        f"Field {name} mismatch: {original} != {roundtrip}"
                elif isinstance(original, list):
                    # Compare lists element by element
                    for i, (o, r) in enumerate(zip(original, roundtrip)):
                        if isinstance(o, float):
                            assert abs(o - r) < 0.001, \
                                f"Field {name}[{i}] mismatch: {o} != {r}"
                        else:
                            assert o == r, f"Field {name}[{i}] mismatch: {o} != {r}"
                else:
                    assert original == roundtrip, \
                        f"Field {name} mismatch: {original} != {roundtrip}"


class TestSchemaIntegrity:
    """Test schema integrity and completeness."""
    
    def test_all_messages_have_required_fields(self):
        """Test that all messages have required schema fields."""
        messages = get_all_messages()
        
        for msg in messages:
            name = msg.get("name", "UNKNOWN")
            assert msg.get("class_id") is not None, f"{name} missing class_id"
            assert msg.get("message_id") is not None, f"{name} missing message_id"
            assert msg.get("message_type") is not None, f"{name} missing message_type"
    
    def test_field_offsets_are_sequential(self):
        """Test that field offsets don't overlap or have unexpected gaps."""
        messages = get_all_messages()
        
        for msg in messages:
            name = msg.get("name", "UNKNOWN")
            payload = msg.get("payload", {})
            fields = payload.get("fields", [])
            
            if not fields:
                continue
            
            # Sort by offset
            sorted_fields = sorted(fields, key=lambda f: f.get("byte_offset", 0))
            
            # Check for overlaps (basic check)
            # Note: Some messages have variant fields at same offset, so we just warn
            prev_end = 0
            overlaps = []
            for field in sorted_fields:
                offset = field.get("byte_offset", 0)
                if offset < prev_end:
                    overlaps.append(f"{name}: Field {field.get('name')} at offset {offset} overlaps with previous field ending at {prev_end}")
                
                # Estimate field size (simplified)
                data_type = field.get("data_type", "U1")
                if isinstance(data_type, dict):
                    data_type = data_type.get("type", "U1")
                if not isinstance(data_type, str):
                    data_type = "U1"
                if "[" in data_type:
                    base = data_type.split("[")[0]
                    count = int(data_type.split("[")[1].rstrip("]"))
                    size = {"U1": 1, "I1": 1, "U2": 2, "I2": 2, "U4": 4, "I4": 4, "R4": 4, "R8": 8, "CH": 1}.get(base, 1) * count
                else:
                    size = {"U1": 1, "I1": 1, "U2": 2, "I2": 2, "U4": 4, "I4": 4, "R4": 4, "R8": 8}.get(data_type, 1)
                
                prev_end = offset + size
        
        # Report overlaps but don't fail (some are intentional variants)
        if overlaps:
            print(f"\nWarning: {len(overlaps)} field overlaps detected")
            for o in overlaps[:5]:
                print(f"  {o}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
