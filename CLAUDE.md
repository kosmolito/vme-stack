# vme-stack

Unattended install of HPE VM Essentials: HVM hosts, then the VME Manager, then the cluster. `spec.md` is the spec; its **Decisions log** at the end records everything decided and verified so far. Read it before changing anything.

## Working agreement

- One section at a time; each must work in the lab before the next starts. Current section: **VME Manager** (M4). The Ansible project is `ansible/`.
- Ask the user before decisions that change the design; record each decision in the spec's Decisions log.
- **This repository is public.** No site data, lab details (addresses, host names, VM IDs, domains), credentials or customer names in files, commit messages or the spec. Site files live outside (`sites/` is gitignored except `sites/example/`, the reference site with every setting: keep it in step with the schema). The maintainers' lab (site file, Terraform, lab playbooks, lab notes) is the private repo `vme-stack-lab`, checked out next to this one (`../vme-stack-lab`); its `CLAUDE.md` has the lab rules.

## Running

Everything Ansible needs is in the EE `vme-stack-ee` (build: `ee/build.sh`; usage and release: `ee/README.md`). Released: `ghcr.io/kosmolito/vme-stack-ee` (tags `vX.Y.Z`, workflow `ee-release`). Users run it with ansible-navigator from a site directory (`sites/example/ansible-navigator.yml`); below: Ansible installed natively.

```bash
cd ansible
SITE=<path to>/inventory.yml
ansible-playbook validate.yml -i $SITE                  # the site inventory only (variables, rules), contacts nothing
ansible-playbook preflight.yml -i $SITE                  # stage 1 only, changes nothing
ansible-playbook media.yml -i $SITE                      # build + publish ISOs, write build/<host>/iso_url
ansible-playbook deploy.yml -i $SITE --vault-password-file <site dir>/.vault_pass   # whole pipeline
ansible-playbook hvm_hosts.yml -i $SITE                  # wait for SSH + post-install (also builds media if needed)
# reinstall a host: hvm_hosts.yml -e force_reinstall=true --limit <host>
ansible-playbook collect.yml -i $SITE    # support bundle (logs + state, secrets replaced) into build/logs
# run log + bundle like the EE: python3 tools/vme_stack_run.py ansible-playbook ... (VME_STACK_DEBUG=1)
```

Site data lives only in the site file, a plain Ansible inventory (settings: `ansible/roles/preflight/meta/argument_specs.yml`, rules: `ansible/plugins/filter/vme_site.py`); `ansible/group_vars/` only derives what the roles read and must never define a name a site sets (it would override the site). The pipeline never touches a hypervisor: VMs are servers booted by someone else (`platform: manual`). Example sites: `ansible/examples/` (guided), `sites/example/` (every setting).

## Manager API

Reference for every call to the VME Manager API (`/api/...`, `/oauth/token`): https://apidocs.morpheusdata.com (HPE Morpheus API docs). The default version is the newest (9.1.0 when written); older ones are under `/v<version>/reference/...` (e.g. `/v9.0.2/`). Check request fields, required fields and response shapes there before adding or changing a call, for **9.0.2, 9.1 and every newer released version** (skip `-dev` doc versions such as `9.1-dev`); say in the change (commit, Decisions log) which versions were checked and how (live on a Manager or docs only). Each reference page embeds the whole OpenAPI spec (JSON starting `{"openapi":"3.1.0"`; extract it with `json.JSONDecoder().raw_decode`) for comparing versions in a script. The docs are not always complete: `/api/setup/check` and `/api/setup/init` are missing (taken from morpheus-cli), and some descriptions are copied between operations, so verify behaviour on a real Manager too.

## Checks and releases

Before committing (as CI does), from the repo root: `task check` (`task --list` for the rest). `task lint`/`task test` build `.venv` from `requirements-dev.txt` first (`task setup`: the newest python3.14/3.13/3.12 found, or `PYTHON=`; ansible-core 2.21 needs 3.12 to 3.14). Releases: `task release VERSION=X.Y.Z` (needs an entry under `## [Unreleased]` in `CHANGELOG.md`), then `task release:push`. Details: `ee/README.md`.

- Packages exactly as HPE ships them: no `apt upgrade` of ours; the installer's own update step runs as in a manual install.
- Bare metal: platform `redfish` uses the vendored `roles/baremetal_lifecycle` (from the user's private repo, see its README; sync by hand). Untested on real hardware.
