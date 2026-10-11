# Changelog

Changes of vme-stack (the EE image `ghcr.io/kosmolito/vme-stack-ee`), newest first.
Versions are vme-stack versions (`ee/VERSION`), not VME versions; the VME versions a
release was tested with are in [`ee/README.md`](ee/README.md#versions).

Write changes under **Unreleased** as you go; `task release VERSION=X.Y.Z` turns
that section into the release's section (and refuses to release with it empty).

## [Unreleased]

- Preflight: all hosts of a cluster must name the same `admin_password` vault
  variable (as already for `admin_user`). The Manager's cluster API takes one SSH
  login for all hosts, so different passwords used to fail the cluster step late
  in the run. BMC credentials (`bmc.credentials`) stay per host.

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
