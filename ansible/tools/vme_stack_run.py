#!/usr/bin/env python3
"""Run a vme-stack command with a run log, and a support bundle when debugging.

    vme_stack_run.py ansible-playbook deploy.yml -i /site/inventory.yml --ask-vault-pass

The EE entrypoint runs every command through this. Anything but ansible-playbook
is started as it is. For ansible-playbook:

- The whole output also goes to a run log, <log dir>/<date>-<time>-<playbook>.log
  (Ansible's own ANSIBLE_LOG_PATH). Log dir: VME_STACK_LOG_DIR (the EE sets /logs
  when it is mounted), else build/logs next to the playbooks.
- VME_STACK_DEBUG=1: more output (-vvv), and afterwards, also after a failure,
  collect.yml with the same inventory, limit, extra vars and vault options:
  logs and state of all machines in one .tar.gz in the log dir, secrets replaced.
  --ask-vault-pass is asked once and handed to both runs through a private
  temporary file, removed at the end.

Exit code: the playbook's.
"""

import datetime
import getpass
import os
import pwd
import subprocess
import sys
import tempfile
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent  # the directory with the playbooks
# Options the collection run takes over from the main run (with their value).
FORWARD = {
    "-i",
    "--inventory",
    "--inventory-file",
    "-l",
    "--limit",
    "-e",
    "--extra-vars",
    "--vault-id",
    "--vault-password-file",
    "--vault-pass-file",
}
ASK_VAULT = {"-J", "--ask-vault-pass", "--ask-vault-password"}
TRUE = {"1", "true", "yes", "on"}


def log_dir():
    d = Path(os.environ.get("VME_STACK_LOG_DIR") or CODE / "build" / "logs")
    d.mkdir(parents=True, exist_ok=True)
    return d


def playbook_of(args):
    return next((Path(a).stem for a in args if a.endswith((".yml", ".yaml")) and not a.startswith("@")), "run")


def forwarded(args):
    """The options of args that collect.yml needs too, in order."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        name = a.split("=", 1)[0] if a.startswith("--") else a
        if name in FORWARD:
            if "=" in a and a.startswith("--"):
                out.append(a)
            elif i + 1 < len(args):
                out += [a, args[i + 1]]
                i += 1
        i += 1
    return out


def link_mounted_ssh():
    """ansible-navigator mounts the user's ~/.ssh at /home/runner/.ssh (plain Docker:
    -v ~/.ssh:/home/runner/.ssh:ro); link it as this user's ~/.ssh, so ~/.ssh/id_ed25519
    (ansible.cfg's default key) means the same as on the user's machine. Here, after
    the image's own entrypoint, the home directory is known (not yet in ours)."""
    mounted = Path("/home/runner/.ssh")
    home = Path(os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir)
    link = home / ".ssh"
    if mounted.is_dir() and home != mounted.parent and not link.exists() and not link.is_symlink():
        try:
            link.symlink_to(mounted)
        except OSError:
            pass


def main(argv):
    link_mounted_ssh()
    if not argv or Path(argv[0]).name != "ansible-playbook":
        if not argv:
            argv = ["bash"]
        os.execvp(argv[0], argv)

    cmd, args = argv[0], argv[1:]
    debug = os.environ.get("VME_STACK_DEBUG", "").lower() in TRUE
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    logs = log_dir()
    run_log = logs / f"{stamp}-{playbook_of(args)}.log"
    env = dict(os.environ, ANSIBLE_LOG_PATH=str(run_log), VME_STACK_RUN_LOG=str(run_log))
    if debug:
        env.setdefault("ANSIBLE_VERBOSITY", "3")

    pass_file = None
    try:
        if debug and any(a in ASK_VAULT for a in args):
            # Ask once; both runs read it from a file only this user can read.
            try:
                secret = getpass.getpass("Vault password: ")
            except (EOFError, KeyboardInterrupt):
                print("\nvme-stack: no vault password given", file=sys.stderr)
                return 1
            shm = "/dev/shm" if os.path.isdir("/dev/shm") else None  # memory only, where there is one
            fd, pass_file = tempfile.mkstemp(prefix="vme-stack-vault-", dir=shm)
            with os.fdopen(fd, "w") as f:
                f.write(secret + "\n")
            args = [a for a in args if a not in ASK_VAULT] + ["--vault-password-file", pass_file]

        note = " (VME_STACK_DEBUG: support bundle at the end)" if debug else ""
        print(f"vme-stack: run log {run_log}{note}", file=sys.stderr)
        if not os.environ.get("VME_STACK_LOG_DIR") and Path("/opt/vme-stack").is_dir():
            print(
                "vme-stack: no /logs mount, the log is lost with the container (mount e.g. -v $PWD/logs:/logs)",
                file=sys.stderr,
            )
        rc = subprocess.call([cmd, *args], env=env)

        if debug and playbook_of(args) != "collect":
            print(f"vme-stack: collecting the support bundle (the run ended with exit code {rc})", file=sys.stderr)
            collect_log = logs / f"{stamp}-collect.log"
            subprocess.call(
                [cmd, str(CODE / "collect.yml"), *forwarded(args)],
                env=dict(env, ANSIBLE_LOG_PATH=str(collect_log), ANSIBLE_VERBOSITY="0"),
            )
        return rc
    finally:
        if pass_file:
            os.unlink(pass_file)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
