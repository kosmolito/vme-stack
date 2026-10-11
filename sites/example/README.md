# Example site (every setting)

[`site.yml`](site.yml) uses every setting of the site file, each with a comment;
[`vault.example.yml`](vault.example.yml) lists every secret it names. Values marked
"default" can be left out. For a guided first site, start from
[`ansible/examples/`](../../ansible/examples/README.md) (VMs or bare metal) instead,
and look things up here.

## A site directory

```
sites/acme/                       # anywhere; sites/ is gitignored in this repository
  site.yml                        # from site.yml here, trimmed to your site
  keys/deploy_server              # your login's key on the deploy server (chmod 600)
  keys/hvm_hosts                  # key for the hosts' admin user (chmod 600), created below
  group_vars/all/vault.yml        # from vault.example.yml, then: ansible-vault encrypt
  .vault_pass                     # optional, for --vault-password-file
```

```bash
cp -r sites/example sites/acme && cd sites/acme
mkdir -p keys && cp ~/.ssh/<deploy server key> keys/deploy_server
ssh-keygen -t ed25519 -N '' -C vme-stack -f keys/hvm_hosts   # installed on the hosts by the run
mkdir -p group_vars/all && mv vault.example.yml group_vars/all/vault.yml
$EDITOR site.yml group_vars/all/vault.yml
ansible-vault encrypt group_vars/all/vault.yml
```

Keep site directories out of this public repository: in a private repository or
on the deploy server. Then check and run (from `ansible/`, or with the container
image as in the main [README](../../README.md)):

```bash
ansible-inventory -i ../sites/acme/site.yml --graph                     # schema check
ansible-playbook preflight.yml -i ../sites/acme/site.yml --ask-vault-pass   # changes nothing
ansible-playbook deploy.yml -i ../sites/acme/site.yml --ask-vault-pass
```

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

`task test` checks this file against the schema and the site rules, like every
`sites/*/site.yml`.
