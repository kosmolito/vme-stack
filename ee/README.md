# vme-stack execution environment (EE)

One image with everything the pipeline needs: ansible-core, ansible-runner, the
Python library passlib, an SSH client **and the vme-stack code**
(`ansible`, baked in at `/opt/vme-stack/code`). Site data is never in the
image: the site directory (site file, vault, vault password, keys) is mounted.

## Build

```bash
ee/build.sh        # -> vme-stack-ee:<ee/VERSION> and vme-stack-ee:latest (this machine's arch)
PLATFORMS=linux/amd64,linux/arm64 IMAGE=ghcr.io/<owner>/vme-stack-ee ee/build.sh   # multi-arch, pushed
```

- Builds from the **committed** code (`git archive HEAD`), so local files such as
  `ansible/build/` (logs, rendered seeds) never get in. Commit first.
- Base image: Red Hat UBI 9 minimal (`registry.access.redhat.com`, layers from
  `cdn0[1-3].quay.io`); Python 3.12 and the system packages come from the UBI
  repositories (`cdn-ubi.redhat.com`). Image size about 415 MB.
- A proxy from the environment (`HTTP(S)_PROXY`, `NO_PROXY`) is passed into the build.

## Versions

- Tags are **vme-stack versions** (SemVer, `ee/VERSION`), not VME versions: the
  VME version is an input (the ISOs named in the site file). What changed in each
  version: [`CHANGELOG.md`](../CHANGELOG.md).
- The VME versions a release was tested with are in the image label
  `io.vme-stack.tested-with` (`VME_TESTED` in `ee/build.sh`) and below; `task
  release` adds the row from `VME_TESTED`, so update that first when testing a new
  VME version.

| vme-stack | tested with |
|---|---|
| 0.1.0 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.1 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.2 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.3 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.4 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.5 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.6 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.7 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |
| 0.1.8 | VME 9.0.2, hpe-vm 1.0.14-1, HPE_HVM_Install_24.04_S5Q83-11078 |

## Release (GHCR)

```bash
# 1. CHANGELOG.md: what changed, under "## [Unreleased]" (commit it)
task release VERSION=0.2.0    # checks, then bump + changelog + docs, commit "Release 0.2.0", tag v0.2.0
task release:push             # git push origin main v0.2.0 -> image tags 0.2.0 and latest on ghcr.io/kosmolito/vme-stack-ee
```

`task release` stops before changing anything unless:

- `0.2.0` is SemVer, above the latest `v*` tag, and not tagged yet
- the working tree is clean, on `main`, not behind `origin/main` (`OFFLINE=true`
  skips the fetch, e.g. without GitHub access)
- `CHANGELOG.md` has something under `## [Unreleased]`, and this file keeps its
  sections
- `task check` passes (lint and tests, as CI)

It then writes `ee/VERSION`, turns `[Unreleased]` into `[0.2.0] - <date>`, adds
the tested-with row and points image references in the docs (`vme-stack-ee:X.Y.Z`)
to the new version. `task test` (part of CI) checks the docs match `ee/VERSION`.

`.github/workflows/ee-release.yml` builds, smoke-tests and pushes the EE when the
tag arrives:

- The tag must match `ee/VERSION`, or the workflow stops.
- Pushes with the repository's `GITHUB_TOKEN` (`packages: write`), no extra secret.
- The image's `org.opencontainers.image.source` label links the package to this
  repository. The package is public: pulling needs no login.
- A manual run (`workflow_dispatch`) builds and smoke-tests without pushing.
- After the push, the GitHub release `v0.2.0` is created with the version's
  `CHANGELOG.md` section as its notes, plus the image and what it was tested with
  (`scripts/release.py notes 0.2.0` shows them; a re-run updates the release).

## Run

The usual way is **ansible-navigator** from the site directory, with the settings
file from [`sites/example/ansible-navigator.yml`](../sites/example/ansible-navigator.yml)
(image, mounts, inventory, vault password file, run records):

```bash
cd sites/acme                  # inventory.yml, ansible-navigator.yml, group_vars/, logs/, build/
ansible-navigator run preflight.yml
ansible-navigator run deploy.yml
ansible-navigator run hvm_hosts.yml --limit hvm02 -e force_reinstall=true
ansible-navigator exec -- bash # shell in the container (code dir), e.g. ansible-inventory --graph
```

The playbooks are in the image; navigator only needs their names. The site
directory is `/site` in the container (read-only), `logs/` is `/logs`. Create
`logs/` before the first run.

`build/` (mounted as the code's `build/`) is optional. Runs write the rendered
seeds (`build/<host>/user-data`, `meta-data`) and each host's ISO URL there; a run
uses its seeds itself, so without the mount nothing breaks, the files just go with
the container. Keep the mount for tools that attach the install ISO themselves
(they read `build/<host>/iso_url`) or to look at a seed when troubleshooting an
install. The example settings mount it: create `build/` too, or drop that line.

Without navigator, the same with plain Docker or Podman:

```bash
cd sites/acme
docker run --rm -it -v $PWD:/site:ro -v ~/.ssh:/home/runner/.ssh:ro -v $PWD/logs:/logs \
  ghcr.io/kosmolito/vme-stack-ee:0.1.8 \
  ansible-playbook deploy.yml -i /site/inventory.yml --vault-password-file /site/.vault_pass
```

- SSH key: `~/.ssh/id_ed25519` unless the inventory sets `ansible_ssh_private_key_file`.
  ansible-navigator mounts your `~/.ssh` at `/home/runner/.ssh` and the image links
  it as `~/.ssh`, so `~/.ssh/...` paths mean the same as on your machine (plain
  Docker: `-v ~/.ssh:/home/runner/.ssh:ro`). Keys in the site directory work too:
  `"{{ inventory_dir }}/keys/..."`.
- The pipeline only makes outgoing connections (SSH, HTTPS, Redfish); no
  `--network host` needed, also not on a Mac or over VPN.
- On the deploy server itself, keep the default SSH connection to its own
  address: `local` would mean inside the container.
- The image is multi-arch (linux/amd64, linux/arm64): an Apple Silicon Mac gets the
  native arm64 variant.
- Runs as uid 1000 (group 0): mounted files must be readable for it, `logs/` and
  `build/` (if mounted) writable (on Linux with another uid: `chmod a+rwx logs build`, and keys
  and `.vault_pass` readable for uid 1000; Docker Desktop on a Mac maps this itself).
- Without a command (plain Docker), the container starts a shell in the code directory.

## From a client (e.g. a Mac)

What has to be in place:

1. **Docker** (Docker Desktop, OrbStack or Colima on a Mac; Podman works too with
   `container-engine: podman` in `ansible-navigator.yml`) and
   **ansible-navigator** (`pip install ansible-navigator`, Python 3.10+). The image
   is public on GHCR, no login needed.
2. **A site directory**, see the [README](../README.md#quick-start) (copy
   [`sites/example/`](../sites/example/README.md)).
3. **Network from the client** (outgoing only): SSH (22) to the deploy server and to
   the HVM hosts (directly or via `ssh_jump`), HTTPS (443) to the BMCs for
   `platform: redfish`. The client does not need to reach the Manager or the media
   URLs: Manager API calls run from the deploy server, hosts/BMCs fetch the ISOs
   from it.
4. **The deploy server**: Debian/Ubuntu or RHEL family, the SSH user with
   passwordless sudo, and the two ISOs at the paths in the site file.

Start with `ansible-navigator run preflight.yml`: it checks everything without
changes.

## Logs and support bundle

Every `ansible-playbook` run writes its whole output to
`logs/<date>-<time>-<playbook>.log` (Ansible's `ANSIBLE_LOG_PATH`; in the container
`/logs`, mounted by the navigator settings or `-v $PWD/logs:/logs`). Without the
mount the log stays in the container and is lost; the run says so. Navigator also
records every run as `logs/<playbook>-<time>.json`: `ansible-navigator replay
logs/<run>.json` steps through it host by host, task by task.

With `VME_STACK_DEBUG=1` (`VME_STACK_DEBUG=1 ansible-navigator run ...`; plain
Docker: `-e VME_STACK_DEBUG=1`):

- the run is verbose (`-vvv`, also SSH details);
- afterwards, also after a failure, `collect.yml` runs with the same inventory,
  `--limit`, extra vars and vault options (`--ask-vault-pass` is asked once) and
  writes `/logs/vme-stack-support-<site>-<date>.tar.gz`:
  - controller: versions, the site file, the inventory as resolved, rendered seeds,
    the run's log
  - deploy server: OS, disk, mounts, nginx config and logs, published ISOs, SELinux,
    firewall, journal warnings
  - each HVM host: installer and cloud-init logs, netplan, addresses, routes, OVS,
    time sync, disks, libvirt, failed units, journal warnings, the `hpe-vm --install`
    log (Manager host)
  - the Manager (API): version, license, health, its own logs and alarms, groups,
    clouds, clusters, servers, instances, recent processes
  - `COLLECTED.txt` (which machines answered) and `REDACTED.txt`
- the exit code stays the run's.

Collecting changes nothing on the machines (temporary files only). Machines that do
not answer are listed in `COLLECTED.txt`; the rest is still collected.

**Secrets**: before packing, every value of the site's vault and every secret field
of the site file (literal ones too) is replaced by `********` in every collected
file, and password hashes are masked; `REDACTED.txt` lists what was replaced where
(counts only). Logs of other tools can contain secrets (e.g. HPE's `hpe-vm --install`
log has the Manager password): they are caught the same way. Check the bundle before
sending if in doubt; nothing is sent anywhere automatically.

The bundle on its own, e.g. later for a running system:

```bash
cd sites/acme && ansible-navigator run collect.yml
```

Without the container (Ansible installed): `python3 tools/vme_stack_run.py
ansible-playbook ...` in `ansible/` does the same, logs in `build/logs` or
`$VME_STACK_LOG_DIR`; `collect.yml` also runs directly.

## Hotfix (emergency code change)

Mount a host directory at `/vme-stack-hotfix`:

| mount | code used |
|---|---|
| none | the image's code |
| empty directory | the image's code is copied into it (plus `VERSION`), then used |
| directory with code | used as it is, nothing is copied |

```bash
mkdir /srv/vme-stack/hotfix
docker run --rm -v /srv/vme-stack/hotfix:/vme-stack-hotfix ... vme-stack-ee:0.1.8 true   # exports the code
vi /srv/vme-stack/hotfix/roles/...                                                       # fix
docker run --rm -v /srv/vme-stack/hotfix:/vme-stack-hotfix ... vme-stack-ee:0.1.8 ansible-playbook ...
```

With navigator, add the mount to `volume-mounts` in `ansible-navigator.yml`:
`- {src: /srv/vme-stack/hotfix, dest: /vme-stack-hotfix}`.

Every run prints which code it uses, e.g.
`vme-stack 0.1.0: using HOTFIX code from /vme-stack-hotfix (based on 0.1.0)`.
Leave the mount out and the image's code is used again. Get the fix back into git
(`diff -ru` against an export of the same image version) and release a new version;
an old hotfix directory mounted into a newer image is **not** detected automatically,
only shown in that line.
