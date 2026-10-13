#!/usr/bin/env python3
"""The task library's names agree (task check):

- vme_manager.tasks.type choices (roles/preflight/meta/argument_specs.yml) are exactly
  the types vme-stack maps to the Manager's codes (roles/vme_tasks/vars/main.yml);
- every catalog task (roles/vme_tasks/files/catalog/catalog.yml) has a mapped type,
  the fields the role reads, a script <key>.sh, and a key starting with its type (bash-).
"""

import pathlib
import sys

import yaml

ROLES = pathlib.Path(__file__).resolve().parent.parent / "roles"


def main():
    spec = yaml.safe_load((ROLES / "preflight/meta/argument_specs.yml").read_text())
    task_opts = spec["argument_specs"]["site_settings"]["options"]["vme_manager"]["options"]["tasks"]["options"]
    choices = set(task_opts["type"]["choices"])
    mapped = yaml.safe_load((ROLES / "vme_tasks/vars/main.yml").read_text())["vt_types_map"]
    catalog_dir = ROLES / "vme_tasks/files/catalog"
    catalog = yaml.safe_load((catalog_dir / "catalog.yml").read_text())
    errs = []
    if choices != set(mapped):
        errs.append(f"type choices {sorted(choices)} != mapped types {sorted(mapped)} (vars/main.yml)")
    for name, t in mapped.items():
        if not t.get("code") or not t.get("ui"):
            errs.append(f"vars/main.yml: type {name} needs code and ui")
    for key, c in catalog.items():
        for field in ("name", "type", "target", "sudo"):
            if field not in c:
                errs.append(f"catalog {key}: no {field}")
        if c.get("type") not in mapped:
            errs.append(f"catalog {key}: type {c.get('type')} is not a mapped type ({', '.join(sorted(mapped))})")
        elif not key.startswith(c["type"] + "-"):
            errs.append(f"catalog {key}: the key must start with its type ({c['type']}-)")
        if not (catalog_dir / f"{key}.sh").is_file():
            errs.append(f"catalog {key}: no script {key}.sh")
    for e in errs:
        print(e)
    print("task catalog ok" if not errs else f"{len(errs)} problem(s)")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
