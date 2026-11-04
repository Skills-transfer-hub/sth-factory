"""Optional DeepSeek Harness headless adapter; Factory owns timeout and process supervision."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from cli_support import adapter_error, probe, read_request, require_binary, task_prompt

MAX_EVENT_BYTES = 1024 * 1024
GUARD_PATCH = '''- id: session-log-deepseek
  config:
    enabled: false
- id: session-telemetry-otel
  disabled: true
- id: plugin-package-inventory-deepseek
  config:
    enabled: false
- id: session-title-llm
  disabled: true
'''


def run(binary, node, config, request):
    workspace = Path.cwd().resolve()
    if os.path.lexists(workspace / '.env'):
        raise ValueError('DeepSeek loads workspace .env automatically; use a workspace without .env and an operator config')
    if config is not None:
        config = Path(require_binary(config)).resolve(strict=True)
        if not config.is_file() or config.is_relative_to(workspace):
            raise ValueError('DeepSeek config must be an operator-owned file outside the workspace')
    with tempfile.TemporaryDirectory(prefix='sth-dsh-') as temporary:
        home = Path(temporary).resolve()
        if home.is_relative_to(workspace):
            raise ValueError('DeepSeek temporary home must be outside the workspace')
        guard = home / 'factory.patch.yml'
        guard.write_text(GUARD_PATCH, encoding='utf-8')
        command = ([node, binary] if node else [binary]) + ['--profile', 'headless']
        if config is not None:
            command += ['--patch', str(config)]
        command += ['--patch', str(guard), '--permission-mode', 'workspace-write',
                    '--approval-policy', 'never', '--json', '-']
        environment = {**os.environ, 'DSH_HOME': str(home), 'DSH_TELEMETRY_DISABLED': '1'}
        # A file avoids deadlock when a large prompt meets a process writing startup events.
        with tempfile.TemporaryFile() as prompt:
            prompt.write(task_prompt(request).encode('utf-8'))
            prompt.seek(0)
            process = subprocess.Popen(command, stdin=prompt, stdout=subprocess.PIPE, env=environment)
            try:
                final = None
                while line := process.stdout.readline(MAX_EVENT_BYTES + 1):
                    if len(line) > MAX_EVENT_BYTES:
                        raise ValueError('DeepSeek event exceeds 1 MiB')
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
                    try:
                        event = json.loads(line)
                    except (ValueError, RecursionError) as error:
                        raise ValueError('DeepSeek emitted invalid NDJSON') from error
                    if not isinstance(event, dict) or final is not None:
                        raise ValueError('DeepSeek event is invalid or follows the terminal event')
                    if event.get('type') == 'final':
                        final = event
                returncode = process.wait()
                if returncode:
                    return returncode if returncode > 0 else 1
                if final is None or not isinstance(final.get('reason'), dict) or final['reason'].get('kind') != 'completed':
                    raise ValueError('DeepSeek did not report a completed terminal event')
                return 0
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True)
    parser.add_argument('--node', help='Absolute Node executable for an npm DSH JavaScript entrypoint')
    parser.add_argument('--probe', action='store_true', help='Read CLI version only; no model session')
    parser.add_argument('--config', help='Absolute operator-owned DSH patch outside the workspace; may contain provider settings')
    arguments = parser.parse_args()
    try:
        require_binary(arguments.binary)
        if arguments.node is not None:
            require_binary(arguments.node)
        if arguments.probe:
            return probe(arguments.binary, arguments.node)
        return run(arguments.binary, arguments.node, arguments.config, read_request())
    except (ValueError, OSError) as error:
        return adapter_error(error)


if __name__ == '__main__':
    raise SystemExit(main())
