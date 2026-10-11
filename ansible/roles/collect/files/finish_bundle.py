#!/usr/bin/env python3
"""Finish a support bundle: unpack the machines' collections, replace the
secrets, pack one .tar.gz. Python only (the EE image has no tar).

    finish_bundle.py <bundle dir> <values file>

<machine>.tar.gz in the bundle dir is unpacked into <machine>/ and removed.
<values file>: JSON {"vault": <the site's vault as data>, "secrets": [<resolved
secret fields>]}; every string in it counts, multi-line ones (keys) also line by
line. Each occurrence in a text file becomes ********, longest values first;
password hashes ($6$..., $y$...) are masked as well. Binary files are left out
of the bundle. REDACTED.txt in the bundle lists the replacements per file
(counts only, never values). Result: <bundle dir>.tar.gz; the directory is removed.
"""

import json
import re
import shutil
import sys
import tarfile
from pathlib import Path

MASK = "********"
HASH = re.compile(r"\$(?:1|2[aby]|5|6|y|gy|7)\$[./A-Za-z0-9$]{8,}")


def strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)
    elif isinstance(x, str):
        yield x.strip()
        yield from (line.strip() for line in x.splitlines())


def unpack(bundle):
    for tgz in sorted(Path(bundle).glob("*.tar.gz")):
        dest = Path(bundle) / tgz.name[: -len(".tar.gz")]
        dest.mkdir(exist_ok=True)
        try:
            with tarfile.open(tgz) as tar:
                tar.extractall(dest, filter="data")  # no links or paths out of dest
        except (tarfile.TarError, OSError) as e:
            (dest / "UNPACK-FAILED.txt").write_text(f"{tgz.name}: {e}\n")
        tgz.unlink()


def redact(bundle, values_file):
    # Shorter than 4 characters would mask unrelated text; such secrets are weak anyway.
    found = {s for s in strings(json.loads(Path(values_file).read_text())) if len(s) >= 4}
    values = sorted(found, key=len, reverse=True)
    report, dropped = [], []
    for f in sorted(p for p in Path(bundle).rglob("*") if p.is_file() and not p.is_symlink()):
        data = f.read_bytes()
        if b"\0" in data:
            dropped.append(str(f.relative_to(bundle)))
            f.unlink()
            continue
        text = data.decode("utf-8", errors="surrogateescape")
        n = 0
        for v in values:
            c = text.count(v)
            if c:
                text = text.replace(v, MASK)
                n += c
        text, h = HASH.subn("$*$" + MASK, text)
        if n or h:
            f.write_text(text, encoding="utf-8", errors="surrogateescape")
            report.append(f"{f.relative_to(bundle)}: {n} secret(s), {h} password hash(es)")
    lines = [
        f"Secrets replaced by {MASK}: every value of the site's vault and every secret field of the site file",
        f"({len(values)} distinct values checked), and password hashes. Files changed:",
        *(report or ["(none)"]),
    ]
    if dropped:
        lines += ["", "Binary files left out:", *dropped]
    (Path(bundle) / "REDACTED.txt").write_text("\n".join(lines) + "\n")
    return f"redacted: {len(report)} file(s) changed, {len(dropped)} binary file(s) left out"


def main(bundle, values_file):
    bundle = Path(bundle)
    unpack(bundle)
    summary = redact(bundle, values_file)
    with tarfile.open(f"{bundle}.tar.gz", "w:gz") as tar:
        tar.add(bundle, arcname=bundle.name)
    shutil.rmtree(bundle)
    print(f"{bundle}.tar.gz")
    print(summary)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
