"""Forward a validated v1 request to a fixed operator-configured command, without a shell."""
import argparse
import json
import subprocess

from cli_support import adapter_error, read_request, require_binary

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('command', nargs=argparse.REMAINDER)
arguments = parser.parse_args()
try:
    command = arguments.command[1:] if arguments.command[:1] == ['--'] else arguments.command
    if not command:
        raise ValueError('fixed operator command is required after --')
    require_binary(command[0])
    request = read_request()
    result = subprocess.run(command, input=json.dumps(request, ensure_ascii=False, allow_nan=False).encode())
    raise SystemExit(result.returncode)
except (ValueError, OSError) as error:
    raise SystemExit(adapter_error(error))
