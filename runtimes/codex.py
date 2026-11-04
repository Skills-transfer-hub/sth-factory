"""Optional Codex CLI adapter. Requires an operator-reviewed externally isolated runtime."""
import argparse
import subprocess
from cli_support import adapter_error, probe, read_request, require_binary, task_prompt

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', required=True)
parser.add_argument('--probe', action='store_true', help='Read CLI version only; never start a model session')
arguments = parser.parse_args()
try:
    require_binary(arguments.binary)
    if arguments.probe:
        raise SystemExit(probe(arguments.binary))
    request = read_request()
    result = subprocess.run([arguments.binary, '-a', 'never', 'exec', '--ignore-user-config', '--ephemeral',
                             '--sandbox', 'workspace-write', '--json', '-'], input=task_prompt(request).encode())
    raise SystemExit(result.returncode)
except (ValueError, OSError) as error:
    raise SystemExit(adapter_error(error))
