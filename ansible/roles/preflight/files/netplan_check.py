#!/usr/bin/env python3
"""Validate raw netplan with netplan's own parser (python3-netplan); no root, no changes.

usage: netplan_check.py <file.json>   with {"<host>": {<netplan: version: 2, ...>}, ...}
Prints {"<host>": null | "<error>"} as JSON, or {"_unavailable": "<why>"} without netplan.
"""

import json
import os
import sys
import tempfile

try:
    import netplan
except ImportError:  # e.g. a RHEL-family deploy server: no python3-netplan there
    print(json.dumps({"_unavailable": "python3-netplan is not installed on this host"}))
    sys.exit(0)


def check(np):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "50-vme-stack.yaml")
        with open(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600), "w") as f:
            json.dump({"network": np}, f)  # JSON is valid YAML; 0600 or netplan warns
        try:
            parser = netplan.Parser()
            parser.load_yaml(path)
            netplan.State().import_parser_results(parser)
        except Exception as e:  # netplan raises its own error types
            # First line only: the rest is netplan quoting our (JSON) input back.
            return str(e).strip().splitlines()[0]
    return None


with open(sys.argv[1]) as f:
    print(json.dumps({host: check(np) for host, np in json.load(f).items()}))
