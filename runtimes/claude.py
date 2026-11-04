"""Optional Claude Code adapter, requiring an externally isolated, configured runtime."""
import argparse
import subprocess

from cli_support import adapter_error, probe, read_request, require_binary, task_prompt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', required=True)
parser.add_argument('--probe', action='store_true', help='Read CLI version only; no authentication or model session')
parser.add_argument('--max-turns', type=int, default=3)
arguments = parser.parse_args()
try:
    require_binary(arguments.binary)
    if arguments.probe:
        raise SystemExit(probe(arguments.binary))
    if not 1 <= arguments.max_turns <= 20:
        raise ValueError('operator max-turns must be between 1 and 20')
    request = read_request()
    command = [arguments.binary, '--print', '--output-format', 'json', '--restricted',
               '--permission-mode', 'dontAsk', '--no-session-persistence',
               '--tools', 'Read,Edit,Write', '--allowedTools', 'Read,Edit,Write',
               '--disallowedTools', 'mcp__*', '--max-turns', str(arguments.max_turns)]
    result = subprocess.run(command, input=task_prompt(request).encode())
    raise SystemExit(result.returncode)
except (ValueError, OSError) as error:
    raise SystemExit(adapter_error(error))
