"""Sandbox: path safety (without Docker) and isolation properties (with Docker).

The Docker tests skip themselves when no daemon is reachable. In CI the fast part always
runs, the container part wherever Docker is available.
"""

from __future__ import annotations

import pytest

from hive.sandbox.docker_sandbox import WORKSPACE, DockerSandbox, SandboxError, SandboxLimits


def docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
    except Exception:
        return False
    return True


requires_docker = pytest.mark.skipif(not docker_available(), reason="Docker unreachable")


# ---------------------------------------------------------------------- paths


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("index.html", f"{WORKSPACE}/index.html"),
        ("./src/main.js", f"{WORKSPACE}/src/main.js"),
        ("/workspace/app.py", f"{WORKSPACE}/app.py"),
        ("workspace/app.py", f"{WORKSPACE}/workspace/app.py"),
        ("src\\win.js", f"{WORKSPACE}/src/win.js"),
        ("a/b/../c.txt", f"{WORKSPACE}/a/c.txt"),
        (".", WORKSPACE),
    ],
)
def test_paths_are_normalised_into_the_workspace(given: str, expected: str) -> None:
    assert DockerSandbox._absolute(given) == expected


@pytest.mark.parametrize("given", ["../etc/passwd", "a/../../b", "/../root"])
def test_escaping_the_workspace_is_refused(given: str) -> None:
    with pytest.raises(SandboxError, match="outside the workspace"):
        DockerSandbox._absolute(given)


def test_windows_host_paths_do_not_leak_in() -> None:
    """Path.resolve() would resolve against the host filesystem on Windows.

    The escape guard would then be worthless — which is why the sandbox uses PurePosixPath
    with its own normalisation.
    """
    assert DockerSandbox._absolute("sub/dir/file.txt").startswith(f"{WORKSPACE}/")
    assert "\\" not in DockerSandbox._absolute("sub\\dir\\file.txt")
    assert ":" not in DockerSandbox._absolute("sub/dir/file.txt")


# --------------------------------------------------------------------- Docker


@requires_docker
async def test_container_runs_without_root_and_without_network() -> None:
    """The isolation promises are verified, not asserted in prose."""
    async with await DockerSandbox.create(SandboxLimits(network="none")) as sandbox:
        whoami = await sandbox.exec("whoami")
        assert whoami.stdout.strip() == "node"

        uid = await sandbox.exec("id -u")
        assert uid.stdout.strip() != "0"

        # Without a network only the loopback interface exists.
        routes = await sandbox.exec("cat /proc/net/route | tail -n +2 | wc -l")
        assert routes.stdout.strip() == "0"


@requires_docker
async def test_new_privileges_are_blocked() -> None:
    async with await DockerSandbox.create() as sandbox:
        # no-new-privileges + cap_drop ALL: privilege escalation must fail.
        result = await sandbox.exec("su root -c 'echo escalated' 2>&1 || echo BLOCKED")
        assert "escalated" not in result.stdout


@requires_docker
async def test_write_read_roundtrip_and_nested_directories() -> None:
    async with await DockerSandbox.create() as sandbox:
        await sandbox.write_file("src/deep/app.js", "console.log('hi');\n")
        assert await sandbox.read_file("src/deep/app.js") == "console.log('hi');\n"

        listing = await sandbox.exec("find . -type f | sort")
        assert "./src/deep/app.js" in listing.stdout


@requires_docker
async def test_missing_file_reports_cleanly() -> None:
    async with await DockerSandbox.create() as sandbox:
        with pytest.raises(SandboxError, match=r"not found|not readable"):
            await sandbox.read_file("nonexistent.txt")


@requires_docker
async def test_command_timeout_actually_kills_the_process() -> None:
    """A time limit on the Python side would leave the process running."""
    async with await DockerSandbox.create() as sandbox:
        result = await sandbox.exec("sleep 30", timeout=2)
        assert result.timed_out is True
        assert result.exit_code == 124


@requires_docker
async def test_output_is_capped() -> None:
    """A build log must not flow unchecked into the context window."""
    limits = SandboxLimits(max_output_bytes=1_000)
    async with await DockerSandbox.create(limits) as sandbox:
        result = await sandbox.exec("head -c 100000 /dev/zero | tr '\\0' 'x'")
        assert len(result.stdout) <= 1_100
        assert "omitted" in result.stdout


@requires_docker
async def test_exit_code_and_stderr_survive() -> None:
    async with await DockerSandbox.create() as sandbox:
        result = await sandbox.exec("echo failure >&2; exit 3")
        assert result.exit_code == 3
        assert result.ok is False
        assert "failure" in result.stderr
        assert "exit=3" in result.combined()
