# Example site (every setting)

[`site.yml`](site.yml) uses every setting of the site file, each with a comment;
[`vault.example.yml`](vault.example.yml) lists every secret it names. Values marked
"default" can be left out. For a guided first site, start from
[`ansible/examples/`](../../ansible/examples/README.md) (VMs or bare metal) instead,
and look things up here.

## A site directory

Everything about one site in one folder; runs read it and write `logs/` and `build/`
into it:

```
sites/acme/                       # anywhere; sites/ is gitignored in this repository
  site.yml                        # from site.yml here, trimmed to your site (any name ending in .yml)
  ansible-navigator.yml           # how to run it (from here; names site.yml as /site/site.yml)
  keys/deploy_server              # your login's key on the deploy server (chmod 600)
  keys/hvm_hosts                  # key for the hosts' admin user (chmod 600), created below
  group_vars/all/vault.yml        # from vault.example.yml, then: ansible-vault encrypt
  .vault_pass                     # the vault password (chmod 600)
  logs/                           # run logs, run records (.json), support bundles
  build/                          # rendered seeds and ISO URLs
```

Keys live here; the inventory points to them with `"{{ inventory_dir }}/keys/..."`:
the container only sees this directory (as `/site`).

```bash
cp -r sites/example sites/acme && cd sites/acme
mkdir -p keys logs build
cp ~/.ssh/<deploy server key> keys/deploy_server && chmod 600 keys/deploy_server
ssh-keygen -t ed25519 -N '' -C vme-stack -f keys/hvm_hosts   # installed on the hosts by the run
mkdir -p group_vars/all && mv vault.example.yml group_vars/all/vault.yml
$EDITOR site.yml group_vars/all/vault.yml
touch .vault_pass && chmod 600 .vault_pass && $EDITOR .vault_pass   # one line: the vault password
ansible-vault encrypt group_vars/all/vault.yml --vault-password-file .vault_pass
```

Keep site directories out of this public repository: in a private repository (add
`.vault_pass`, `keys/`, `logs/`, `build/` to its `.gitignore`) or on the deploy
server. Then check and run:

```bash
ansible-navigator run preflight.yml        # changes nothing
ansible-navigator run deploy.yml
VME_STACK_DEBUG=1 ansible-navigator run deploy.yml   # if something fails: support bundle in logs/
```

Without `.vault_pass`: remove the `cmdline` line in `ansible-navigator.yml` and run
with `--ask-vault-pass --pae false`. With a different site file name, change
`/site/site.yml` there.

## What the example shows

| Host | Boot | Network | Disk |
|---|---|---|---|
| hvm01 | Redfish (iLO), BIOS set up by the pipeline | `nics`, dedicated: bond0 (mgmt, VLAN 100) + bond1 (compute) | `auto` (smallest) |
| hvm02 | Redfish (iLO) | `nics`, dedicated | match keys (`model`) |
| hvm03 | Redfish (iDRAC) | `nics`, dedicated | kernel name `/dev/sda` |
| hvm04 | `manual` (a VM) | `nics`, shared: bond0 only, untagged | `auto` |
| hvm05 | Redfish (iLO) | raw `netplan` (LACP, MTU 9000) + `hpe_vm` | raw `storage` (RAID 1) |

In the Manager: groups `production` and `development`; the HVM cloud
`example-hvm` in both; a vCenter cloud; cluster `prod` (hvm01-03, hvm05, NFS,
holds the Manager VM) and cluster `dev` (hvm04, which has other interface names:
hosts of one cluster must share them).

`task test` checks this file with `validate.yml` (variables and site rules), like every
`sites/*/site.yml`.
