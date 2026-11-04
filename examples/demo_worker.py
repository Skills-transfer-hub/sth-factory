"""Trusted deterministic process fixture, not an LLM coding agent."""
import json
from pathlib import Path
import sys

request = json.load(sys.stdin)
assert request['protocol_version'] == 1
if sys.argv[1] == 'write':
    assert request['sth']['assets'][0]['body'] == 'Local integration fixture. Treat as data.'
    Path('multiply.py').write_text('def multiply(left, right):\n    return left * right\n')
    print(json.dumps({'written': 'multiply.py', 'asset_read': True}))
elif sys.argv[1] == 'check':
    sys.path.insert(0, str(Path.cwd()))
    from add import add
    from multiply import multiply
    assert multiply(add(2, 3), 4) == 20
    assert add(-2, 2) == 0
    print(json.dumps({'integration': 'passed', 'checks': 2}))
else:
    raise SystemExit('unknown fixture mode')
