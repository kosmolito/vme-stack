# Changelog

Changes of vme-stack (the EE image `ghcr.io/kosmolito/vme-stack-ee`), newest first.
Versions are vme-stack versions (`ee/VERSION`), not VME versions; the VME versions a
release was tested with are in [`ee/README.md`](ee/README.md#versions).

Write changes under **Unreleased** as you go; `task release VERSION=X.Y.Z` turns
that section into the release's section (and refuses to release with it empty).

## [Unreleased]

- The navigator settings (`sites/example/ansible-navigator.yml`, the repository's
  `ansible-navigator.yaml`) set `container-engine: docker`: with `auto` (also the
  default when it is missing) navigator takes podman whenever podman is installed,
  even when Docker is the engine in use, and the run fails. Podman users set
  `container-engine: podman`.

## [0.1.5] - 2026-10-11

- `ansible-navigator.yaml` in the repository root, for working on vme-stack: runs
  the project image (`vme-stack-ee:latest`) with the clone's own `ansible/` as its
  code (the image's hotfix mount), so changes run in the real EE without a rebuild.
- `sites/example/ansible-navigator.yml` uses `vme-stack-ee:latest` (pulled again
  when a newer one is published); pin a version there to stay on it.

## [0.1.4] - 2026-10-11

- **Site file change: the site file is a plain Ansible inventory** (YAML, any
  name). No custom inventory plugin and no JSON schema any more. `all.vars` holds
  the site-wide settings (`site`, `network`, `ssh_jump`, `vme_manager`,
  `vme_groups`, `vme_clouds`, `vme_clusters`); group `deploy_server` the deploy
  server, group `hvm` the HVM hosts (their defaults as group vars, overrides as
  host vars), group `vme_manager` the host that runs the Manager VM (was
  `vme_manager.host`). Connections use Ansible's own variables: `ansible_host`
  (the host's static IP; was `ip`, deploy server `address`), `ansible_user` (was
  `hvm_admin_user`, deploy server `user`), `ansible_ssh_private_key_file` (was
  `hvm_ssh_private_key`/`ssh_private_key`); `ssh_jump` (was `deploy_server.jump`).
  `media` is a host var of the deploy server (it describes that server), with
  `hvm_iso_path`/`vme_iso_path` (were `hvm_iso`/`vme_iso`) and
  `www_root`/`work_dir`/`port`/`url` (were `deploy_server.*`). Convert old site
  files after `sites/example/site.yml`; an old file fails with "not a vme-stack
  site inventory".
- **Validation per variable**: preflight (and `validate.yml`, which contacts no
  machine) checks that secrets resolve, every variable against
  `roles/preflight/meta/argument_specs.yml` (types, required, allowed values,
  unknown keys of known dicts), then the site rules (formats, unique IPs/MACs,
  references, one deploy server and one Manager host); every problem of a step at
  once, over the whole site even with `--limit`.
- **Run with ansible-navigator** from the site directory:
  `cd sites/acme && ansible-navigator run deploy.yml`.
  `sites/example/ansible-navigator.yml` sets the image, mounts the site directory
  (`/site`), `logs/` and `build/` (seeds and ISO URLs now survive the container),
  the inventory and the vault password file. Navigator records every run in
  `logs/` (`ansible-navigator replay`). Plain `docker run` stays documented;
  `--network host` is not needed.
- **Keys in the site directory**: `keys/...`, referenced from the inventory as
  `"{{ inventory_dir }}/keys/..."`, so they work the same with and without the
  container. A key that is not found comes with that hint.
- Per-host ISOs are named `hvm-<host>.iso` (was `vme-stack-<host>-<seed hash>.iso`);
  the seed hash sits in `hvm-<host>.iso.seed` next to it, so an unchanged seed is
  still not rebuilt. A host that boots an older copy is caught by the install-id
  check.
- `media.yml` prints every host's ISO URL, also when nothing was built, and
  whether the ISO is on the deploy server (an installed host's ISO is removed
  after its install; `-e force_reinstall=true --limit <host>` builds it again, or
  `keep_host_iso: true` keeps it). Was: nothing for installed hosts.
- Fix: `media_server` read the deploy server's state wrongly where `systemctl`
  prints nothing (e.g. without systemd).

## [0.1.3] - 2026-10-11

- **Run logs**: every `ansible-playbook` run in the container writes its whole
  output to `/logs/<date>-<time>-<playbook>.log` when a writable `/logs` is
  mounted (`-v $PWD/logs:/logs`); without it the run says the log is lost.
- **Support bundle**: `-e VME_STACK_DEBUG=1` makes a run verbose and afterwards,
  also after a failure, collects logs and state of the controller, the deploy
  server, every HVM host and the Manager (API) into
  `/logs/vme-stack-support-<site>-<date>.tar.gz`, with every vault value, every
  secret field of the site file and password hashes replaced by `********`.
  `collect.yml` does the same on its own. Collecting changes nothing on the
  machines. See `ee/README.md` (Logs and support bundle).

## [0.1.2] - 2026-10-11

- **Site file change: SSH keys per login.** `access` is gone. The deploy server's
  login is `deploy_server.user` + `deploy_server.ssh_private_key`; the HVM hosts'
  is `hvm_admin_user` + `defaults.hvm_ssh_private_key` (both may name the same
  file). The jump host moves to `deploy_server.jump` and uses the deploy server's
  key. `ssh_keys` is replaced: the public key of `hvm_ssh_private_key` is now
  derived at preflight and installed for the admin user, so it always matches;
  `hvm_ssh_keys` only adds extra keys (e.g. administrators'). Old keys fail the
  schema check with the new form.
- `deploy_server.connection: local` is for Ansible installed on the deploy server
  itself; from the container always use `ssh` (the docs now say so).

## [0.1.1] - 2026-10-11

- **Site file change: secrets are plain Ansible values.** A secret field holds the
  value itself, the Ansible way: usually a quoted template referencing the vault,
  e.g. `hvm_admin_password: "{{ vault_hvm_admin_password }}"` (recommended), or a
  literal (works, not recommended). It used to hold the name of a vault variable,
  which did not tell a reader what was a literal. Preflight lists every secret
  that does not resolve (vault not loaded, variable or value missing).
- **Renamed keys** (old ones fail the schema check with the new form; see
  `sites/example/`):
  - the hosts' `admin_user`/`admin_password` -> `hvm_admin_user`/`hvm_admin_password`
    (in `defaults` and per host); the Manager's stay `vme_manager.admin_user`/
    `admin_password`
  - `bmc.credentials` -> `bmc.username` + `bmc.password`: each BMC its own login,
    or several servers sharing one vault variable
  - `vcenter.credentials` -> `vcenter.username` + `vcenter.password`
  - `vme_manager.admin_password`, `license_key`, `ssh_private_key`,
    `ssh_public_key` hold values (or vault references), no longer variable names
- Preflight: all hosts of a cluster need the same `hvm_admin_password` (as already
  the same `hvm_admin_user`). The Manager's cluster API takes one SSH login for
  all hosts, so different passwords used to fail the cluster step late in the run.

## [0.1.0] - 2026-10-11

First public release. From empty servers (or VMs) to a working HPE VM Essentials
environment, driven by one site file; tested end to end with VME 9.0.2 (8.1.1 also
supported) in a lab of Proxmox VMs, about 45 minutes from empty hosts to cluster.

- **Site file**: one `site.yml` per site, loaded as inventory and checked against a
  JSON schema and cross-field rules before anything runs; secrets only as vault
  variable names. Example sites: `ansible/examples/` (VMs, bare metal) and
  `sites/example/` (every setting).
- **Preflight** (`preflight.yml`, changes nothing): deploy server (sudo, packages,
  ISOs, space), SSH key, DNS and NTP from the deploy server, the Manager URL's DNS
  record on every site DNS server, BMCs' Redfish service, raw netplan through
  netplan's own parser.
- **HVM hosts**: unattended install from HPE's own HVM ISO; the seed is HPE's
  `/server/user-data` from that ISO plus our answers (network, disk, identity,
  proxy, timezone). One ISO per host, built and served by a deploy server (Ubuntu/
  Debian or RHEL family). Boot over Redfish (HPE iLO, Dell iDRAC; untested on real
  hardware) or by anyone else from the printed ISO URL (`platform: manual`).
- Network per host as a NIC layout (dedicated mgmt/compute bonds or one shared bond,
  matched by MAC, mgmt VLAN tagged or untagged) or raw netplan; disk as `auto`, a
  kernel name, installer match keys or a raw storage section.
- Re-runs are safe: installed hosts are skipped, foreign machines on a host's IP
  stop the run, a host's own running installer is recognised; `force_reinstall`
  with `--limit` reinstalls.
- **VME Manager**: installed with HPE's `hpe-vm --install` from the VM Essentials
  ISO (served from the mounted ISO), first-time setup through the API (trial or
  license key), optionally moved onto shared storage and made managed.
- **Manager objects**: groups, clouds (HVM private clouds; vCenter clouds with
  import of existing VMs) and HVM clusters with NFS datastores, found by name or
  created, never changed or deleted.
- **Container image** `ghcr.io/kosmolito/vme-stack-ee` (linux/amd64, linux/arm64)
  with everything the pipeline needs; hotfix mount for emergency code changes.
