# Example sites

Two scenarios, both ending with the same result: HVM hosts installed, the VME
Manager running and set up, an HVM cluster with shared NFS storage.

| | [`vm/`](vm/site.yml) | [`baremetal/`](baremetal/site.yml) |
|---|---|---|
| hosts | VMs on any hypervisor | physical HPE (iLO) / Dell (iDRAC) servers |
| `platform` | `manual` | `redfish` |
| who boots the ISO | you (or Terraform etc.) | the pipeline, over Redfish |
| one run, start to end | no: you attach the ISOs while it waits | yes |

Both need:

- a **deploy server** (Ubuntu/Debian or RHEL family) on the mgmt network, an SSH user
  with passwordless sudo, and HPE's two ISOs at the paths in `media`
- an **NFS export** for the cluster (`vme_clusters[].datastores`)
- a site directory, copied from the example:
  ```
  acme/
    site.yml
    keys/vme-stack               # SSH private key (chmod 600): deploy_server.ssh_private_key and
                                 # defaults.hvm_ssh_private_key (one key for both, or two files)
    group_vars/all/vault.yml     # from vault.example.yml, then: ansible-vault encrypt
  ```

Always start with `preflight.yml`: it checks the site file, the deploy server,
DNS, NTP, the DNS records of the Manager URL and NTP server names (on the site's
DNS servers) and (bare metal) the BMCs, and changes nothing.

```bash
alias vme='docker run --rm -it -v $PWD/acme:/site:ro ghcr.io/kosmolito/vme-stack-ee:0.1.2'
vme ansible-playbook preflight.yml -i /site/site.yml --ask-vault-pass
```

## Scenario 1: VMs (`vm/`)

For a lab or a proof of concept. Per HVM host VM:

- **nested virtualization** on (VMware: "Expose hardware assisted virtualization";
  Proxmox: CPU type `host`), UEFI firmware
- 8+ vCPU, 16+ GB RAM (the Manager's host: 32+ GB), 100+ GB disk
- one vNIC per entry in `nics`, with the **fixed MAC** from the site file (each
  role becomes a bond with one member, so a second vNIC can be added later)
- mgmt vNIC in the mgmt VLAN's port group / bridge, untagged (`mgmt_vlan: 0`);
  compute vNIC on a trunk carrying `compute_vlans` tagged. To tag mgmt in the guest
  instead, set `mgmt_vlan` and make the mgmt vNIC a trunk too (never tag in both
  places: double tag, no traffic)
- VMware: allow promiscuous mode, MAC changes and forged transmits on the port
  groups (the cluster's VMs use their own MACs)

Then:

```bash
vme ansible-playbook deploy.yml -i /site/site.yml --ask-vault-pass
```

1. The run builds one ISO per host and prints its URL, e.g.
   `Attach and boot hvm01 from: http://192.168.50.5:8080/isos/vme-stack-hvm01-<sha>.iso`
2. Download/attach that ISO to the VM and boot from it (the run waits up to 45 min
   per host). The install needs no input.
3. When the hosts answer on SSH, the run continues alone: post-install, Manager,
   first-time setup, cluster, NFS, Manager moved to NFS.

To build the ISOs first and attach them before the long run:
`media.yml`, attach and boot, then `deploy.yml` (finished steps are skipped).

## Scenario 2: bare metal (`baremetal/`)

Per server:

- BMC (iLO 5/6 or iDRAC 9) reachable over HTTPS from where the container runs,
  with a user that may use virtual media and power control (`vault_ilo`, ...)
- the BMC can reach the deploy server on HTTP 8080 (it fetches the ISO itself)
- UEFI boot, Secure Boot off; or `bmc.bios_setup: true` to let the pipeline set it
- the MACs of the NICs (iLO/iDRAC shows them)
- with several disks: the OS goes on the **smallest** disk (`boot_disk: auto`), which
  suits a boot device such as NS204i or BOSS. If something smaller is visible (SD
  card, USB module, small LUN), pick the disk with installer match keys (globs on
  udev values), e.g. `boot_disk: {model: "*NS204i*"}`. `serial` matches the
  `/dev/disk/by-id/` name without its bus prefix: for SAS disks and RAID logical
  drives that is often the WWN, not the serial on the label. A kernel name
  (`boot_disk: /dev/sda`) works too, but can point to another disk after a reboot
  when there are several controllers. `/dev/disk/by-id/` paths do not work. Other
  disks are left untouched
- switch ports: mgmt VLAN tagged (`mgmt_vlan: 100`) or untagged (`mgmt_vlan: 0`,
  access/native VLAN on the mgmt ports), compute VLANs tagged

Then one run, from powered off (or running anything: it is reinstalled) to cluster:

```bash
vme ansible-playbook deploy.yml -i /site/site.yml --ask-vault-pass
```

The pipeline mounts each server's ISO as virtual media, boots it once from it and
waits for the installed system. Status: built, not yet tested on real hardware.

## Groups, clouds and clusters in the Manager

Three lists, joined by name; each object is found by name or created, never
changed or deleted afterwards:

- `vme_groups`: the Manager groups.
- `vme_clouds`: `type: hvm` is the HPE VM private cloud the HVM clusters live in;
  `type: vmware` is a vCenter cloud (`vcenter`: URL, `username` and `password`
  from the vault as for the BMCs, datacenter, optionally one vCenter cluster),
  which the Manager then syncs; a read-only vCenter role is
  enough. Once the cloud is up, its existing VMs are imported into the Manager as
  unmanaged VMs (nothing changes in vCenter); `import_existing: false` skips that.
  `groups` lists the groups the cloud is in; it can be several.
- `vme_clusters`: HVM clusters, each with its `cloud` (type hvm), its `hosts`
  (a host is in at most one cluster) and its datastores. The cluster is placed in
  its cloud's first group, or in `group` (one of the cloud's groups).

The Manager reaches every cluster's hosts with one key pair:
`vme_manager.ssh_private_key` / `ssh_public_key` (from the vault).

## Values and secrets

Values in `site.yml` are plain Ansible: a literal, or a template Ansible resolves
when the value is used. For secrets, reference the vault with a quoted template,
`"{{ vault_hvm_admin_password }}"` or `"{{ vault_ilo.password }}"`, so they stay
encrypted; a literal password works too, but sits in the site file in clear text.
Preflight lists every secret that does not resolve (vault not loaded, variable
missing). Each BMC has its own
`username`/`password`; servers with the same login can name the same variable.

## Mixing

`platform` can be set per host, e.g. physical servers plus one VM:
`defaults.platform: redfish` and `platform: manual` on the VM.
