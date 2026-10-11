# vme-stack

Unattended install of HPE VM Essentials: HVM hosts, then the VME Manager, then the cluster. `spec.md` is the spec; its **Decisions log** at the end records everything decided and verified so far. Read it before changing anything.

## Working agreement

- One section at a time; each must work in the lab before the next starts. Current section: **VME Manager** (M4). The Ansible project is `ansible/`.
- Ask the user before decisions that change the design; record each decision in the spec's Decisions log.
- **This repository is public.** No site data, lab details (addresses, host names, VM IDs, domains), credentials or customer names in files, commit messages or the spec. Site files live outside (`sites/` is gitignored except `sites/example/`, the reference site with every setting: keep it in step with the schema). The maintainers' lab (site file, Terraform, lab playbooks, lab notes) is the private repo `vme-stack-lab`, checked out next to this one (`../vme-stack-lab`); its `CLAUDE.md` has the lab rules.

## Running

Everything Ansible needs is in the EE `vme-stack-ee` (build: `ee/build.sh`; usage and release: `ee/README.md`). Released: `ghcr.io/kosmolito/vme-stack-ee` (tags `vX.Y.Z`, workflow `ee-release`).

```bash
cd ansible
SITE=<path to>/site.yml
ansible-inventory -i $SITE --graph                       # schema check + inventory
ansible-playbook preflight.yml -i $SITE                  # stage 1 only, changes nothing
ansible-playbook media.yml -i $SITE                      # build + publish ISOs, write build/<host>/iso_url
ansible-playbook deploy.yml -i $SITE --vault-password-file <site dir>/.vault_pass   # whole pipeline
ansible-playbook hvm_hosts.yml -i $SITE                  # wait for SSH + post-install (also builds media if needed)
# reinstall a host: hvm_hosts.yml -e force_reinstall=true --limit <host>
```

Site data lives only in the site file (schema: `ansible/schemas/site.schema.json`); tuning defaults in `ansible/group_vars/all.yml`. The pipeline never touches a hypervisor: VMs are servers booted by someone else (`platform: manual`). Example sites: `ansible/examples/` (guided), `sites/example/` (every setting).

## Checks and releases

Before committing (as CI does), from the repo root: `task check` (`task --list` for the rest). `task lint`/`task test` build `.venv` from `requirements-dev.txt` first (`task setup`, `PYTHON=` ≥ 3.12). Releases: `task release VERSION=X.Y.Z` (needs an entry under `## [Unreleased]` in `CHANGELOG.md`), then `task release:push`. Details: `ee/README.md`.

- Packages exactly as HPE ships them: no `apt upgrade` of ours; the installer's own update step runs as in a manual install.
- Bare metal: platform `redfish` uses the vendored `roles/baremetal_lifecycle` (from the user's private repo, see its README; sync by hand). Untested on real hardware.
