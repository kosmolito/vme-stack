# vme-stack execution environment (EE)

One image with everything the pipeline needs: ansible-core, ansible-runner, the
Python libraries (jsonschema, passlib), an SSH client **and the vme-stack code**
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

## Run

Mount the site directory as `/site`. Paths inside the site file are relative to
it, e.g. `ssh_private_key: ../../keys/deploy_server` resolves to `/keys/deploy_server`.

```bash
docker run --rm -it --network host \
  -v /srv/vme-stack/sites/acme:/site:ro \
  -v /srv/vme-stack/keys:/keys:ro \
  vme-stack-ee:0.1.2 \
  ansible-playbook deploy.yml -i /site/site.yml --vault-password-file /site/.vault_pass
```

- The image is multi-arch (linux/amd64, linux/arm64): on an Apple Silicon Mac
  Docker pulls the native arm64 variant.
- On a client (e.g. macOS) leave out `--network host` and use
  `deploy_server.connection: ssh`: the pipeline only makes outgoing connections
  (SSH, HTTPS, Redfish), which work from Docker Desktop's normal network, also over VPN.
- `--network host`: the container uses the deploy server's network (mgmt network,
  BMCs). On the deploy server itself, use `deploy_server.connection: ssh` with its
  own address: `local` would mean inside the container.
- Without `--vault-password-file`, use `-it` and `--ask-vault-pass`.
- Interactive: leave out the command to get a shell (`bash`) in the code directory,
  then run `ansible-playbook ...`, `ansible-inventory -i /site/site.yml --graph`, etc.
- Runs as uid 1000 (group 0); mounted files must be readable for it.

## From a client (e.g. a Mac)

The image runs natively on Apple Silicon (arm64 variant). What has to be in place:

1. **Docker** (Docker Desktop, OrbStack or Colima). The image is public on GHCR,
   no login needed.
2. **A site directory**, mounted as `/site`:
   ```
   acme/
     site.yml                    # deploy_server.connection: ssh (default)
     group_vars/all/vault.yml    # ansible-vault: passwords, Manager key, BMC credentials
     keys/deploy_server          # SSH private keys (chmod 600): deploy_server.ssh_private_key
     keys/hvm_hosts              #   and defaults.hvm_ssh_private_key (may be one file)
     .vault_pass                 # optional, else --ask-vault-pass
   ```
3. **Network from the client** (outgoing only): SSH (22) to the deploy server and to
   the HVM hosts (directly or via `deploy_server.jump`), HTTPS (443) to the BMCs for
   `platform: redfish`. The client does not need to reach the Manager or the media
   URLs: Manager API calls run from the deploy server, hosts/BMCs fetch the ISOs
   from it.
4. **The deploy server**: Debian/Ubuntu or RHEL family, the SSH user with
   passwordless sudo, and the two ISOs at the paths in `site.yml`.

```bash
docker run --rm -it -v ~/vme-sites/acme:/site:ro ghcr.io/kosmolito/vme-stack-ee:0.1.2 \
  ansible-playbook deploy.yml -i /site/site.yml --ask-vault-pass
```

No `--network host` on a Mac (it would be Docker's VM, not the Mac). Use
`preflight.yml` first to check everything without changes.

## Hotfix (emergency code change)

Mount a host directory at `/vme-stack-hotfix`:

| mount | code used |
|---|---|
| none | the image's code |
| empty directory | the image's code is copied into it (plus `VERSION`), then used |
| directory with code | used as it is, nothing is copied |

```bash
mkdir /srv/vme-stack/hotfix
docker run --rm -v /srv/vme-stack/hotfix:/vme-stack-hotfix ... vme-stack-ee:0.1.2 true   # exports the code
vi /srv/vme-stack/hotfix/roles/...                                                       # fix
docker run --rm -v /srv/vme-stack/hotfix:/vme-stack-hotfix ... vme-stack-ee:0.1.2 ansible-playbook ...
```

Every run prints which code it uses, e.g.
`vme-stack 0.1.0: using HOTFIX code from /vme-stack-hotfix (based on 0.1.0)`.
Leave the mount out and the image's code is used again. Get the fix back into git
(`diff -ru` against an export of the same image version) and release a new version;
an old hotfix directory mounted into a newer image is **not** detected automatically,
only shown in that line.
