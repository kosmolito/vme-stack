#!/usr/bin/env python3
"""Write docs/variables.md, the reference of every site variable, from the argument
spec preflight validates the site with (ansible/roles/preflight/meta/argument_specs.yml).

    variables_doc.py           write docs/variables.md
    variables_doc.py --check   exit 1 if docs/variables.md is not up to date
"""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "ansible/roles/preflight/meta/argument_specs.yml"
DOC = ROOT / "docs/variables.md"

INTRO = """\
# Site variables

Every variable a site inventory can set, with what it does and its default. Generated
from [`argument_specs.yml`](../ansible/roles/preflight/meta/argument_specs.yml), the
spec preflight checks every site against (`task docs` writes this file). For a full
example with comments see [`sites/example/inventory.yml`](../sites/example/inventory.yml).

- **Where**: site-wide settings go in `all.vars` of the inventory (or a file in
  `group_vars/all/` of a split site), the deploy server's in its host vars, the HVM
  hosts' in `hvm` group vars (defaults for all hosts) or per host.
- **Names** with dots are keys inside a dict (`network.domain`); `[]` marks a list of
  dicts (`vme_clusters[].hosts`).
- **Secrets** (marked *Secret*) are best vault references: `"{{ vault_x }}"` with
  `vault_x` in an encrypted `group_vars/all/vault.yml`; a literal works too.
- **Required** (yes) means within its parent: `vme_manager.ip` is required once
  `vme_manager` is set.
- Rules across variables (unique IPs and MACs, references between Manager objects,
  one password per cluster, ...) are checked by preflight as well; it lists every
  problem at once. Check a site without contacting anything: `validate.yml`.
"""


def type_of(o):
    t = o.get("type", "str")
    if t == "list":
        t = f"list of {o.get('elements', 'str')}"
    if o.get("choices"):
        t += ": " + ", ".join(f"`{c}`" for c in o["choices"])
    return t


# Keys an option may have; anything else is usually an unquoted ", " in a flow mapping.
KNOWN = {"type", "required", "choices", "description", "options", "elements", "no_log", "default"}


def problems(options, prefix=""):
    for name, o in options.items():
        if set(o) - KNOWN:
            yield f"{prefix}{name}: unknown keys {sorted(set(o) - KNOWN)} (an unquoted comma in a description?)"
        if not o.get("description"):
            yield f"{prefix}{name}: no description"
        if o.get("options"):
            yield from problems(o["options"], f"{prefix}{name}.")


def rows(options, prefix=""):
    for name, o in options.items():
        path = prefix + name
        desc = " ".join(str(o.get("description", "")).split())
        desc = desc.replace("<", "&lt;").replace(">", "&gt;")  # <ip> etc. are no HTML tags
        if o.get("no_log"):
            desc = "*Secret.* " + desc
        yield path, type_of(o), "yes" if o.get("required") else "", desc
        if o.get("options"):
            sub = path + ("[]." if o.get("type") == "list" else ".")
            yield from rows(o["options"], sub)


def render():
    spec = yaml.safe_load(SPEC.read_text())["argument_specs"]
    out = [INTRO]
    for entry in spec.values():
        out.append(f"\n## {entry['short_description']}\n")
        out.append("| Variable | Type | Required | What it is |")
        out.append("|---|---|---|---|")
        for path, typ, req, desc in rows(entry["options"]):
            desc = desc.replace("|", "\\|")
            out.append(f"| `{path}` | {typ} | {req} | {desc} |")
    out.append(
        "\n## Environment\n\n"
        "| Variable | What it is |\n|---|---|\n"
        "| `VME_STACK_DEBUG` | `1`: more detail in the run, and a support bundle in `logs/` at the end"
        " (also after a failure). See [`ee/README.md`](../ee/README.md#logs-and-support-bundle). |"
    )
    return "\n".join(out) + "\n"


def main():
    spec = yaml.safe_load(SPEC.read_text())["argument_specs"]
    errs = [e for entry in spec.values() for e in problems(entry["options"])]
    if errs:
        print("\n".join([f"{SPEC.relative_to(ROOT)}:"] + errs))
        return 1
    text = render()
    if "--check" in sys.argv[1:]:
        if not DOC.exists() or DOC.read_text() != text:
            print(f"{DOC.relative_to(ROOT)} is out of date: run task docs")
            return 1
        print(f"{DOC.relative_to(ROOT)} is up to date")
        return 0
    DOC.parent.mkdir(exist_ok=True)
    DOC.write_text(text)
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
