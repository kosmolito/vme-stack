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

Everything is described in a **site file** (`site.yml`): network, hosts, Manager,
cluster. Secrets (passwords, keys) live in an Ansible Vault file next to it.

## Quick start

You need the container image (`ghcr.io/kosmolito/vme-stack-ee`), Docker or Podman,
and a site directory:

```
sites/acme/
  site.yml                    # the site, from an example (see below)
  group_vars/all/vault.yml    # secrets, encrypted with ansible-vault
  keys/deploy_server          # SSH key of your login on the deploy server
  keys/hvm_hosts              # SSH key vme-stack installs for the hosts' admin user
```

In `site.yml`, point to the keys relative to the file: `deploy_server.ssh_private_key:
keys/deploy_server` and `defaults.hvm_ssh_private_key: keys/hvm_hosts` (one file for
both works too).

Check everything first (changes nothing), then deploy:

```bash
docker run --rm -it -v $PWD/sites/acme:/site:ro ghcr.io/kosmolito/vme-stack-ee:latest \
  ansible-playbook preflight.yml -i /site/site.yml --ask-vault-pass

docker run --rm -it -v $PWD/sites/acme:/site:ro ghcr.io/kosmolito/vme-stack-ee:latest \
  ansible-playbook deploy.yml -i /site/site.yml --ask-vault-pass
```

Example sites with step-by-step guides, for VMs and for bare metal:
[`ansible/examples/`](ansible/examples/README.md). Every setting, with comments:
[`sites/example/`](sites/example/README.md).

Running it again is safe: finished steps are skipped. Stages can also run alone:
`hvm_hosts.yml`, `vme_manager.yml`, `vme_cluster.yml`.

More on running the container (from a Mac, interactively, emergency hotfixes):
[`ee/README.md`](ee/README.md).

## Repository

| Folder | What it is |
|---|---|
| `ansible/` | the pipeline: playbooks, roles, site file schema |
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
