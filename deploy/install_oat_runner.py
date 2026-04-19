"""Install a GitHub Actions self-hosted runner on the OAT droplet.

The runner lets nightly CI deploy to OAT without punching SSH holes in the
droplet's firewall: the runner maintains an outbound HTTPS connection to
github.com and pulls jobs when they're available.

It runs as root under systemd so the existing SSH-based deploy pipeline
(`invoke deploy-oat`) works unchanged — the runner just SSHes to
root@127.0.0.1, which loops back on the same box.

Usage:
    uv run python -m deploy.install_oat_runner --host <ip> --token <token> \
        --repo jdrumgoole/winebox

Get --token from GitHub: Repo -> Settings -> Actions -> Runners ->
    New self-hosted runner (Linux/x64). The token expires in ~1 hour.
"""

import argparse
import sys

from deploy.common import run_ssh


RUNNER_VERSION = "2.323.0"
RUNNER_DIR = "/opt/github-runner"
RUNNER_LABELS = "self-hosted,Linux,X64,oat"


def install(host: str, token: str, repo: str, version: str) -> None:
    tarball = f"actions-runner-linux-x64-{version}.tar.gz"
    url = (
        f"https://github.com/actions/runner/releases/download/"
        f"v{version}/{tarball}"
    )
    repo_url = f"https://github.com/{repo}"

    print(f"Installing GitHub Actions runner v{version} on {host}")
    print(f"  Repo: {repo_url}")
    print(f"  Dir:  {RUNNER_DIR}")
    print(f"  Labels: {RUNNER_LABELS}")

    run_ssh(host, "root", [
        "apt-get update",
        "apt-get install -y curl tar jq libicu-dev",
        f"mkdir -p {RUNNER_DIR}",
    ])

    print("\n[1/5] Downloading runner tarball...")
    run_ssh(host, "root", [
        f"cd {RUNNER_DIR}",
        f"test -f {tarball} || curl -fsSL -o {tarball} {url}",
        f"tar xzf {tarball}",
    ])

    print("\n[2/5] Configuring runner against repo...")
    run_ssh(host, "root", [
        f"cd {RUNNER_DIR}",
        "export RUNNER_ALLOW_RUNASROOT=1",
        "./config.sh remove --token DUMMY || true",
        (
            f"RUNNER_ALLOW_RUNASROOT=1 ./config.sh --unattended --replace "
            f"--url {repo_url} "
            f"--token {token} "
            f"--name winebox-oat "
            f"--labels {RUNNER_LABELS} "
            f"--work _work"
        ),
    ])

    print("\n[3/5] Installing systemd service (as root)...")
    run_ssh(host, "root", [
        f"cd {RUNNER_DIR}",
        "RUNNER_ALLOW_RUNASROOT=1 ./svc.sh install root",
        "RUNNER_ALLOW_RUNASROOT=1 ./svc.sh start",
    ])

    print("\n[4/5] Setting up loopback SSH so deploys can target 127.0.0.1...")
    run_ssh(host, "root", [
        "test -f /root/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -f /root/.ssh/id_ed25519",
        "touch /root/.ssh/authorized_keys",
        "chmod 600 /root/.ssh/authorized_keys",
        "grep -qxFf /root/.ssh/id_ed25519.pub /root/.ssh/authorized_keys "
        "|| cat /root/.ssh/id_ed25519.pub >> /root/.ssh/authorized_keys",
        "ssh-keyscan -H 127.0.0.1 >> /root/.ssh/known_hosts 2>/dev/null || true",
        "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "
        "root@127.0.0.1 'echo loopback-ssh-ok'",
    ])

    print("\n[5/5] Installing uv for the runner...")
    run_ssh(host, "root", [
        "command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh",
        "test -x /root/.local/bin/uv && ln -sf /root/.local/bin/uv /usr/local/bin/uv || true",
        "uv --version",
    ])

    print("\nDone. Verify in GitHub: Settings -> Actions -> Runners.")
    print("The runner should appear as 'winebox-oat' with label 'oat'.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="OAT droplet IP")
    parser.add_argument("--token", required=True, help="Runner registration token from GitHub")
    parser.add_argument("--repo", default="jdrumgoole/winebox", help="owner/repo")
    parser.add_argument("--version", default=RUNNER_VERSION, help="Runner version")
    args = parser.parse_args()

    try:
        install(args.host, args.token, args.repo, args.version)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
