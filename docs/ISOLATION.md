# Optional container execution boundary

The operator chooses an execution backend in the trusted policy:

```json
{
  "isolation": {
    "backend": "container",
    "image": "python@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8",
    "memory_mb": 512,
    "cpus": 1,
    "pids_limit": 128,
    "tmp_mb": 64,
    "network": "none"
  }
}
```

`{"backend":"local"}` is the compatibility backend for trusted local commands. It has no operating-system isolation and reports `security_sandbox: false`. Worktrees alone are not sandboxes.

Container images must be immutable `repository@sha256:digest` references or exact `sha256:image-id` values already present in the local Docker daemon. The factory does not build or pull images automatically, silently change backends, use a remote Docker endpoint, create credentials, or enable networking. An unavailable CLI, daemon or configured image fails closed before runtime execution. Image review and installation belong to the operator. Commands refer to executable paths **inside the image**, for example `/usr/local/bin/python3`, rather than host interpreter paths.

## Enforced task boundary

The backend copies the task worktree to a separate snapshot, excluding `.git` entries at every level. Only this snapshot is mounted into the container at `/workspace`; the source repository, shared mirror, factory logs, policy, Docker socket and user HOME are not mounted. Successful files, deletions and symlinks are copied back without following symlinks; the factory worktree's original `.git` pointer remains untouched. A runtime-created `.git` entry is never imported. Special files are refused. The snapshot and failed task output remain available to the operator for diagnosis.

The container runs under a numeric nonroot UID/GID, normally the task user's values, with a read-only root filesystem, no extra capabilities, `no-new-privileges`, a private network namespace with no external network, Docker CPU/memory/PID limits and a bounded `/tmp` tmpfs. Only explicit fixed environment values are supplied to the task. Proxy values automatically supplied by Docker configuration are explicitly cleared inside the container. Docker client registry/proxy setup remains unchanged on the trusted host side.

The local Docker daemon may itself run as root. `probe()` reports `daemon_rootless`; the verified environment had a rootful managed Docker daemon, so this is **not a claim of a rootless daemon or a virtual-machine boundary**. Containers share the host kernel. Keep the daemon socket accessible only to the trusted supervisor. An image may contain its own files or secrets: digest pinning identifies bytes but does not audit them.

The mounted snapshot is host disk storage and currently has **no hard disk quota**. CPU, memory, PID and tmpfs limits do not limit total snapshot output. The factory's stdout/stderr threshold remains a polling threshold rather than a disk quota. A system quota or another backend is needed for hard disk limits. The total concurrent resource budget is also the operator's responsibility.

Because networking is disabled, an agent in this backend cannot contact a remote model API. No unrestricted network switch or credential passthrough is offered. A separately reviewed broker/network policy or an image containing a local model is needed before remote agents can use this backend. The current tests validate actual container behavior with deterministic processes, not model inference.

## Supervisor integration contract

`prepare_execution(spec, argv, worktree, task_folder, env)` returns an `Execution` object with `argv`, `cwd`, `env`, `security_sandbox`, `container_name`, `collect()` and `cleanup()`.

The supervisor records the container identity before starting the process, launches the returned argv using the returned cwd and env, calls `collect()` only after success, and always calls `cleanup()` in a `finally` block. Docker runs with `--interactive` and no TTY so the runtime's JSON stdin reaches the worker unchanged. The returned environment is for the trusted Docker client; the container receives only its explicit task environment. Container cleanup is necessary even if the Docker client is killed, because killing a client does not stop its daemon-owned container. A cleanup failure must remain visible, not be converted to a successful task.

Every container name has a random `sth-factory-<32hex>` identifier and a matching label. For recovery after a supervisor crash, `cleanup_container(spec, container_name)` validates that exact name, inspects the ownership label and configured image, and removes only the matching container. It returns `False` when already absent and raises `IsolationError` on an inspection, identity or removal failure. It does not enumerate or prune unrelated containers. The runtime cannot access its control file because it is outside the mounted snapshot. After recovery, interrupted task execution still requires the explicit retry policy of the durable runner.

## Tests actually executed

Tests were written first and initially failed because `isolation.py` did not exist. Unit coverage checks fixed images, refused privilege/network/mount weakening, snapshot-only mounts, hidden Git metadata, no symlink following during collection, unavailable-backend refusal and exact cleanup identity.

The actual managed Docker daemon was inspected through `/var/run/docker.sock` using the environment's supported configuration. `python:3.12-alpine` was pulled from the approved Docker registry without changing proxy or network policy; the resulting immutable digest is shown above. Three real container tests then verified:

- nonroot execution, read-only rootfs, missing host marker and `.git`, loopback-only network, PID limit 128, memory limit 536870912 bytes, no inherited proxy values, successful file collection and preservation of the worktree Git pointer;
- the runtime starts, its Docker client is killed, recovery cleanup stops/removes the still-running exact container, and subsequent inspection reports it absent;
- a runtime JSON request is read from stdin without a TTY, echoed in stdout, and collected as a file with identical fields.

Reproduce after making that image available locally:

```sh
STH_TEST_CONTAINER_IMAGE=python@sha256:e6dae589c1c05976188fd3bd019afd091445fc533ed2ea29001beddc7368a9c8 \
  python3 -m unittest discover -s tests -p test_isolation.py -v
```

Without `STH_TEST_CONTAINER_IMAGE`, these three environment-dependent tests are explicitly skipped. This document describes the backend; the root runner's integration tests separately establish its use by complete factory runs.
