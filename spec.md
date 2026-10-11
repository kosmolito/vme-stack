# vme-stack — Project Spec

## Overview

`vme-stack` installs a complete HPE VM Essentials (VME) stack from empty machines with one command: HVM hosts first, then the VME Manager (Morpheus), then the hosts joined into a cluster. It is delivered as a repeatable service to customers, so it must be generic, versioned and driven by one input file per site.

**In scope**

- Unattended HVM host install (replaces the manual ISO + TUI setup)
- Targets: Dell (iDRAC) and HPE (iLO) bare metal over Redfish, and VMs with nested virtualization for labs
- VME Manager deployment and base configuration with Terraform
- Cluster creation and host join
- Post-install host config: updates, NTP, NIC bonding

**Goals**

- One input file per customer, schema-validated before anything runs
- Same code for every site; only the input file changes
- Re-runnable: done hosts are skipped, failed hosts retried
- Testable end to end in a nested lab in CI

**Non-goals (v1)**

- Firmware/BIOS lifecycle management
- Network switch configuration
- Day-2 operations (upgrades, scaling beyond adding hosts)
- HPE Compute Ops Management (COM) driver (possible later)

## Architecture

One linear pipeline; only the boot step is pluggable per platform. Each stage can also run alone.

1. **Preflight** — validate `site.yml` against the schema; check BMC/hypervisor reachability, credentials, ISO presence, DNS/NTP reachability.
2. **Media** — render per-host cloud-init seed; prepare the shared HVM boot ISO once; serve both over HTTP.
3. **Boot (driver)** — create or locate the machine, attach media, one-time boot from CD, power cycle.
4. **Wait** — poll until the host answers on SSH (timeout per host).
5. **Post-install** — NTP, timezone, NIC bond and address checks, media clean-up. No package changes: the installer's own update step (as in HPE's seed) is the only update.
6. **VME Manager** — Terraform deploys and configures the Manager.
7. **Cluster join** — create the HVM cluster if missing, add hosts via the VME Manager API/Terraform.

**Boot driver contract** — every driver is one Ansible role implementing the same interface:

| Driver | Target | Media attach | Notes |
| --- | --- | --- | --- |
| `redfish` | HPE iLO, Dell iDRAC (vendor detected at run time) | Redfish VirtualMedia from the ISO URL (iLO slot 2; iDRAC `VirtualMedia/1`, legacy `CD` path for iDRAC < 9 6.00) | Role `boot_redfish` -> vendored `baremetal_lifecycle`; iLO virtual media scripting needs an iLO Advanced license |
| `manual` | anything else: VMs (Proxmox, vSphere, libvirt), servers without a driver | Done outside the pipeline (Terraform or a person) from the ISO URL | Pipeline publishes the URL and waits for SSH |

**VMs are servers.** The pipeline never creates, deletes or configures VMs. A VM is a server that already exists and is booted from its ISO URL by something else; VM creation (lab: Terraform with bpg/proxmox, in the private lab repo) is a separate step. Driver inputs: host record from `site.yml`, `host_iso_url`. Drivers must be idempotent and never touch disks or BIOS beyond the one-time boot.

**Seed delivery**

- VMs: attach the per-host `CIDATA` seed ISO as a second CD-ROM.
- Bare metal: default to an HTTP seed (`ds=nocloud-net;s=http://<seed-server>/seeds/<host>/`). Fallback option `seed_mode: embedded` builds a per-host ISO with the seed baked in, for sites without install-time network.

## Repo layout

Product code lives in `vme-stack` (public). Site files never go into it: customer sites live in a separate private repo (`vme-stack-customers`), the maintainers' test lab (site file, Terraform for the lab VMs, lab helpers) in the private `vme-stack-lab`, checked out next to this repo.

```
vme-stack/
  README.md
  CLAUDE.md                  # conventions for Claude Code
  spec.md                    # this spec; Decisions log at the end
  ansible/                   # the Ansible project (the product)
    ansible.cfg
    deploy.yml               # whole pipeline: hvm_hosts -> vme_manager -> vme_cluster
    preflight.yml            # stage 1 alone (changes nothing)
    hvm_hosts.yml            # HVM hosts: media, boot, install, post-install
    media.yml                # build + publish per-host ISOs only
    media_server.yml         # nginx/xorriso on the deploy server
    vme_manager.yml          # VME Manager (hpe-vm --install, first-time setup)
    vme_cluster.yml          # groups, clouds (HVM, vCenter), clusters, datastores, Manager VM on shared storage
    group_vars/all.yml       # tuning defaults (timeouts, force_reinstall)
    plugins/
      inventory/vme_site.py  # site.yml as inventory + schema check
      filter/vme_site.py     # cross-field site rules (preflight)
    schemas/site.schema.json
    roles/
      preflight/  host_state/  seed/  media_server/  media/
      boot_manual/  boot_redfish/  baremetal_lifecycle/   # boot drivers (+ vendored Redfish role)
      wait_ssh/  postinstall/
      vme_manager_media/  vme_manager/  vme_manager_setup/  vme_cluster/
    examples/                # example sites (VMs, bare metal) with guides
    tests/                   # site rule cases, check_sites.py
  sites/example/             # reference site with every setting (other sites/* are gitignored)
  ee/                        # execution environment (ansible-builder), release to GHCR
  .github/workflows/         # ci.yml, ee-release.yml
  Taskfile.yml               # task check, task release
```

## Customer input file (site.yml)

One `site.yml` per site is the only thing that changes between customers. Secrets are referenced, never written inline. It is loaded as Ansible **inventory** (`-i site.yml`) by the `vme_site` inventory plugin, so `--limit <host>` works. Schema: `ansible/schemas/site.schema.json` (JSON Schema 2020-12). Bare-metal example: `ansible/examples/baremetal/site.yml`.

```yaml
site: acme-prod
version: 1                       # schema version

media:
  hvm_iso: /srv/vme-stack/src/HVM_Install_24.04_S5Q83-11056.iso   # on the deploy server
  seed_mode: embedded            # embedded (implemented) | http

network:                         # one mgmt network shared by all hosts
  domain: acme.local
  gateway: 10.0.0.1
  prefix: 24
  mgmt_vlan: 100                 # 0 = untagged
  dns: [10.0.0.10, 10.0.0.11]
  ntp: [10.0.0.10]
  timezone: Europe/Stockholm
  proxy: http://proxy.acme.local:3128   # optional
  bond_mode: active-backup       # active-backup | 802.3ad

deploy_server:                   # builds + serves the ISOs; probes run here; the EE usually runs here too
  name: deploy                   # inventory name (default)
  address: 10.0.0.5
  user: vmestack                 # passwordless sudo
  port: 8080                     # nginx; media URL = http://address:port unless media_url is set
  www_root: /srv/vme-stack/www   # default
  work_dir: /srv/vme-stack/work  # default

access:
  ssh_private_key: ~/.ssh/vme_stack     # controller side; relative = relative to site.yml
  jump: vmestack@10.0.0.4        # optional SSH jump host to reach the deploy server and hosts

defaults:                        # any host may override platform, admin_user, ssh_keys, boot_disk, os_updates
  platform: redfish              # redfish | manual
  admin_user: hvmadmin
  ssh_keys: ["ssh-ed25519 AAAA..."]
  boot_disk: auto                # auto (smallest disk) | installer match keys, e.g. { serial: "*S3EVNX0K*" }
  nic_layout: dedicated          # dedicated | shared
  os_updates: true

hosts:
  - name: hvm01
    ip: 10.0.0.21
    bmc: { address: 10.0.1.11, credentials: vault_ilo }   # vault variable name; bios_setup: true to opt in
    nics:
      mgmt: ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"]
      compute: ["aa:bb:cc:dd:ee:03", "aa:bb:cc:dd:ee:04"]
  - name: hvm09                  # e.g. a VM, or a server without a driver
    platform: manual
    ip: 10.0.0.41
    nics: { layout: shared, mgmt: ["52:54:00:71:00:01", "52:54:00:71:00:02"] }
  - name: hvm10                  # edge case: raw netplan + raw storage, used verbatim
    ip: 10.0.0.42
    netplan: { version: 2, ethernets: {...}, bonds: {...}, vlans: {...} }   # instead of nics
    hpe_vm: { mgmt_interface: bond0.100, compute_interface: bond1 }       # required with netplan
    storage: { layout: { name: lvm, match: { serial: "*S3EVNX0K*" } } } # instead of boot_disk
```

**Validation, in two steps**

1. *Schema* (inventory plugin, before any play): shapes, formats (IP, MAC, FQDN, host label, SSH key), enums, unknown keys rejected. Every error is listed at once and the run stops (`any_unparsed_is_failed`). Host names must be unique (the plugin needs that to build the inventory).
2. *Site rules* (preflight, over the whole file even with `--limit`): unique IPs and MACs (raw netplan: from `ethernets.*.match.macaddress`); raw netplan: `hpe_vm.mgmt_interface` defined, static (no DHCP), not a bridge, carries the host's `ip`, and `compute_interface` defined and not the parent of the mgmt VLAN; not both `boot_disk` and `storage`; host IPs not the gateway or the deploy server; IPs and gateway usable inside `gateway/prefix`; the platform has a driver role (`boot_<platform>`); `bmc` required for `redfish_*` and refused for `manual`; NIC layout rules (dedicated needs compute MACs, shared forbids them); `seed_mode` implemented.

Preflight then checks the environment (raw netplan parsed by netplan's own parser, `python3-netplan` on the deploy server; controller SSH key exists and is private; deploy server: passwordless sudo, apt, python3, stock ISO, free space for one ISO per targeted host; DNS answers from the deploy server) and lists every problem at once. NTP problems only warn.

**Flow per host**: `host_state` (installed? IP taken?) -> `seed` (render; hash = ISO name + cloud-init instance-id) -> `media` (xorriso on the deploy server, published at `<media_url>/isos/vme-stack-<host>-<hash>.iso`, URL also written to `build/<host>/iso_url`) -> `boot_<platform>` -> `wait_ssh` (on reinstall first waits for the old system to go down; after login, the instance-id must match this run's seed) -> `postinstall` (deletes the ISO from the media server). `media.yml` stops after `media`, for flows where something else boots the host (lab: `media.yml` -> `terraform apply` -> `hvm_hosts.yml`).

## Stage 1: HVM hosts (Ansible)

Each role does one job and is safe to re-run. A host that already answers SSH with the expected hostname and HVM version is skipped unless `force_reinstall: true`.

| Role | Does | Done when |
| --- | --- | --- |
| `preflight` | Schema check, reachability of BMCs/hypervisors, seed server, DNS, NTP; ISO exists; iLO license check | All checks pass or run stops with a clear list |
| `boot_iso` | Fetch HVM ISO; set GRUB `timeout=0` and `ds=nocloud` (or `nocloud-net` URL); rebuild with `xorriso` keeping BIOS+UEFI boot | Prepared ISO served once, checksum recorded |
| `mac_discovery` | Read NIC inventory via Redfish (Dell: `EthernetInterfaces`; HPE iLO 6/7: `NetworkAdapters/.../NetworkDeviceFunctions`; iLO 5: `BaseNetworkAdapters`) | `mgmt_macs` set per host |
| `seed` | Render `user-data` + `meta-data` from templates; build `CIDATA` ISO or HTTP seed dir | Seed served at `/seeds/<host>/` |
| `seed_server` | Run nginx container serving `/isos` and `/seeds` | HTTP 200 from a BMC-side check |
| `boot_<driver>` | Attach media, set one-time boot to CD, power cycle | Host is booting the installer |
| `wait_ssh` | Poll SSH with backoff; default timeout 45 min | SSH login works with deploy key |
| `postinstall` | timezone, NTP (timesyncd or chrony, as the image ships), verify bonds and mgmt address, remove the host ISO | Host passes health check |

**Seed (`user-data.j2`) must cover everything the TUI does today:**

- Hostname, FQDN, static IP, gateway, DNS, VLAN
- Netplan bond matched by MAC (not interface name)
- Boot disk selection (`auto` = smallest disk, or installer match keys: serial/model/vendor/id_path/ssd/size)
- Admin user + SSH keys, no password login
- Any HVM-specific first-boot settings (to confirm against HPE's reference template)

**Redfish notes**

- Insert media, then set boot override `Once` + `Cd` + `UEFI`, then `ForceRestart`.
- iLO virtual media scripting needs an iLO Advanced license.
- Write raw Redfish calls with `ansible.builtin.uri` behind the driver interface, so vendor quirks stay inside one role.

## Stage 2: VME Manager and cluster (Terraform)

Terraform owns the VME Manager and its configuration because these are long-lived resources with real state. Ansible calls Terraform (`cloud.terraform` / `community.general.terraform`) so the pipeline stays one command.

**Module `terraform/vme-manager`**

- Inputs generated from `site.yml`: Manager IP/FQDN, target host for the Manager VM, cluster name, network, credentials from Vault
- Deploys the VME Manager appliance onto the first HVM host
- Base config with the Morpheus provider: groups, cloud, cluster, networks, NTP/DNS settings
- Outputs: Manager URL, cluster ID

**Cluster join**

- Create the HVM cluster if missing, add every host from `site.yml`
- Prefer the Morpheus Terraform provider; fall back to the VME Manager API from Ansible where the provider lacks a resource

**State**

- One state per site, stored remotely (S3-compatible bucket or GitLab/Terraform Cloud backend), never in Git
- Workspace or key = `site` name

## Packaging and entry points

Everything runs from one container image so every site gets identical tooling.

**Execution environment (`ee/`)**, built with `ansible-builder`, contains:

- Ansible core + collections: `ansible.posix`, `community.general`, `cloud.terraform`; python `jsonschema`
- Terraform (pinned) + providers via a provider mirror
- `xorriso`, `genisoimage`, `jq`, `python3-jsonschema`
- Tagged per release: `ghcr.io/<org>/vme-stack-ee:<version>`

**Seed server**: stock `nginx` container started by `seed_server`, serving `/isos` and `/seeds` from a local volume.

**Commands**

```
# full pipeline
ansible-navigator run deploy.yml -i customers/acme/site.yml --vault-id acme@prompt

# single stages
ansible-navigator run playbooks/preflight.yml   -i site.yml
ansible-navigator run playbooks/hvm_hosts.yml   -i site.yml --limit hvm01
ansible-navigator run playbooks/vme_manager.yml -i site.yml
```

A thin `Makefile` wraps these (`make preflight SITE=acme`, `make deploy SITE=acme`). AWX/Semaphore is optional later and uses the same EE image.

## Non-functional requirements

- **Idempotent**: every role re-runnable; completed hosts skipped; `--limit` works per host.
- **Fail clearly**: preflight lists every problem at once; runtime errors name the host, stage and next action.
- **Secrets**: Ansible Vault per customer or an external store (HashiCorp Vault); no secrets in logs (`no_log` on credential tasks) or in Terraform state outputs.
- **Pinned versions**: HVM ISO checksum, EE image tag, collection and provider versions per release.
- **Parallel**: hosts provision in parallel (default 5 forks).
- **Logs**: each run writes a timestamped log + summary (host, stage, result, duration) to `runs/<site>/`.
- **Testing**:
  - `ansible-lint`, `yamllint`, `terraform fmt/validate`, schema tests on `examples/` in every PR
  - Molecule tests for `seed`, `boot_iso`, `preflight`
  - E2E: nested libvirt lab (1 Manager + 2 HVM) on a self-hosted runner, on merge to `main` and before each release
- **Releases**: SemVer tags; changelog; EE image built and pushed by `release.yml`.
- **Docs**: `README.md` (quick start), `docs/site-yml.md` (every field), `docs/drivers.md` (how to add a driver), `CLAUDE.md` (code conventions).

## Milestones and open questions

Build in this order; each milestone is usable on its own.

1. **M1 — Unattended seed**: one HVM installs from a hand-written seed with zero TUI input (libvirt lab).
2. **M2 — Lab pipeline**: `site.yml` + schema + preflight + `seed`, `media`, `media_server`, `boot_manual`, `wait_ssh`, `postinstall`; lab VMs from Terraform.
3. **M3 — Bare metal**: `boot_redfish_dell`, `boot_redfish_hpe`, `mac_discovery`; tested on one server of each vendor.
4. **M4 — VME Manager**: Terraform module + cluster join; full `deploy.yml` end to end.
5. **M5 — Productize**: EE image, CI e2e lab, release workflow, docs; first customer run.
6. **Later**: optional COM driver, AWX templates.

**Open questions**

- [ ] Which settings does the HVM TUI apply beyond standard Ubuntu autoinstall? (Compare with HPE's reference template.)
- [ ] Does the HVM installer accept `ds=nocloud-net` over HTTP, or must the seed be on media?
- [ ] Where does the VME Manager VM run: first HVM host, or existing infrastructure?
- [ ] Morpheus Terraform provider coverage for cluster create/host add in the target VME version?
- [ ] Remote Terraform state backend available at customer sites?
- [ ] Minimum supported iLO/iDRAC firmware versions?

## Decisions log

- **Manager install**: pre-built HPE image, installed via CLI from Ansible; Terraform only does base config after the API is up. First-admin/API-token bootstrap is an M4 spike.
- **Work order**: one section at a time, each working before the next. Current: HVM host deployment (M1/M2).
- **BMC drivers only attach media**: set one-time boot to virtual media and power cycle. Install, seed and post-install are identical for bare metal and VMs.
- **Seed delivery**: default is a per-host ISO with the seed embedded (one code path for VM and BMC). HTTP `nocloud-net` stays optional. The reference repo (jullienl/HPE-COM-baremetal) uses two media with `ds=nocloud`, which also works.
- **Network**: follow the official HPE guide (Installing HVM OS on host servers): Linux/netplan bond (active-backup) + tagged VLAN carrying the static IP, set in the seed. Reference repo instead uses `mgmt0` + an OVS bond after cluster join and warns a pre-built bond breaks `hpe-vm`. Verify in the first lab run; if it breaks, switch to the OVS design (bond becomes a post-join stage).
- **Official guide corrections**: NTP via `systemd-timesyncd` (not chrony); packages come from an HPE-curated repo; boot menu entry is "HVM Install 24.04".
- **Unverified (check in M1)**: whether the ISO needs `autoinstall` on the kernel cmdline to skip the confirm prompt; IOMMU/hugepage GRUB options (reference repo adds them, official TUI flow doesn't); whether `identity` can be omitted when `user-data.users` is set.
- **M1 verified (2026-10-08, lab VM)**: stock ISO (Ubuntu 24.04.2) ships `/server/user-data` as a partly interactive autoinstall (`interactive-sections: storage, identity, network, proxy`; `autoinstall ds=nocloud;s=/cdrom/server/` already on the kernel line). We replace `/server/{user-data,meta-data}` and set GRUB `timeout=0` with `xorriso -boot_image any replay`; BIOS+UEFI boot records survive. Resulting host: netplan bond0 (active-backup, 2 members by MAC) + `bond0.9` static IP, LVM root grown to full disk, `hpe-vm 1.0.14-1` installed, IOMMU set, HPE apt repo set, hostname/key correct. Install took ~20 min. The official-guide bond approach (Linux bond in the seed) installs fine; whether `hpe-vm`/cluster join accepts it is still open (M4).
- **Re-runs (verified 2026-10-08)**: `host_state` role probes the host first. Installed host with the expected hostname -> install stages skipped (re-run 11 s, second re-run 0 changes). Something else answering on the IP -> run stops with an IP-conflict message. `force_reinstall=true` is refused without `--limit`. A forced reinstall of a lab host rebuilt the host end to end with trunk NICs.
- **Installer downloads updates when it has network**: subiquity's postinstall `run_unattended_upgrades` step fetched ~1.2 GB from the internet and took the install from ~20 to ~30 min. The stock HPE seed does not disable it. The live installer also runs its own sshd, so `wait_ssh` waits for a successful key login (full timeout), not just a banner. **Decided: switched off** (superseded 2026-10-09, see "Packages exactly as HPE ships them"). The seed sets `apt.disable_suites: [security, updates]`, so the step has nothing to fetch. Verified: step took 2 s, the guest received ~7 MB in total during the whole install (was ~1.2 GB), and the full forced reinstall (ISO build + install + checks) took ~6 min instead of ~30. Updates are applied later from the HPE repo that HPE's runcmd configures.
- **Timezone**: per-site variable (`timezone`), seeded at install and enforced in postinstall. Lab uses `Europe/Stockholm`.
- **How `hpe-vm` treats our network (read from /opt/hpe-vm/scripts, hpe-vm 1.0.14-1)**: cluster join runs `build-ovs.sh <mgmt-if> <compute-if>` -> `build-ovs.py`, which accepts an ethernet, VLAN **or bond** as mgmt interface, rejects DHCP on it, moves its IP/routes/DNS onto an OVS bridge `mgmt` with the interface as a port, backs up all netplan files to `mvmbackup-<ts>/`, writes `01-base.yaml` + `60-mvm-mgmt.yaml` (+ `61-mvm-compute.yaml` for a `cmpt` bridge), then `netplan apply`. Dry run against our netplan:
  - `-m bond0.9`: clean. Linux bond0 + VLAN stay; IP moves to OVS bridge `mgmt` with port `bond0.9`. The netplan-bond-in-seed decision holds.
  - `-m bond0.9 -c bond0`: bond0 becomes a port of OVS bridge `cmpt` while its VLAN child is a port of `mgmt`. netplan accepts it, but the VLAN child very likely stops receiving once its parent is an OVS port (hypothesis, not applied). Probably the "breaks hpe-vm" case the reference repo hit. **Rule until proven otherwise: compute must not be the parent of the mgmt VLAN.**
  - `prepare-kvm.sh` also edits sshd (`PermitRootLogin prohibit-password`) and kvm modprobe options; expect that on joined hosts.
- **NIC layouts (decided + verified 2026-10-08)**: per host `nics.layout`:
  - `dedicated` (default): `nics.mgmt` MACs -> bond0 (IP on `bond0.<mgmt_vlan>`, or bond0 if vlan 0); `nics.compute` MACs -> bond1, no IP. Cluster join should pass `-m bond0.<vlan> -c bond1`. Verified: 4-NIC install, then HPE `build-ovs.sh bond0.9 bond1` gave OVS `mgmt` (port bond0.9, IP + route) and `cmpt` (port bond1); host reachable, gateway reachable.
  - `shared`: `nics.mgmt` MACs only -> bond0 with the IP **untagged**; the switch native VLAN must be the mgmt VLAN (site requirement for the customer network team). Cluster join passes `-m bond0` only. Verified: install with Proxmox `tag=9` as native VLAN, then `build-ovs.sh bond0` gave OVS `mgmt` with port bond0 carrying the IP; host and gateway reachable.
  - Rejected: compute = parent of a tagged mgmt VLAN (`-m bond0.9 -c bond0`); not tested, excluded by the layout rules.
  - Rules enforced in `host_state` until the schema exists: dedicated needs mgmt + compute MACs, shared forbids compute, no MAC twice.
  - After `build-ovs`, the host's mgmt MAC changes (bridge internal port); one test saw it unreachable from the lab hypervisor for under a minute (likely stale ARP, unverified).
  - A lab-only playbook (`hpe_vm_ovs.yml`, in the lab repo) runs HPE's step and checks reachability.
- **OS updates (superseded 2026-10-09)**: `postinstall` used to run `apt upgrade` from the HPE repo plus a reboot on a pending kernel (`needrestart`, since the HPE image has no `update-notifier-common`). Removed; see "Packages exactly as HPE ships them".
- **NTP check is a warning (decided 2026-10-09)**: postinstall waits up to 3 min for timesyncd, then prints a warning instead of failing. Reason: the lab's NTP servers were unsynchronised (one on its local clock, ~70 s slow; one ~160 s fast). timesyncd rejects both ("too large root distance"), so hosts stay unsynchronised until the NTP servers are fixed; that is the site's problem, not a failed install.
- **site.yml schema (decided + verified 2026-10-09)**:
  - Loaded as inventory by a repo inventory plugin (`vme_site`): `-i site.yml`, not `-e @site.yml`, because hosts created with `add_host` are invisible to `--limit` (tested).
  - JSON Schema (`schemas/site.schema.json`, python `jsonschema` on the controller) for shape; a filter plugin (`vme_site_errors`) for cross-field rules, called by the `preflight` role.
  - NICs per host as `nics: {layout, mgmt, compute}` (replaces the spec's `mgmt_macs` + `network.bond.members`); MACs required until `mac_discovery` (M3).
  - Files stay in `ansible/` (schemas/, plugins/, examples/); site files live in `sites/<site>/site.yml` (since the public/private split: never in this repo). Tuning defaults (timeouts, `force_reinstall`) moved to `ansible/group_vars/all.yml`.
  - Verified with the first (Proxmox-driver) version: forced reinstall of a lab host from the site file (36 min incl. ~1 GB of OS updates and the reboot into the new kernel: the first full verification of `os_updates` on a fresh host); seed byte-identical to the old inventory's; preflight negative tests list every problem.
- **Everything runs in the EE (decided 2026-10-09)**: all Ansible dependencies (collections, python `jsonschema`, xorriso, Terraform) will be baked into the EE, so roles may rely on them; "avoid a dependency" is no longer a design goal.
- **VMs are servers; no hypervisor code in the pipeline (decided 2026-10-09)**: Proxmox VMs are treated like bare metal. VM creation is a separate step (Terraform, manual or Ansible); the `boot_proxmox` driver and the site file's `hypervisors`/`vm` blocks are gone. Platforms: `redfish_hpe`, `redfish_dell` (M3), `manual` (pipeline publishes the ISO URL and waits). Lab VMs: Terraform (bpg/proxmox, lab repo), host names and MACs read from the site file, ISO URLs from `build/<host>/iso_url`; VMID-range/name-prefix guardrails are Terraform preconditions.
- **Deploy server builds and serves the media (decided 2026-10-09)**: one machine (client or managed server, where the EE runs) builds the per-host ISOs with xorriso and serves them with nginx (`media_server` role); BMCs (Redfish InsertMedia) and hypervisors (Proxmox download-url) fetch them by URL. It is also the probe point for SSH/DNS/NTP. The stock HVM ISO must be on it (`media.hvm_iso`). Lab: a deploy VM created by the lab's Terraform; a lab playbook copies the stock ISO from its CD drive. `boot_iso` renamed `media` (it was not a driver).
- **Install proof for manual boots (decided + verified 2026-10-09)**: meta-data's instance-id is `<host>-<seed hash>`. The installed system gets cloud-init datasource "None" (`iid-datasource-none`), so the seed's late-commands copy the live installer's instance-id to `/etc/vme-stack/install-id`; `wait_ssh` checks it after an install. Verified: the first attempt (checking cloud-init's own instance-id) failed exactly as designed for a mismatch.
- **host_state probe bug (fixed 2026-10-09)**: `failed_when: false` on the SSH banner probe also reset `failed`, so a timeout looked like a found banner; now `ignore_errors` + `is succeeded`.
- **OS updates need two passes (superseded 2026-10-09)**: seen once with our `apt upgrade` (kernel 117, then 139 in the next run); not reproduced; code removed with the update step.
- **HPE repo holds back systemd (decided 2026-10-09: keep held back)**: `zion-os-updates-prod` has systemd 255.4-1ubuntu8.17 without a matching `systemd-timesyncd`; upgrading would remove timesyncd and install chrony, so `apt upgrade` keeps 14 packages (systemd family, libheif) back. On a fresh install the whole systemd family stays at the ISO's version (255.4-1ubuntu8.10; repo has systemd 8.17 but timesyncd only 8.15), 16 packages held back. Decided: keep timesyncd. vme-stack no longer runs `apt upgrade`, but anyone who later does will hit this (it is HPE's repo, not our change).
- **Packages exactly as HPE ships them (decided 2026-10-09)**: no unofficial packages and no package changes of our own. The seed's `apt` section is HPE's stock one again (`disable_suites` removed), so the installer's update step runs as in a manual install. It downloads from HPE's own Pulp server (`pulp-server.glipdev-hpe.com/pulp/content/zion-ubuntu-external`, set up by HPE's installer environment and removed by HPE's runcmd), not from Ubuntu's archive; it needs internet to that server. Verified 2026-10-09: forced reinstall 20 min end to end, kernel 6.8.0-110, systemd and timesyncd both 255.4-1ubuntu8.14 (consistent, nothing held back), hpe-vm 1.0.14-1; plain re-run 0 changes in 3.5 min; `terraform plan` clean; `postinstall` no longer runs `apt upgrade` or reboots (`os_updates` removed from schema, plugin and site files). Diff of our rendered seed against HPE's `/server/user-data`: only the four interactive sections answered (network, storage, identity/SSH, proxy if set), the timezone, and the install-id late-command.
- **Raw netplan and storage for edge cases (decided 2026-10-10)**: a host's network is either a `nics` layout (common cases, generated) or raw `netplan` + `hpe_vm` (anything else: LACP, MTU, extra VLANs, routes), and its disk either `boot_disk` or a raw autoinstall `storage` section (RAID, partitioning). Raw blocks go into the seed verbatim (no templating; YAML anchors for repetition). `hpe_vm.mgmt_interface`/`compute_interface` say what HPE's cluster join (`build-ovs.sh -m/-c`) and our checks use; with `nics` they are derived (`bond0[.vlan]`/`bond1`). Post-install: bond checks only for `nics`, the mgmt-address check on `mgmt_interface` for both, gateway ping warns only. Lab example: hvm02: VLAN 10 on the compute bond (layouts cannot express it) + raw storage (LVM on `/dev/sda`). Verified 2026-10-10: seed blocks byte-equal to the site file; preflight's netplan parser check reports e.g. `bond1: interface 'nosuchnic' is not defined`; install 8.5 min; both bonds, VLAN 10 and LVM on the whole disk as written; two-host re-runs 0 changes.
  - First attempt used MTU 9000 on the compute bond: the lab hypervisor's bridge is MTU 1500, so the virtio NICs cap at 1500 and the kernel refused them as bond members; the install and our checks still passed. Added a generic post-install check: any interface systemd-networkd marks `failed` fails the run (verified on that state). Hardware limits like max MTU cannot be checked before install.
  - In two-host runs (strategy free) a host's mgmt-address check saw the other host's `ansible_facts` (once each way; not reproducible in a minimal playbook). Post-install now reads hostname and addresses on the host itself instead of from facts.
- **build-ovs and failover (verified 2026-10-10)**: HPE's `build-ovs.sh` (`tests/hpe_vm_ovs.yml`, interfaces from `mgmt_interface`/`compute_interface`) on both lab hosts: nics-layout hvm01 and raw-netplan hvm02 each got OVS `mgmt` (port `bond0.9`, IP + default route) and `cmpt` (port `bond1`), gateway reachable. hvm02's `bond1.10` stays up after `bond1` becomes an OVS port; whether it still carries traffic is untested (no VLAN 10 peer). Bond failover on hvm01 after build-ovs: Proxmox `link_down` on the active NIC (cable pull) -> `mgmt1` took over, 12 of 250 pings lost at 0.2 s (~2.4 s), no failback on link return (active-backup, no primary), `terraform plan` clean afterwards. Both lab hosts are now in the post-build-ovs state: reinstall them before a real cluster join.
- **Redfish driver from ansible-baremetal-lifecycle (decided 2026-10-10)**: the user's existing role (raw Redfish via `uri`, HPE iLO + Dell iDRAC, vendor detection, session cleanup, iDRAC legacy/iDRAC10 paths) is **vendored** into `ansible/roles/baremetal_lifecycle` (its repo is private, so pulling it at install/EE-build time would need credentials everywhere). One local change: the ISO URL check uses `HEAD` instead of `GET` (GET downloaded the whole ISO per host). `boot_redfish` maps the site file onto it: `hosted_iso_file` = per-host ISO URL, `srv_ip` = `bmc.address`, credentials from the vault variable named in `bmc.credentials`; eject + insert + boot once from CD + power on/ForceRestart. **BIOS setup** (UEFI, Secure Boot off) is opt-in per host (`bmc.bios_setup: true`), default off. **Platforms**: `redfish_hpe`/`redfish_dell` merged into one `redfish` (vendor detected at run time). The role uses `pause`, so `hvm_hosts.yml` is now two plays: build media + boot (linear), then wait + post-install (free). Preflight checks the credentials variable and that the BMC's Redfish service root answers from the controller. Not yet tested against real hardware (no BMC in the lab); verified: schema/rules, preflight negative tests, unchanged lab flow (0 changes).
- **VME Manager deployment (decided 2026-10-10, M4 step 1)**: HPE's own non-interactive installer, `hpe-vm --install` (in `hpe-vm` 1.0.14-1: address, netmask, gateway, DNS, hostname, appliance URL, admin user/password, qcow image URL, size S/M/L, `-i`/`-c` interfaces), run by Ansible on `vme_manager.host` (a chosen HVM host; the Manager runs inside the cluster it manages). `hpe-vm` also builds the OVS mgmt bridge on that host (`-i mgmt_interface`); see the next entry for why not `-c`. The Manager image comes from HPE's VM Essentials software ISO (`media.vme_iso`, v8.1.1: `hpe-vm-essentials-8.1.1-1.qcow2.gz`, `hpe-vm_1.0.14-1_amd64.deb`, README, SHA256.txt): `vme_manager_media` serves it from the mounted ISO (see below). Size is a site setting (`vme_manager.size`, default S); the role checks the host has the size's RAM + 4 GB. Admin password: a vault variable named in the site file; vault `sites/<site>/group_vars/all/vault.yml` (generated, encrypted; vault password in `sites/<site>/.vault_pass`, gitignored). Same Ansible project (`vme_manager.yml` next to `hvm_hosts.yml`). Steps 2 (first-time setup/license via API) and 3 (Terraform base config + cluster join) follow once step 1 works. Lab: Manager on hvm01 (32 GB), no DNS record, appliance URL `https://<manager ip>`.
- **hpe-vm --install behaviour (found 2026-10-10)**: options must be given as `--option value` (`--option=value` is rejected: "Invalid argument"). With `-c` it requires `-v`, and then attaches the Manager VM's only NIC to the **compute** OVS bridge tagged with the `-v` VLAN; with the Manager IP on the mgmt VLAN that VM is unreachable. **Decided: no `-c`/`-v` at Manager install** (Manager on the mgmt bridge); the compute bridge and VM VLANs (`network.compute_vlans`, lab: [10]) are set at cluster creation. hpe-vm creates a libvirt storage pool `morph`, downloads the image by URL (6.8 GB in ~50 s from the deploy server) and boots the VM named after `vme_manager.hostname`. It runs as a transient systemd unit under `script(1)` (root-only log `/var/log/vme-stack-hpe-vm-install.log`), independent of the SSH session.
- **VME software ISO has a file > 4 GiB (2026-10-10)**: `hpe-vm-essentials-8.1.1-1.qcow2.gz` is 6,825,927,763 bytes; xorriso lists and extracts it as 2,530,960,467 (wrapped at 4 GiB) and the result fails HPE's SHA256 and `gzip -t`. A read-only loop mount (UDF view) gives the full file, which matches `SHA256.txt`. **Decided (user, 2026-10-10): serve the image straight from the mounted ISO.** The deploy server keeps the VME ISO loop-mounted read-only at `<www_root>/vme-iso` (`/etc/fstab`, `ro,loop,nofail`, mounted as UDF), nginx serves it at `<media_url>/vme-iso/`, and `hpe-vm --install` downloads the qcow2.gz from there; nothing is copied (saves 6.8 GB). `SHA256.txt` is checked once per (re)mount; another ISO path in the site file remounts. Verified: mount survives a deploy server reboot, re-runs 0 changes, download from hvm01 6.8 GB in 20 s with HPE's checksum.
- **M4 step 1 verified (2026-10-10)**: on a freshly installed lab hvm01 (32 GB), `vme_manager.yml` published the image, ran `hpe-vm --install` (size S, no `-c`/`-v`): download 45 s, first boot to "Installation Complete" 24 min, 25.5 min end to end. `https://<manager>/ping` -> `MORPHEUS PING`, `/` -> login page, `/api/setup/check` -> `setupNeeded: true` (unauthenticated; the hook for step 2's first-time setup). Re-run: Manager answers, install skipped, 0 changes.
- **M4 step 2: first-time setup via API (decided + verified 2026-10-10)**: `vme_manager_setup` calls `POST /api/setup/init` (fields from morpheus-cli's `setup init`: accountName, username, password, confirmPassword, email, firstName, lastName, applianceName, applianceUrl, backups, monitoring, logs, hubMode, licenseKey) only while `GET /api/setup/check` reports `setupNeeded`, then proves the admin with an OAuth password-grant login (`/oauth/token`, client `morph-api`) and reads `/api/license`. Defaults: tenant = site name, the Manager admin = `vme_manager.admin_user` with the same vault password as the VM admin, email `<admin_user>@<domain>`, backups off, monitoring/logs on, Morpheus Hub skipped. **License**: optional vault variable `vme_manager.license_key`; without it the Manager starts a trial on its own (lab: tier `core`, 60 days 2026-10-10 to 2026-12-09, hard limit). Verified in the lab; re-run skips setup.
- **M4 step 3: HVM cluster via the Manager API (decided 2026-10-10)**: **all via Ansible + Manager API** (the morpheus Terraform provider 0.14.1 has group/standard_cloud/credential/key_pair resources but no HVM cluster resource), so Terraform is not used for the Manager. `vme_cluster.yml` / role `vme_cluster`: find-or-create by name the group, a private cloud (`standard`), the Manager's SSH key pair, then `POST /api/clusters` (type `mvm-cluster`, layout `mvm-1.2-ubuntu-24.04-std-morpheus-amd64` = "HVM 1.2 Cluster on HVM/Ubuntu 24.04") and wait for status `ok`. Site: `vme_cluster` (name/group/cloud default to the site name, `hosts` default all, key vault variables); preflight requires identical mgmt/compute interface names and admin user on all members (HPE requirement), `compute_vlans` when there is a compute interface, and `admin_password`.
  - API details found by trial: `server.sshHosts` is a list of objects `{ip, name}` (plain strings -> HTTP 500 `No such property: ip`); `server.plan` is required (`manual-default` for existing hosts); mgmt interface goes in `server.network.name`, compute interface/VLANs/key in `server.config` (`computeInterfaceName`, `computeVlans` comma list, `provisionKey` = key pair id).
  - **Host SSH: password required (decided).** The Manager's pre-check only opens port 22 and closes it without a password ("kex_exchange_identification: Connection closed"), then fails "Host version null does not match layout version 24.04"; HPE's docs also ask for user + password. Decided: the hosts' admin user gets a generated vault password (`admin_password`, set in post-install; sshd drop-in allows password login for that user only), and the Manager also gets its own key pair (generated per site, RSA/PEM, public key added to the hosts).
  - **Verified 2026-10-10**: a lab cluster (group and cloud named after the site) with hvm01 (runs the Manager) and hvm02 reached status `ok` ("cluster provisioning success") 4 min 48 s after the request; the Manager built the OVS `mgmt`/`cmpt` bridges on hvm02 itself and inventories both hypervisors. Re-run: group/cloud/key pair/cluster found, nothing created, 0 changes.
  - ansible-core 2.21 requires boolean `when:` results (`when: <string var>` fails, hidden by `no_log`).
- **Deploy server connection (decided 2026-10-10)**: `deploy_server.connection: ssh | local` (default ssh). `local`: the playbook runs on the deploy server itself (Ansible installed there); the inventory plugin sets `ansible_connection: local`, `user` is not needed, the playbook's user needs passwordless sudo. `address` keeps meaning the address hosts and BMCs fetch media from (media URL). In an EE container on the deploy server use `ssh` to the server's own address (`local` would be the container). Ownership of media dirs uses the real login user (`id -un`). `ssh` verified unchanged; `local` not yet run in the lab.
- **Source ISOs stay on the deploy server (decided 2026-10-10)**: `media.hvm_iso` and `media.vme_iso` are absolute paths on the deploy server, used where they are (no copying from the controller, no `iso_location` option). Expected setup: the deploy server is also the machine running the playbook/EE, so paths are simply local paths; whoever prepares it puts the two ISOs there (a permanent location, not `/tmp`: it is cleaned at reboot and the VME ISO's fstab mount would then fail). Preflight reports a missing ISO. Optional checksums for the ISOs may come later.
- **deploy.yml (2026-10-10)**: one entry point that imports `hvm_hosts.yml`, `vme_manager.yml`, `vme_cluster.yml`; preflight runs once per run (later imports end that play when `vme_preflight_passed`), the cluster stage is skipped without `vme_cluster`. Verified on the built lab: 75 s, nothing reinstalled, 0 changes apart from the NTP switch. **Full run from empty hosts verified 2026-10-10**: both lab hosts wiped (Terraform `-replace`), `deploy.yml -e force_reinstall=true --limit hvm01,hvm02` rebuilt hosts, Manager (setup + fresh trial) and cluster (2 hosts, ok) in 43 min 23 s; Terraform cleanup then `plan` clean; plain re-run 76 s, 0 changes.
- **Shared storage: NFS datastores (decided + verified 2026-10-10)**: `vme_cluster.datastores: [{name, type: nfs, host, path, version 3|4, default}]`, added through `POST /api/clusters/<id>/datastores` (type `libvirt-netfs-nfs`, config `sourceHostname`/`sourceDirPath`/`sourceVersion`, `defaultStore` = image target) and waited for `online`. GFS2 (type `libvirt-dir-gfs2`, needs the same block device on all hosts via iSCSI/FC + multipath, and fencing for dlm) comes later. Other types offered: Directory Pool, 3PAR, HPE Alletra. Lab: a lab playbook exports a second disk of the deploy VM over NFS (mgmt subnet, `no_root_squash`); both hosts mount it (NFS 4) as libvirt pool `lab-nfs`. The Manager itself installed `nfs-common` on the hosts during cluster setup.
- **Manager VM onto shared storage (decided + verified 2026-10-10)**: `vme_manager.datastore` names a cluster datastore; the cluster role moves the Manager's root volume there with the Manager's own server reconfigure (`PUT /api/servers/<id>/resize`, same plan, volume `datastoreId`), as in the UI's "Reconfigure server". Verified live, no downtime: copy ~5 min (written as a raw file, 100 GB virtual / 41 GB used), then the running VM and its persistent definition point to the NFS disk; re-run skips. The Manager deleted the local disk despite `deleteOriginalVolumes: false`.
- **Manager restart / HA (found 2026-10-10)**: hpe-vm defines the Manager VM with libvirt autostart **off**. The HVM cluster runs Pacemaker/corosync (2 nodes, quorum) with only a `dlm` clone (stopped: no STONITH); nothing restarts the Manager elsewhere, and the Manager sees its own VM as `kvmUnmanaged`. HPE's official docs (hpevm-docs) had nothing on Manager HA; the HPE community describes failover as: disk on shared storage, "Convert to Managed", a heartbeat datastore, "Automatically power on VMs" in cloud/cluster, placement auto/failover (community posts, partly HPE employees, marked as personal opinions). **Decided (user, 2026-10-10): no HA configuration without official documentation.** Autostart is a site setting `vme_manager.autostart` (default false, HPE's default; enforced either way; do not combine with HA). The Manager VM **is** converted to managed (`PUT /api/servers/<id>/make-managed`, VM's admin user/password, cluster group, no agent): verified, the server becomes `morpheusVm` with an instance named after the Manager (type `mvm`); re-run skips.
- **Execution environment (decided + verified 2026-10-10)**: `ee/` builds `vme-stack-ee` with **ansible-builder** (v3) on UBI 9 / Python 3.12: ansible-core 2.21.5, ansible-runner, jsonschema, passlib, openssh-clients; no collections (the pipeline only uses `ansible.builtin`). **Code baked in** (`/opt/vme-stack/code`, from `git archive HEAD` so `build/` never gets in); site data mounted (`/site`). **Tags are vme-stack SemVer** (`ee/VERSION`, 0.1.0), not VME versions; tested VME versions in label `io.vme-stack.tested-with` and the README table. **Hotfix rule** (user's design): mount `/vme-stack-hotfix`; empty -> image code copied into it and used; with content -> used as is; not mounted -> image code. Entrypoint set via `options.container_init` (an `ENTRYPOINT` in build steps is overridden by builder). Verified: hotfix rule in 4 steps, preflight and `deploy.yml` run from the container against the lab (88 s, 0 changes). Release: `.github/workflows/ee-release.yml` on tags `vX.Y.Z` (must match `ee/VERSION`): build with ansible-builder, smoke test (tools, libs, example site through the schema plugin, VERSION), push `ghcr.io/kosmolito/vme-stack-ee:X.Y.Z` and `:latest` with `GITHUB_TOKEN`; the image's `org.opencontainers.image.source` label links the GHCR package to the repo. Verified locally (build, smoke test, actionlint) and on GitHub (2026-10-11): manual run passed; tag `v0.1.0` released `ghcr.io/kosmolito/vme-stack-ee:0.1.0` and `:latest`. Trigger only on `v[0-9]+.[0-9]+.[0-9]+` (a mistyped `v.0.1.0` had started a run and was stopped by the VERSION check). **Multi-arch from 0.1.1 (decided 2026-10-11)**: `linux/amd64` + `linux/arm64` (Apple Silicon clients), built with buildx + QEMU on the amd64 runner after the amd64 smoke test; manual runs build both without pushing (`PUSH=false`); tag runs push and run the arm64 variant under QEMU. `build.sh` uses `ansible-builder create` + `docker build`/`buildx build`. On a client (macOS): no `--network host`, `deploy_server.connection: ssh`. Locally verified: both build paths (amd64), smoke test; arm64 only on GitHub (no emulation in the sandbox). Base switched to **ubi9/ubi-minimal** (microdnf, `python3.12` + `python3.12-pip` from UBI): 1.65 GB -> 415 MB; same checks passed (hotfix rule, `deploy.yml` from the container, 91 s, 0 changes).
- **Deploy server: Debian/Ubuntu or RHEL family (decided 2026-10-11)**: `media_server` detects apt or dnf (nginx, xorriso; same package names) and uses nginx `conf.d/` on both (the old Debian-only `sites-enabled/vme-stack.conf` is removed). **SELinux: switched to permissive** when enforcing (`setenforce 0` + `SELINUX=permissive`; user's decision: SELinux off on the deploy server; permissive instead of disabled because disabling needs a reboot and a kernel argument on RHEL 9). **Firewall**: an active firewalld or ufw gets the media port opened. Preflight accepts apt or dnf. Verified on the Ubuntu lab (migration to conf.d, media 200, re-run 0 changes) and on **AlmaLinux 9.8** (2026-10-11; a lab test VM; SELinux enforcing and firewalld active at the start): dnf install of nginx/xorriso, SELinux -> permissive (also in the config), firewalld port 8080/tcp, nginx `conf.d`, per-host ISO built and served (HTTP 200 from hvm02), VME ISO loop-mounted via fstab (UDF) and the 6.8 GB image served (HTTP 200 from hvm01); after a reboot all still in place and a re-run made 0 changes. **Found**: preflight's raw-netplan syntax check needs `python3-netplan` on the deploy server (Ubuntu has it, RHEL family does not): without it the check is skipped with a warning; the other netplan rules still apply.
- **Folder rename (decided 2026-10-11)**: `01-hvm-hosts/` -> `ansible/`. It holds the whole Ansible project (hosts, deploy server, VME Manager, cluster), not only HVM hosts; the numbered per-section folders of the early plan were dropped. Earlier entries in this log that name `01-hvm-hosts` refer to the same folder. Inside the EE the code stays at `/opt/vme-stack/code`.
- **CI (decided 2026-10-11)**: `.github/workflows/ci.yml` on pull requests and pushes to `main`, two jobs. **lint**: ansible-lint profile **production** (`.ansible-lint`; only `var-naming[no-role-prefix]` skipped: facts deliberately shared between roles, e.g. `install_now`, `host_iso_url`; vendored `baremetal_lifecycle` excluded, linted in its own repo), yamllint (`.yamllint`: lines <= 160, no `---`, one space in braces), ruff check + format (`ruff.toml`), shellcheck, actionlint, `terraform fmt`/`validate` (lab; in the lab repo since the public/private split). **site-tests**: `ansible/tests/check_sites.py` checks every site file (schema from the inventory plugin, rules from the filter plugin, no vault needed) and 26 negative cases in `ansible/tests/site_cases.yml` (each must fail with its message), plus syntax of all playbooks. Tools pinned in `requirements-dev.txt`. Lint fixes changed behaviour nowhere: task names (template at the end), `set -o pipefail` with bash (guards where a failing pipe part is expected), handlers for timesyncd/sshd/exportfs (flushed where order matters), systemd module instead of `systemctl`. Verified in the lab: no-op `deploy.yml` 0 changes, handlers fired correctly on hvm02, NFS playbook 0 changes; a mutation (one rule disabled) made exactly its case fail.
- **Untagged mgmt + boot_disk match keys (decided and verified 2026-10-11)**: example sites for both scenarios in `ansible/examples/` (`vm/`: platform manual, one vNIC per role, mgmt untagged; `baremetal/`: platform redfish, iLO + iDRAC), each with a `vault.example.yml` kept outside `group_vars/` (a template there would be loaded). `boot_disk` is now `auto` (smallest disk) or the installer's match keys (`serial`, `model`, `vendor`, `id_path`, `ssd`, `size`; globs on udev ID_SERIAL/ID_MODEL/ID_VENDOR/ID_PATH), passed as the storage layout's `match`. By-id paths are rejected: read from subiquity 6405 on the HVM ISO, `match: path` compares the kernel name (`/dev/sda`) only. `serial` is ID_SERIAL = a `/dev/disk/by-id/` name without its bus prefix; for SCSI/SAS and RAID logical drives that comes from VPD page 0x83 (WWN-like), not the label serial (Proxmox: `device_id=drive-scsi0`, the `serial=` only shows up as `scsi-S...`). First lab attempt with the label serial failed in the installer: "Failed to find matching device for {'serial': '*VMELAB-OS-03*'}".
  - Verified on a fresh lab VM hvm03: dedicated layout, `mgmt_vlan: 0`, one NIC per role (bonds with one member), 64 GB `scsi0` + 16 GB decoy `scsi1`, `boot_disk: {serial: "*drive-scsi0*"}`. Install + post-install 15 min; LVM root on the 64 GB disk, decoy untouched; IP untagged on `bond0`; HPE `build-ovs.sh bond0 bond1` gave OVS `mgmt` (port bond0, IP, default route) and `cmpt` (port bond1), gateway reachable.
  - Found: a lab address in use by an unknown machine (no ping reply, answers SSH); host_state's guard caught it. The same guard also stops a run started while the host's live installer is already up (it runs sshd on the seed's IP, our key is refused): run `hvm_hosts.yml` before the host boots its ISO, or with `-e force_reinstall=true --limit <host>`. Fixed below.
- **Recognising our own running installer (decided and verified 2026-10-11)**: the seed's top-level cloud-config (live session only; `autoinstall:` covers the installed system) adds a user `vme-stack-probe` (shell /bin/sh, locked password, our keys); `users: [default, ...]` keeps HPE's live user `installer` as shipped. `installer` cannot be used: its shell `/usr/bin/subiquity-shell` runs `sudo snap run subiquity` and ignores commands (tried: key login works, then only the installer log streams). `host_state`: when the IP answers SSH but the admin login fails, read the live cloud-init instance-id (`/var/lib/cloud/data/instance-id`, world-readable) as `vme-stack-probe`. `<host>-<sha>`: this host's install in progress (no IP-conflict failure); with this run's seed sha the boot driver is skipped and `wait_ssh` skips "old system down" (the deploy-key login waits for the reboot); an older sha fails for `platform: manual` ("installing from an older ISO"), a driver reboots it from the new ISO. Anything else is still a foreign machine. Verified on hvm03: run started while the installer was up -> "its installer is running (hvm03-347844b1d808)", boot skipped, installed and post-installed in 15 min, install-id check passed; `vme-stack-probe` does not exist on the installed system; reruns 0 changes. Untested: the older-seed guard.
- **boot_disk keeps kernel names (decided 2026-10-11, user)**: besides `auto` and match keys, `boot_disk: /dev/sda` (any `/dev/<name>`, also `/dev/nvme0n1`) is accepted again, rendered as `match: {path: /dev/sda}`; `path` is also a match key (`{path: "/dev/sd[ab]"}`). `/dev/disk/by-*` stays rejected (never matches in the installer). Docs warn that kernel names can move between boots with several controllers. Render checked; the same `match: {path: /dev/sda}` installed hvm02 (2026-10-10).
- **Taskfile for checks and releases (decided 2026-10-11)**: one root `Taskfile.yml` (go-task, pinned in `requirements-dev.txt` as `go-task-bin`, like `shellcheck-py`/`actionlint-py`, so one `pip install` gives every tool but Terraform). Task names are namespaced (`lint:*`, `test:*`, `ee:*`, `release:*`): an area can move into its own included Taskfile later without changing commands. CI (`ci.yml`) runs `task lint` / `task test`, `ee-release.yml` runs `task ee:build` / `task ee:smoke`. Release logic is in `scripts/release.py` (not YAML): `task release VERSION=X.Y.Z` checks SemVer above the latest tag, clean tree on `main` not behind `origin/main` (`OFFLINE=true` skips the fetch), a non-empty `## [Unreleased]` in the new `CHANGELOG.md`, `ee/README.md` sections, then `task check`; then writes `ee/VERSION`, dates the changelog section, adds the tested-with row from `VME_TESTED` in `ee/build.sh` (the image label) and updates `vme-stack-ee:X.Y.Z` pins in the docs, commits `Release X.Y.Z`, tags (`FULL=true`: local EE build + smoke first). Pushing is a separate `task release:push`. `task test:docs` (in CI) keeps the docs consistent with `ee/VERSION`. The ee/README table now lists only tested VME versions; change history moved to `CHANGELOG.md`. Verified in a throwaway clone: refusals (existing tag, dirty tree, bad SemVer, empty Unreleased, behind origin, push without tag) and a full 0.1.5 release.
- **Taskfile simplified (user request 2026-10-11, "should be easy to understand")**: replaces the namespaced `lint:*`/`test:*`/`dev:*` subtasks, the tool checks and `FULL=true`. Tools always run from `.venv/bin/` (Task lets the OS PATH win over a Taskfile `env:` PATH, so no PATH tricks); `task setup` (re)builds `.venv` with `python -m venv` + pip when `requirements-dev.txt` differs from the copy kept in `.venv`, and `lint`/`test` depend on it, so a missing tool cannot happen; CI installs only `go-task-bin`. ansible-lint and ruff find their files from their configs. Verified in an isolated copy with a minimal PATH: `task check`, rebuild on a changed requirements file, a full `task release VERSION=0.1.5 OFFLINE=true`.
- **Seed from HPE's ISO (decided 2026-10-11, user choice)**: `user-data.j2` no longer copies HPE's 8.1.1 seed. The seed role reads `/server/user-data` from the site's `hvm_iso` on the deploy server (xorriso), drops `interactive-sections` and merges our answers in (`combine` recursive; lists both set, i.e. `late-commands`, are HPE's then ours). It stops when the ISO's interactive-sections hold anything but storage, identity, network, proxy. Why: the HVM ISO for VME 9.0.2 (`HPE_HVM_Install_24.04_S5Q83-11078`) ships a different seed (hugepage kernel options, no bonding.conf late-command since 9.0 applies bond timers itself, `preserve_sources_list: true`); same Ubuntu 24.04.2 and identical grub.cfg. Verified: the 8.1.1 ISO renders a seed equal as data to the old template's (only HPE's late-command now precedes ours, and HPE's last runcmd item has no trailing newline); the 11078 ISO differs from it exactly by HPE's changes.
- **VME 9.0.2 (verified 2026-10-11)**: ISOs `HPE_HVM_Install_24.04_S5Q83-11078.iso` (same Ubuntu 24.04.2, same grub.cfg, new seed: see "Seed from HPE's ISO") and `HPE_VM_Essentials_SW_image_v9.0.2_2_S6E64-11258.iso` (same layout: one `hpe-vm-essentials-9.0.2-2.qcow2.gz`, `hpe-vm_1.0.15-1_amd64.deb`, plus Morpheus Manager Installer desktop apps we ignore). Two differences needed code: (1) **NTP**: HPE's 9.x post-install (`postcommand.sh`) installs a hardening set (aide, auditd, chrony, libpam-pwquality, vlock; postfix as a dependency), and chrony replaces systemd-timesyncd. Decided (packages as HPE ships them): postinstall configures chrony when `/usr/sbin/chronyd` exists (`/etc/chrony/sources.d/vme-stack.sources`, Ubuntu's `pool` lines commented out so only the site's servers count, like timesyncd's empty `FallbackNTP`), else timesyncd as before. (2) **Cluster layout**: 9.0 replaced layout 1.2 by 1.3 (Pacemaker replaced by the Morpheus agent for GFS2; the Manager lists only `mvm-1.3-ubuntu-24.04-std-morpheus-amd64` and the HCI Ceph `mvm-1.3-ubuntu-24.04-morpheus-amd64`). Decided: `vme_cluster.layout` defaults to the newest `mvm-<x.y>-ubuntu-24.04-std-morpheus-amd64` the Manager offers (filter `newest_hvm_layout`); a pinned code that does not exist fails listing the HVM codes. Unchanged and working: seed/media/boot, installer detection, `hpe-vm --install` (20 min, Manager 9.0.2-2), first-time setup API, group/cloud/key pair/cluster API, NFS datastore, Manager disk move + managed. Hosts keep `hpe-vm` 1.0.14-1 from the HVM ISO (the VME ISO's 1.0.15-1 is not installed on hosts; the cluster does not need it). Release notes 9.0: bond timers (miimon, up/down delay) are applied by HVM itself, which is why HPE dropped its bonding.conf late-command.
- **Manager URL DNS check (decided 2026-10-11, user request)**: when `vme_manager.url` holds a name, preflight queries each `network.dns` server for its A record (`net_probe.py --resolve`, raw DNS from `probe_from`, like the other DNS/NTP probes) and fails unless every answering server returns `vme_manager.ip` among its addresses (servers that do not answer at all are already a warning). Fail, not warn: hosts get exactly these servers, and agents and users reach the Manager by that URL; a missing or wrong record otherwise surfaces in the cluster step ~40 min later. An IP URL skips the check. Verified in the lab: IP URL passes; a name without a record and `www.github.com:8443` (wrong address) each fail with one line per DNS server. **NTP names (added 2026-10-11, user request)**: `network.ntp` entries that are names are resolved the same way; a server with no address for one is a warning (NTP checks only warn, decided 2026-10-09). Verified: public NTP names resolve on both lab DNS servers (no warning); a made-up name warns once per DNS server.
- **Groups, clouds, several clusters (decided 2026-10-11, user choices)**: `vme_cluster` (one cluster; group and cloud defaulted to the site name) is replaced by three top-level lists joined by name: `vme_groups` [{name}], `vme_clouds` [{name, type hvm|vmware, groups [..], vcenter (vmware only: url, credentials = vault var with {username, password} as for BMCs (user choice 2026-10-11: scales to several vCenters, clouds on one vCenter share it, username out of the site file), datacenter, cluster, import_existing)}], `vme_clusters` [{name, cloud (type hvm), group (default the cloud's first group), hosts, layout, datastores}]. Flat lists, not a tree, because a Manager cloud can be in several groups. The Manager's SSH key pair moves to `vme_manager.ssh_private_key`/`ssh_public_key` (one per Manager) and is found by its public key, else stored as `<hostname>-ssh`. Old `vme_cluster` fails the schema with a pointer to the new form (no compatibility path, pre-1.0). Every object is found by name or created, never changed or deleted; a cloud is created in its first group and added to the others with `PUT /api/groups/<id>/update-zones` (adds only). vmware clouds are created with zone type `vmware` (`apiUrl`, `username`, `password`, `datacenter`, `cluster`, `importExisting`); the Manager validates the vCenter connection on create. Site rules: unique names, references resolve, cluster cloud is type hvm, cluster group is one of its cloud's groups, a host in at most one cluster, per-cluster interface/admin checks, Manager datastore is a datastore of the cluster holding `vme_manager.host`. Verified in the lab on 9.0.2: the existing lab group/cloud/cluster and key pair adopted without changes; a second group created, the cloud added to it, a second cluster (hvm03) created in it; re-run 0 changes. vCenter: a fake vCenter got HTTP 400 "Invalid vmware credentials" and nothing was created. **Verified with the lab vCenter (2026-10-11)**: vCenter 8.0.3 (administrator account by the user's choice for the lab; a read-only role is recommended in the docs): a vmware cloud created in the second group (next to the shared HVM cloud), status ok after the first sync (1 ESXi host, 1 network, 1 datastore, 1 resource pool; importExisting off), re-run 0 changes, nothing changed on the vSphere side by vme-stack (it only calls the Manager). The URL may omit `/sdk` (the role appends it). **Import of existing VMs (user request 2026-10-11: default on, a site setting skips it)**: `vcenter.import_existing` (default true). The cloud is created with `importExisting: off`; once its status is ok and the first sync is done, the role switches it on (the one cloud setting changed after creation: `PUT /api/zones/<id>` with the stored config, the vault password again since the API masks it, and `importExisting: on`), refreshes the cloud and reports the VM count. VMs land as unmanaged servers (`vmwareUnmanaged`), not converted to managed (that would install the agent into the VMs). Verified: the vCenter's 6 VMs with their power states, cloud config otherwise unchanged and status ok after the refresh, re-run 0 changes. Also fixed: the seed's HPE-seed read was `run_once`, so it was skipped for all hosts when the first host was already installed (adding a host failed, 0.1.6).
- **Public/private split (decided 2026-10-11, user choices)**: the product moves to the public repo `kosmolito/vme-stack` with a fresh history (one import commit, released as **0.1.0**: versions restart, the private repo's 0.1.0-0.1.6 images are retired; version numbers in earlier entries of this log are the private ones); the old repo, renamed `vme-stack-lab` (private), keeps the full history and only the lab: site file, Terraform for the lab VMs, lab playbooks (deploy server and NFS bootstrap, `hpe_vm_ovs.yml`), lab notes. The lab uses this repo as a sibling checkout (`../vme-stack`), so lab runs use the working tree. This spec keeps the design and every decision; lab specifics (addresses, VM IDs, the shared Proxmox host, lab gotchas) moved to the lab repo's notes. `sites/` is gitignored here except `sites/example/`, a reference site with every setting (checked by `task test` like every site file). CI and the EE release run here; the lab repo has its own checks (its site file against this repo's schema, Terraform, lab playbook syntax).
