#!/usr/bin/env python3
"""Adjudicate config key conflicts using Gemini LLM.

Resolves conflicts in the adjudication_queue.json by asking Gemini to determine
the correct value based on context and known patterns.

Usage:
    export GOOGLE_API_KEY="your-key"
    uv run python scripts/adjudicate_config_keys.py
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path


GEMINI_MODELS = {
    "flash-lite": "gemini-2.5-flash-lite",
    "flash": "gemini-2.5-flash",
    "pro": "gemini-2.5-pro",
}

PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
}


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    
    def add(self, input_t: int, output_t: int):
        self.input_tokens += input_t
        self.output_tokens += output_t
    
    def cost(self, model: str) -> float:
        pricing = PRICING.get(model, {"input": 0, "output": 0})
        return (self.input_tokens * pricing["input"] + self.output_tokens * pricing["output"]) / 1_000_000


def build_adjudication_prompt(items: list[dict]) -> str:
    """Build prompt for adjudicating a batch of config key conflicts."""
    
    items_text = ""
    for i, item in enumerate(items, 1):
        items_text += f"\n### Conflict {i}: {item['key_name']} ({item['key_id']})\n"
        items_text += f"**Field:** {item['field']}\n"
        items_text += f"**Candidates:**\n"
        for c in item['candidates']:
            sources_str = ", ".join(c['sources'][:3])
            if len(c['sources']) > 3:
                sources_str += f" +{len(c['sources'])-3} more"
            items_text += f"  - `{c['value']}` (from {sources_str}, count={c['count']})\n"
        items_text += f"**Auto-suggested:** `{item['suggested']}` (confidence: {item['confidence']:.1%})\n"
    
    return f'''You are adjudicating conflicts in u-blox UBX configuration key extractions.

These conflicts occur when different PDF manuals report different values for the same configuration key field.

=== CONFLICT ITEMS ==={items_text}

=== KNOWN PATTERNS ===

1. **NAV vs NAV2 confusion**: Gemini sometimes confuses adjacent NAV and NAV2 message output keys.
   - Check key_id: NAV keys have different key_id ranges than NAV2 keys
   - NAV2 keys are newer (protocol 27.30+) and have different key_id patterns

2. **Unit inconsistencies**: 
   - Empty/space units `" "` are often extraction errors - prefer descriptive units
   - "PIO number" is more descriptive than blank for pin configuration keys
   - "7 bits" is valid for I2C address keys

3. **Scale format variations**:
   - "1e-7" vs "0.0000001" - these are equivalent, prefer scientific notation
   - Missing scale vs explicit scale - prefer explicit if available

4. **OCR errors**:
   - "I" (letter) vs "1" (digit) in data types: I1, I2, I4 are signed integers
   - "O" (letter) vs "0" (digit) in names: CFG-ODO uses letter O

=== RESPONSE FORMAT ===

Return a JSON object with decisions for each conflict:
{{
  "decisions": [
    {{
      "key_id": "0x...",
      "field": "unit|scale|name|...",
      "decision": "the correct value",
      "reasoning": "brief explanation"
    }}
  ]
}}

Choose the MOST CORRECT value based on:
1. Technical accuracy (what makes sense for this config key?)
2. Majority vote (if values are equivalent, prefer majority)
3. Known patterns (NAV vs NAV2, OCR errors, etc.)
4. Descriptiveness (prefer informative values over empty/generic ones)
'''


def run_adjudication(
    queue_file: Path,
    output_file: Path,
    model: str = "gemini-2.5-flash-lite",
    batch_size: int = 10,
    dry_run: bool = False,
) -> int:
    """Run LLM adjudication on config key conflicts."""
    from google import genai
    
    if not os.environ.get("GOOGLE_API_KEY"):
        print("Error: GOOGLE_API_KEY not set")
        return 1
    
    # Load adjudication queue
    queue_data = json.loads(queue_file.read_text())
    items = queue_data.get("items", [])
    
    # Filter to items without decisions
    pending = [item for item in items if item.get("decision") is None]
    print(f"Total items: {len(items)}, pending: {len(pending)}")
    
    if not pending:
        print("No pending items to adjudicate!")
        return 0
    
    if dry_run:
        print(f"\nDry run - would process {len(pending)} items in {(len(pending) + batch_size - 1) // batch_size} batches")
        return 0
    
    client = genai.Client()
    total_usage = TokenUsage()
    decisions_made = 0
    
    # Process in batches
    batches = [pending[i:i+batch_size] for i in range(0, len(pending), batch_size)]
    print(f"Processing {len(batches)} batches...")
    
    for batch_num, batch in enumerate(batches, 1):
        print(f"\n  Batch {batch_num}/{len(batches)}: {len(batch)} items")
        
        prompt = build_adjudication_prompt(batch)
        
        try:
            start_time = time.time()
            response = client.models.generate_content(
                model=model,
                contents=[prompt],
                config={"response_mime_type": "application/json", "max_output_tokens": 8192},
            )
            elapsed = time.time() - start_time
            
            usage_in = response.usage_metadata.prompt_token_count
            usage_out = response.usage_metadata.candidates_token_count
            total_usage.add(usage_in, usage_out)
            
            result = json.loads(response.text)
            decisions = result.get("decisions", [])
            
            print(f"    Response: {len(decisions)} decisions in {elapsed:.1f}s")
            
            # Apply decisions to original items
            decision_map = {d["key_id"]: d for d in decisions}
            for item in batch:
                key_id = item["key_id"]
                if key_id in decision_map:
                    d = decision_map[key_id]
                    item["decision"] = d.get("decision")
                    item["llm_reasoning"] = d.get("reasoning", "")
                    decisions_made += 1
                    print(f"      {item['key_name']}.{item['field']}: {d.get('decision')}")
            
        except Exception as e:
            print(f"    ERROR: {e}")
            continue
        
        # Rate limiting
        if batch_num < len(batches):
            time.sleep(1)
    
    # Save updated queue
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(queue_data, indent=2))
    
    print(f"\n=== Summary ===")
    print(f"  Decisions made: {decisions_made}")
    print(f"  Tokens: {total_usage.input_tokens:,} in / {total_usage.output_tokens:,} out")
    print(f"  Cost: ${total_usage.cost(model):.4f}")
    print(f"  Output: {output_file}")
    
    return 0


def main():
    parser = argparse.ArgumentParser(description="Adjudicate config key conflicts using LLM")
    parser.add_argument("--queue", type=Path, default=Path("data/config_keys/adjudication_queue.json"),
                        help="Adjudication queue file")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output file (default: same as queue)")
    parser.add_argument("--model", choices=GEMINI_MODELS.keys(), default="flash-lite",
                        help="Gemini model to use")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Items per API call")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without making API calls")
    
    args = parser.parse_args()
    
    output = args.output or args.queue
    model = GEMINI_MODELS[args.model]
    
    print(f"Model: {model}")
    print(f"Queue: {args.queue}")
    print(f"Output: {output}")
    
    return run_adjudication(
        queue_file=args.queue,
        output_file=output,
        model=model,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
