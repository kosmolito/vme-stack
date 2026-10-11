# vme-stack

Installs a complete **HPE VM Essentials** environment from empty servers, with one
command and one configuration file per site:

1. **HVM hosts**: unattended Ubuntu install from HPE's own HVM ISO
2. **VME Manager**: deployed with HPE's `hpe-vm` tool, first-time setup done
3. **Cluster**: HVM cluster with the hosts, shared NFS storage

Packages come only from HPE (the ISO and HPE's repository). vme-stack fills in what
HPE's installer asks for interactively: network, disk, users and proxy.

## How it works

A **deploy server** (any Ubuntu/Debian or RHEL-family Linux machine on the
management network) holds HPE's ISOs, builds one install ISO per host and serves
it over HTTP. Each server boots its ISO, through its BMC (HPE iLO / Dell iDRAC) or,
for VMs, through whatever created them. Then the Manager and the cluster are set up
through HPE's tools and the Manager's API.

Everything is described in a **site file** (`inventory.yml`): network, hosts, Manager,
cluster. Secrets (passwords, keys) live in an Ansible Vault file next to it.

## Quick start

You need Docker (or Podman: set `container-engine: podman` in the site's
`ansible-navigator.yml`), [ansible-navigator](https://ansible.readthedocs.io/projects/navigator/)
(`pip install ansible-navigator`), and a **site directory**: everything about one
site in one folder. The container image (`ghcr.io/kosmolito/vme-stack-ee`) brings
the code and all tools; navigator runs it with this folder mounted.

```
sites/acme/
  inventory.yml               # the site (any name ending in .yml), from an example
  ansible-navigator.yml       # how to run it: image, mounts (from sites/example/)
  group_vars/all/vault.yml    # secrets, encrypted with ansible-vault
  .vault_pass                 # vault password (chmod 600), or ask each run
  logs/                       # run logs, run records, support bundles (written by runs)
  build/                      # rendered seeds and ISO URLs (written by runs)
```

The site file is a plain **Ansible inventory**: site-wide settings in `all.vars`,
the deploy server in group `deploy_server`, the HVM hosts in group `hvm` (with
their defaults as group vars), the Manager's host in group `vme_manager`. Every
setting, commented: [`sites/example/inventory.yml`](sites/example/inventory.yml).

**SSH key: `~/.ssh/id_ed25519` by default**, for the deploy server login and the
hosts' admin user alike (its public key is installed on the hosts). It stays in
your `~/.ssh`: ansible-navigator mounts that into the container, where it is
`~/.ssh` as well. For another key set `ansible_ssh_private_key_file` in the
inventory, e.g. `~/.ssh/acme_deploy`, or a key kept in the site directory:
`"{{ inventory_dir }}/keys/..."`.

Set it up from the reference site ([`sites/example/README.md`](sites/example/README.md)
has the details), then check everything (changes nothing) and deploy:

```bash
cd sites/acme
ansible-navigator run validate.yml         # the site file only, contacts nothing
ansible-navigator run preflight.yml
ansible-navigator run deploy.yml
```

Every run writes its log and a full record to `logs/`; `ansible-navigator replay
logs/<run>.json` steps through a past run task by task. **Something went wrong?**
Run it again with `VME_STACK_DEBUG=1 ansible-navigator run deploy.yml`: more detail,
and at the end (also after a failure) a support bundle
`logs/vme-stack-support-<site>-<date>.tar.gz` with the logs and state of all
machines, secrets replaced. Send that file. Details:
[`ee/README.md`](ee/README.md#logs-and-support-bundle).

Example sites with step-by-step guides, for VMs and for bare metal:
[`ansible/examples/`](ansible/examples/README.md). Every setting, with comments:
[`sites/example/`](sites/example/README.md).

Running it again is safe: finished steps are skipped. Stages can also run alone:
`hvm_hosts.yml`, `vme_manager.yml`, `vme_cluster.yml` (e.g. `ansible-navigator run
hvm_hosts.yml --limit hvm02 -e force_reinstall=true`).

More on running the container (without navigator, from a Mac, emergency hotfixes):
[`ee/README.md`](ee/README.md).

## Repository

| Folder | What it is |
|---|---|
| `ansible/` | the pipeline: playbooks, roles, the site settings (`roles/preflight/meta/argument_specs.yml`) |
| `ee/` | the container image (execution environment) and how it is released |
| `sites/example/` | a site with every setting; real sites stay out of this repository (gitignored) |
| `spec.md` | the specification, with a log of all design decisions |
| `CHANGELOG.md` | what changed in each release |
| `Taskfile.yml` | checks and releases: `task check`, `task release VERSION=X.Y.Z` |

## Status

Tested end to end in a lab (Proxmox VMs): from empty hosts to a working cluster in
about 45 minutes. Site files hold customer data and never go into this repository
(`sites/` is gitignored except `sites/example/`): keep them in a private repository
or outside the clone. Booting physical servers through iLO/iDRAC is built but not yet
tested on real hardware. Not covered yet: GFS2 storage, Manager high availability.
