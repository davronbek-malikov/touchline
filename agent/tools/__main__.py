"""Call a tool by hand: python -m agent.tools search_players '{"position_groups": ["CB"], "limit": 3}'"""
import json
import sys

from agent.tools import REGISTRY, run_tool

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in REGISTRY:
        sys.exit(f"usage: python -m agent.tools <{'|'.join(REGISTRY)}> '<json args>'")
    out, is_error = run_tool(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
    print(json.dumps(json.loads(out), indent=2, ensure_ascii=False))
    sys.exit(1 if is_error else 0)
