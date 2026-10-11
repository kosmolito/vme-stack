#!/usr/bin/env python3
"""Check site files without running Ansible (no vault, no lab): schema + site rules.

    check_sites.py <site.yml> ...     every file must pass (exit 1 otherwise)
    check_sites.py --cases <cases>    each case must fail with its expected message

The schema check and its messages come from the inventory plugin, the site rules
from the filter plugin, so this tests exactly what preflight runs.
"""

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the ansible/ project
ROLES = ROOT / "roles"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inventory = _load("vme_site_inventory", ROOT / "plugins/inventory/vme_site.py")
rules = _load("vme_site_filter", ROOT / "plugins/filter/vme_site.py")
VALIDATOR = Draft202012Validator(json.loads(inventory.SCHEMA.read_text()))


def problems(site):
    """Everything the inventory plugin and preflight would report, as strings."""
    errs = sorted(VALIDATOR.iter_errors(site), key=lambda e: list(map(str, e.absolute_path)))
    if errs:  # like the plugin: schema problems stop before the rules run
        return list(dict.fromkeys(f"{inventory._path(e)}: {inventory._message(e)}" for e in errs))
    names = [h["name"] for h in site["hosts"]] + [site["deploy_server"].get("name", "deploy")]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        return [f"names used more than once: {', '.join(dupes)}"]
    return rules.vme_site_errors(site, str(ROLES))


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


def check_files(paths):
    failed = 0
    for p in paths:
        found = problems(yaml.safe_load(Path(p).read_text()))
        print(f"{'FAIL' if found else 'ok  '} {p}")
        for f in found:
            print(f"       {f}")
        failed += bool(found)
    return failed


def check_cases(path):
    doc = yaml.safe_load(Path(path).read_text())
    base = doc["base"]
    failed = 0
    found = problems(base)
    print(f"{'FAIL' if found else 'ok  '} base site passes")
    failed += bool(found)
    for case in doc["cases"]:
        found = problems(merge(base, case["patch"]))
        hit = any(case["expect"] in f for f in found)
        print(f"{'ok  ' if hit else 'FAIL'} {case['name']}")
        if not hit:
            print(f"       expected: {case['expect']}")
            print(f"       got:      {found or 'no problems'}")
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
