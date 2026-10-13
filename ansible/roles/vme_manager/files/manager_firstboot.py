#!/usr/bin/env python3
"""Watch hpe-vm --install and the Manager VM's first boot on the HVM host. Prints JSON.

usage: manager_firstboot.py <unit> <domain>

hpe-vm waits for https://<ip>/ping and never notices when the appliance's own setup
(morpheus-ctl reconfigure, run by cloud-init in the VM) failed. The VM has a QEMU guest
agent, so the host reads the VM's cloud-init output through libvirt: no network, no
login. Standard library only; run as root.
"""

import base64
import json
import subprocess
import sys
import time

# Failure lines of morpheus-ctl (omnibus-ctl) and Chef in cloud-init's output. Lines of
# file diffs Chef prints ("  +...", "  -...") are skipped: they quote scripts.
FAILURE = r"There was an error running|Infra Phase failed|Chef (Infra )?Client failed|FATAL: "
GUEST_CMD = (
    "f=/var/log/cloud-init-output.log; [ -r $f ] || exit 0; "
    f"grep -v -E '^\\s+[-+]' $f | grep -E -A4 '{FAILURE}' | grep -v -x -- -- | head -n 30"
)


def agent(domain, cmd, timeout=10):
    r = subprocess.run(
        ["virsh", "qemu-agent-command", domain, json.dumps(cmd), "--timeout", str(timeout)],
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"virsh exited {r.returncode}")
    return json.loads(r.stdout)["return"]


def guest_failure(domain):
    """Failure lines from the VM's first boot ([] = none so far); None if the agent is not up."""
    try:
        pid = agent(
            domain,
            {
                "execute": "guest-exec",
                "arguments": {"path": "/bin/sh", "arg": ["-c", GUEST_CMD], "capture-output": True},
            },
        )["pid"]
        for _ in range(20):
            st = agent(domain, {"execute": "guest-exec-status", "arguments": {"pid": pid}})
            if st.get("exited"):
                out = base64.b64decode(st.get("out-data", "")).decode("utf-8", "replace")
                return [line.rstrip() for line in out.splitlines() if line.strip()]
            time.sleep(1)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        pass
    return None


def main():
    unit, domain = sys.argv[1], sys.argv[2]
    active = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True).stdout.strip() in (
        "active",
        "activating",
    )
    vm = subprocess.run(["virsh", "domstate", domain], capture_output=True, text=True).returncode == 0
    lines = guest_failure(domain) if vm else None
    print(
        json.dumps(
            {
                "hpe_vm_active": active,
                "vm": vm,
                "agent": lines is not None,
                "firstboot_failed": bool(lines),
                "lines": lines or [],
                "done": not active or bool(lines),
            }
        )
    )


if __name__ == "__main__":
    main()
