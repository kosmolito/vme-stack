# Changelog

Changes of vme-stack (the EE image `ghcr.io/kosmolito/vme-stack-ee`), newest first.
Versions are vme-stack versions (`ee/VERSION`), not VME versions; the VME versions
each release was tested with are in [`ee/README.md`](ee/README.md#versions).

Write changes under **Unreleased** as you go, grouped as Added, Changed, Fixed,
Removed; **Breaking** marks a change that needs a site file edit.
`task release VERSION=X.Y.Z` turns the section into the release (and refuses an
empty one).

## [Unreleased]

### Added

- Preflight checks the reverse DNS (PTR) of the Manager's and the HVM hosts'
  addresses. A PTR name that is no valid host name (such as a leftover
  `*.apps.<domain>` wildcard) on the Manager's IP is an error: the appliance's
  setup fails on it. Other mismatches are warnings.
- The Manager install watches the Manager VM's first-boot setup (through its
  QEMU guest agent) while `hpe-vm` runs, and stops with the VM's error output
  when `morpheus-ctl reconfigure` failed, instead of waiting 90 minutes.

## [0.1.9] - 2026-10-13

### Added

- A GitHub release for each version, with its changelog section as the notes.
- `bmc_auth: session | basic`: how Redfish logs in to a BMC; set it for all
  hosts, a group or a host. `basic` never tries a session, for BMCs that refuse
  session logins (older iDRAC firmware), where each refused login counts toward
  iDRAC's IP blocking.

### Fixed

- Preflight failed on Dell iDRAC with "Redfish service not reachable ... 406 Not
  Acceptable": the check now sends `Accept: application/json`.
- Redfish boot failed with 401 on Dell iDRAC firmware that refuses session logins:
  it falls back to basic auth with the same credentials. Every Redfish request
  sends `Accept: application/json`.
- SSH failed with Docker Desktop (`muxserver_listen: link mux listener ... Bad file
  descriptor`): SSH's control sockets are now in `/tmp/ansible-cp`.
- Dell iDRAC9 booted the disk instead of the install ISO: the standard boot-once
  target `Cd` means the physical CD/DVD there. The host now boots once from the
  virtual CD through the iDRAC's own setting (`VCD-DVD`).
- A host whose `nics` MACs were written in uppercase came up without network,
  hostname or admin user (cloud-init saw the NICs as missing). MACs go into the
  install seed in lowercase.
- With a symlinked SSH key (e.g. `~/.ssh/id_ed25519`), the key Ansible logs in
  with was left out of the hosts' admin user, so the run could not log in after
  the install.

### Removed

- `jsonschema` from the image (unused since 0.1.4).

## [0.1.8] - 2026-10-12

### Added

- [`docs/variables.md`](docs/variables.md): every site variable with type,
  default and whether it is required; generated, `task check` keeps it current.
- Preflight checks the deploy server's connection variables.

## [0.1.7] - 2026-10-11

### Changed

- The Manager's SSH key pair defaults to the Manager host's login key
  (`ssh_private_key_file` and `<file>.pub`); no vault entries needed. Setting only
  one of `ssh_private_key`/`ssh_public_key` is an error.
- Example site files are named `inventory.yml` (was `site.yml`); any name works.

### Fixed

- Preflight rejected an SSH key that is a symlink.

## [0.1.6] - 2026-10-11

### Added

- A site can be split the Ansible way (INI inventory, `group_vars/`, `host_vars/`);
  see `sites/example/README.md`.

### Changed

- `~/.ssh/id_ed25519` is the default SSH key; `ansible_ssh_private_key_file` is
  optional. ansible-navigator mounts your `~/.ssh` into the container.
- The navigator settings set `container-engine: docker` (`auto` picks podman
  whenever it is installed). Podman users: `container-engine: podman`.

### Fixed

- The support bundle was not written when rendered seeds existed (since 0.1.3).

## [0.1.5] - 2026-10-11

### Added

- `ansible-navigator.yaml` in the repository root: runs the image with your
  clone's `ansible/` as its code, for development without a rebuild.

### Changed

- `sites/example/ansible-navigator.yml` uses `vme-stack-ee:latest`; pin a version
  there to stay on it.

## [0.1.4] - 2026-10-11

### Changed

- **Breaking:** the site file is a plain Ansible inventory: groups
  `deploy_server`, `hvm`, `vme_manager`; Ansible's own `ansible_host`,
  `ansible_user`, `ansible_ssh_private_key_file`; `media` is a host var of the
  deploy server. Convert old files after `sites/example/`; an old file fails with
  "not a vme-stack site inventory".
- Validation per variable (`roles/preflight/meta/argument_specs.yml`) and site
  rules, all problems at once; `validate.yml` checks a site without contacting
  anything.
- Per-host ISOs are named `hvm-<host>.iso`.
- `media.yml` prints every host's ISO URL, also when nothing was built.

### Added

- Run with ansible-navigator from the site directory
  (`sites/example/ansible-navigator.yml`); runs are recorded in `logs/`.
- Keys in the site directory: `"{{ inventory_dir }}/keys/..."`.

### Removed

- The custom inventory plugin and the JSON schema.

### Fixed

- `media_server` misread the deploy server's state where `systemctl` prints
  nothing.

## [0.1.3] - 2026-10-11

### Added

- Run logs: each run writes `/logs/<date>-<time>-<playbook>.log` when `/logs` is
  mounted.
- Support bundle: `VME_STACK_DEBUG=1` (or `collect.yml`) collects logs and state
  of all machines into `/logs/vme-stack-support-<site>-<date>.tar.gz`, secrets
  replaced. See `ee/README.md`.

## [0.1.2] - 2026-10-11

### Changed

- **Breaking:** SSH keys per login; `access` is gone. Deploy server:
  `deploy_server.user` + `ssh_private_key`; HVM hosts: `hvm_admin_user` +
  `hvm_ssh_private_key`; jump host: `deploy_server.jump`. The hosts get the public
  key of their login key; `hvm_ssh_keys` adds more.
- From the container, the deploy server connection is always `ssh`.

## [0.1.1] - 2026-10-11

### Changed

- **Breaking:** secret fields hold values (usually
  `"{{ vault_<name> }}"`), not vault variable names; preflight lists secrets that
  do not resolve.
- **Breaking:** renamed keys: `admin_user`/`admin_password` →
  `hvm_admin_user`/`hvm_admin_password`; `bmc.credentials` → `bmc.username` +
  `bmc.password`; `vcenter.credentials` → `vcenter.username` + `vcenter.password`.
- Preflight: all hosts of a cluster need the same `hvm_admin_password`.

## [0.1.0] - 2026-10-11

First public release: from empty servers or VMs to a working HPE VM Essentials
environment from one site file. Tested end to end with VME 9.0.2 (8.1.1 also
supported), about 45 minutes.

### Added

- Site file with checks before anything runs; example sites in
  `ansible/examples/` and `sites/example/`.
- Preflight (`preflight.yml`, changes nothing): deploy server, SSH, DNS, NTP,
  BMCs, netplan.
- HVM hosts: unattended install from HPE's HVM ISO, one ISO per host built and
  served by the deploy server; boot over Redfish (iLO, iDRAC; untested on real
  hardware) or by hand (`platform: manual`). NIC layouts or raw netplan; disk
  selection.
- Safe re-runs: installed hosts skipped, foreign machines on a host's IP stop the
  run; `force_reinstall` with `--limit`.
- VME Manager: installed with `hpe-vm --install`, first-time setup through the
  API, optionally moved to shared storage.
- Manager objects: groups, clouds (HVM, vCenter) and HVM clusters with NFS
  datastores; created if missing, never changed or deleted.
- Container image `ghcr.io/kosmolito/vme-stack-ee` (amd64, arm64) with a hotfix
  mount.
