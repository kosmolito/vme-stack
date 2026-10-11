#!/usr/bin/env python3
"""Check site inventories with validate.yml (what preflight checks first), no machines.

    check_sites.py <site.yml> ...     every file must pass (exit 1 otherwise)
    check_sites.py --cases <cases>    each case must fail with its expected message

Each site file is copied alone into a temporary directory (an encrypted vault next
to it is not loaded) and gets a dummy value for every "{{ vault_... }}" it refers
to, so the checks run without the vault: in CI and for the lab alike.
"""

import argparse
import copy
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the ansible/ project
VAULT_REF = re.compile(r"\{\{\s*(vault_\w+)(?:\.(\w+))?\s*\}\}")
# ansible-playbook next to this Python (the .venv), else from PATH
_beside = Path(sys.executable).parent / "ansible-playbook"
ANSIBLE_PLAYBOOK = str(_beside) if _beside.exists() else (shutil.which("ansible-playbook") or "ansible-playbook")
DUMMY_PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDummyDummyDummyDummyDummyDummyDummyDummy check"


def dummy_vault(text):
    """A value for every vault variable the site refers to ({name} or {name: {field}})."""
    out = {}
    for name, field in VAULT_REF.findall(text):
        value = DUMMY_PUBLIC_KEY if "public_key" in (field or name) else f"dummy-{name}-{field or 'value'}"
        if field:  # also used with a field somewhere: a dict wins over a plain value
            out[name] = out[name] if isinstance(out.get(name), dict) else {}
            out[name][field] = value
        else:
            out.setdefault(name, value)
    return out


def validate(inventory_text):
    """Run validate.yml on an inventory; return (passed, output)."""
    with tempfile.TemporaryDirectory(prefix="vme-check-") as d:
        inv = Path(d) / "site.yml"
        inv.write_text(inventory_text)
        extra = Path(d) / "vault.yml"
        extra.write_text(yaml.safe_dump(dummy_vault(inventory_text)))
        env = dict(
            os.environ,
            ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"),
            ANSIBLE_NOCOLOR="1",
            ANSIBLE_FORCE_COLOR="0",
            ANSIBLE_LOG_PATH="",
        )
        r = subprocess.run(
            [ANSIBLE_PLAYBOOK, str(ROOT / "validate.yml"), "-i", str(inv), "-e", f"@{extra}"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
        )
        return r.returncode == 0, r.stdout + r.stderr


def merge(base, patch):
    """Deep merge for the test cases: dicts merge, everything else replaces; None deletes."""
    out = copy.deepcopy(base)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def problems_of(output):
    """The problem lines of a failed run (for the report)."""
    lines = [ln.strip().strip('",') for ln in output.splitlines()]
    return [ln for ln in lines if ln and (": " in ln) and not ln.startswith(("TASK", "PLAY", "ok:", "fatal:"))][:12]


def check_files(paths):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: validate(Path(p).read_text()), paths))
    failed = 0
    for p, (ok, out) in zip(paths, results, strict=True):
        print(f"{'ok  ' if ok else 'FAIL'} {p}")
        if not ok:
            print("       " + "\n       ".join(problems_of(out)))
        failed += not ok
    return failed


def check_cases(path):
    doc = yaml.safe_load(Path(path).read_text())
    base = doc["base"]
    cases = [{"name": "base site passes", "patch": {}, "expect": None}] + doc["cases"]
    texts = [yaml.safe_dump(merge(base, c["patch"]), sort_keys=False) for c in cases]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(validate, texts))
    failed = 0
    for case, (ok, out) in zip(cases, results, strict=True):
        hit = ok if case["expect"] is None else (not ok and case["expect"] in out)
        print(f"{'ok  ' if hit else 'FAIL'} {case['name']}")
        if not hit:
            print(f"       expected: {case['expect'] or 'no problems'}")
            print("       got:      " + ("\n                 ".join(problems_of(out)) or "no problems"))
        failed += not hit
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", help="YAML with a base site and cases that must fail")
    ap.add_argument("files", nargs="*", help="site files that must pass")
    a = ap.parse_args()
    failed = check_files(a.files)
    if a.cases:
        failed += check_cases(a.cases)
    print(f"\n{failed} failed" if failed else "\nall passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
