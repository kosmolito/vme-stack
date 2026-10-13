#!/usr/bin/env python3
"""Run a command in the Manager VM through its QEMU guest agent. Prints JSON.

usage: manager_exec.py <domain> <command> [args...]

No network and no login needed: the HVM host reaches the VM's agent through libvirt.
Standard library only; run as root on the host that runs the VM.
"""

import base64
import json
import subprocess
import sys
import time


def agent(domain, cmd, timeout=30):
    r = subprocess.run(
        ["virsh", "qemu-agent-command", domain, json.dumps(cmd), "--timeout", str(timeout)],
        capture_output=True,
        text=True,
        timeout=timeout + 10,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"virsh exited {r.returncode}")
    return json.loads(r.stdout)["return"]


def main():
    domain, argv = sys.argv[1], sys.argv[2:]
    try:
        pid = agent(
            domain,
            {"execute": "guest-exec", "arguments": {"path": argv[0], "arg": argv[1:], "capture-output": True}},
        )["pid"]
        for _ in range(600):
            st = agent(domain, {"execute": "guest-exec-status", "arguments": {"pid": pid}})
            if st.get("exited"):
                out = {
                    "rc": st.get("exitcode", -1),
                    "stdout": base64.b64decode(st.get("out-data", "")).decode("utf-8", "replace"),
                    "stderr": base64.b64decode(st.get("err-data", "")).decode("utf-8", "replace"),
                }
                break
            time.sleep(1)
        else:
            out = {"rc": -1, "stdout": "", "stderr": "command still running after 10 minutes"}
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
        out = {"rc": -1, "stdout": "", "stderr": f"guest agent: {e}"}
    print(json.dumps(out))
    sys.exit(0 if out["rc"] == 0 else 1)


if __name__ == "__main__":
    main()
