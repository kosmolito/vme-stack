#!/usr/bin/env python3
"""Release checks and preparation for vme-stack (called by the Taskfile).

    release.py preflight X.Y.Z [--offline]   checks before a release, changes nothing
    release.py prepare X.Y.Z                 bump, changelog, docs; commit "Release X.Y.Z"
    release.py docs                          the docs match ee/VERSION (CI and after prepare)

Docs rules: CHANGELOG.md has a section for the version; the "tested with" table
in ee/README.md has a row for it (after prepare: equal to VME_TESTED in
ee/build.sh, the image label; between releases VME_TESTED may already name the
next tested VME); image references `vme-stack-ee:X.Y.Z` in the docs name the version.
"""

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "ee/VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"
EE_README = ROOT / "ee/README.md"
BUILD_SH = ROOT / "ee/build.sh"
# Docs that may show a pinned image version; prepare points them to the release.
PINNED_DOCS = [
    ROOT / "README.md",
    EE_README,
    ROOT / "ansible/examples/README.md",
]
# Sections ee/README.md must keep (what a user of the image needs).
EE_README_SECTIONS = ["## Build", "## Versions", "## Release", "## Run", "## Hotfix"]

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PIN = re.compile(r"vme-stack-ee:(\d+\.\d+\.\d+)")
UNRELEASED = "## [Unreleased]"


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


def section(text, heading_prefix):
    """Body of the first '## ' section whose heading starts with heading_prefix."""
    m = re.search(rf"^{re.escape(heading_prefix)}.*$", text, re.M)
    if not m:
        return None
    rest = text[m.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def vme_tested():
    m = re.search(r'VME_TESTED:-"([^"]+)"', BUILD_SH.read_text())
    if not m:
        sys.exit("ee/build.sh: no VME_TESTED default found")
    return m.group(1)


def table_row(version):
    return f"| {version} | {vme_tested()} |"


def docs_problems(version, exact_row=False):
    errs = []
    if VERSION_FILE.read_text().strip() != version:
        errs.append(f"ee/VERSION is {VERSION_FILE.read_text().strip()}, not {version}")
    if section(CHANGELOG.read_text(), f"## [{version}]") is None:
        errs.append(f"CHANGELOG.md has no section '## [{version}]'")
    readme = EE_README.read_text()
    if exact_row and table_row(version) not in readme:
        errs.append(f"ee/README.md: no row '{table_row(version)}' (from VME_TESTED in ee/build.sh)")
    elif not re.search(rf"^\| {re.escape(version)} \|", readme, re.M):
        errs.append(f"ee/README.md: no row for {version} in the tested-with table")
    errs += [f"ee/README.md: section '{s}' is missing" for s in EE_README_SECTIONS if s not in readme]
    for doc in PINNED_DOCS:
        for pinned in sorted(set(PIN.findall(doc.read_text())) - {version}):
            errs.append(f"{doc.relative_to(ROOT)}: refers to vme-stack-ee:{pinned}, not {version}")
    return errs


def preflight(version, offline):
    errs = []
    if not SEMVER.match(version):
        sys.exit(f"{version} is not X.Y.Z")
    tags = [t[1:] for t in git("tag", "-l", "v*").stdout.split() if SEMVER.match(t[1:])]
    if version in tags:
        errs.append(f"tag v{version} exists already")
    latest = max(tags, key=vtuple, default="0.0.0")
    if vtuple(version) <= vtuple(latest):
        errs.append(f"{version} is not above the latest release {latest}")
    if git("status", "--porcelain").stdout.strip():
        errs.append("working tree not clean (commit or stash first)")
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        errs.append(f"on branch {branch}, releases are made from main")
    if offline:
        print("WARNING: --offline: origin/main not fetched, comparing with the local copy")
    elif git("fetch", "-q", "origin", "main", check=False).returncode != 0:
        errs.append("cannot fetch origin/main (no access? use OFFLINE=true to compare with the local copy)")
    if git("merge-base", "--is-ancestor", "origin/main", "HEAD", check=False).returncode != 0:
        errs.append("main is behind origin/main: pull first")
    ahead = git("rev-list", "--count", "origin/main..HEAD", check=False).stdout.strip()
    if ahead not in ("", "0"):
        print(f"Note: {ahead} commit(s) not on origin/main yet; release:push pushes them too")
    body = section(CHANGELOG.read_text(), UNRELEASED)
    if body is None:
        errs.append(f"CHANGELOG.md has no '{UNRELEASED}' section")
    elif not body.strip():
        errs.append(f"CHANGELOG.md: '{UNRELEASED}' is empty, write what changed first")
    readme = EE_README.read_text()
    errs += [f"ee/README.md: section '{s}' is missing" for s in EE_README_SECTIONS if s not in readme]
    return errs


def prepare(version):
    VERSION_FILE.write_text(version + "\n")

    text = CHANGELOG.read_text()
    today = datetime.date.today().isoformat()
    text = text.replace(UNRELEASED, f"{UNRELEASED}\n\n## [{version}] - {today}", 1)
    CHANGELOG.write_text(text)

    readme = EE_README.read_text()
    rows = re.findall(r"^\| \d+\.\d+\.\d+ \|.*\|$", readme, re.M)
    if not rows:
        sys.exit("ee/README.md: tested-with table not found")
    readme = readme.replace(rows[-1], rows[-1] + "\n" + table_row(version), 1)
    EE_README.write_text(readme)

    for doc in PINNED_DOCS:
        doc.write_text(PIN.sub(f"vme-stack-ee:{version}", doc.read_text()))

    errs = docs_problems(version, exact_row=True)
    if errs:
        sys.exit("after prepare:\n  " + "\n  ".join(errs))
    files = [str(p.relative_to(ROOT)) for p in [VERSION_FILE, CHANGELOG, *PINNED_DOCS]]
    git("add", *files)
    git("commit", "-q", "-m", f"Release {version}")
    print(f"Committed 'Release {version}'")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("version")
    p.add_argument("--offline", action="store_true")
    sub.add_parser("prepare").add_argument("version")
    sub.add_parser("docs")
    a = ap.parse_args()

    if a.cmd == "preflight":
        errs = preflight(a.version, a.offline)
    elif a.cmd == "prepare":
        prepare(a.version)
        return
    else:
        errs = docs_problems(VERSION_FILE.read_text().strip())
    if errs:
        print("Release check failed:\n  " + "\n  ".join(errs))
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()
