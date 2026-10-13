# Site variables

Every variable a site inventory can set, with what it does and its default. Generated
from [`argument_specs.yml`](../ansible/roles/preflight/meta/argument_specs.yml), the
spec preflight checks every site against (`task docs` writes this file). For a full
example with comments see [`sites/example/inventory.yml`](../sites/example/inventory.yml).

- **Where**: site-wide settings go in `all.vars` of the inventory (or a file in
  `group_vars/all/` of a split site), the deploy server's in its host vars, the HVM
  hosts' in `hvm` group vars (defaults for all hosts) or per host.
- **Names** with dots are keys inside a dict (`network.domain`); `[]` marks a list of
  dicts (`vme_clusters[].hosts`).
- **Secrets** (marked *Secret*) are best vault references: `"{{ vault_x }}"` with
  `vault_x` in an encrypted `group_vars/all/vault.yml`; a literal works too.
- **Required** (yes) means within its parent: `vme_manager.ip` is required once
  `vme_manager` is set.
- Rules across variables (unique IPs and MACs, references between Manager objects,
  one password per cluster, ...) are checked by preflight as well; it lists every
  problem at once. Check a site without contacting anything: `validate.yml`.


## Site-wide settings (all.vars, or group_vars/all/ in a split site)

| Variable | Type | Required | What it is |
|---|---|---|---|
| `site` | str | yes | Short name of the site. Used in run logs and support bundles, and as the Manager's tenant name unless vme_manager.tenant is set. |
| `network` | dict | yes | The management network that the deploy server, the HVM hosts and the Manager share. |
| `network.domain` | str | yes | DNS domain of the hosts (hvm01 becomes hvm01.&lt;domain&gt;). |
| `network.gateway` | str | yes | Default gateway of the mgmt network. |
| `network.prefix` | int | yes | Prefix length of the mgmt network (24 = 255.255.255.0). |
| `network.mgmt_vlan` | int |  | 802.1Q VLAN tag of the mgmt network on the hosts. Default 0 = untagged. |
| `network.dns` | list of str | yes | DNS servers (IP addresses) the hosts and the Manager use. |
| `network.ntp` | list of str | yes | NTP servers (addresses or names) the hosts use. |
| `network.timezone` | str |  | IANA time zone of the hosts, e.g. Europe/Stockholm. Default UTC. |
| `network.proxy` | str |  | HTTP proxy for the installer and apt, e.g. http://proxy:3128. Default: none. |
| `network.bond_mode` | str: `active-backup`, `802.3ad` |  | Bond mode of the nics layout. Default active-backup (no switch config); 802.3ad needs LACP on the switch. |
| `network.compute_vlans` | list of int |  | VLANs for VM traffic on the compute bridge, set up when a cluster is created. Required when hosts have a compute interface. |
| `ssh_jump` | str |  | Jump host (user@host) to reach the deploy server and the hosts through, e.g. when the machine you run from is not on the mgmt network. Logged in with the deploy server's key. Default: direct SSH. |
| `vme_manager` | dict |  | The VME Manager VM, installed with HPE's hpe-vm onto the one host in group vme_manager. Leave out to install the hosts only. |
| `vme_manager.ip` | str | yes | The Manager VM's IP on the mgmt network (netmask, gateway and DNS come from network). |
| `vme_manager.hostname` | str | yes | The Manager VM's host name. |
| `vme_manager.url` | str |  | URL users and hosts reach the Manager by. Default https://&lt;ip&gt;. A name must resolve to ip on every network.dns server (preflight checks it). |
| `vme_manager.size` | str: `S`, `M`, `L` |  | VM size: S = 12 GB / 2 vCPU, M = 16 GB / 4 vCPU, L = 32 GB / 4 vCPU. Default S. |
| `vme_manager.admin_user` | str |  | Admin user of the Manager VM and the Manager's first admin. Default vmeadmin. |
| `vme_manager.admin_password` | str | yes | *Secret.* Password of admin_user. |
| `vme_manager.tenant` | str |  | Name of the Manager's master tenant. Default the site name. |
| `vme_manager.email` | str |  | Email of the first admin. Default &lt;admin_user&gt;@&lt;network.domain&gt;. |
| `vme_manager.license_key` | str |  | *Secret.* VME license key. Default: none, the Manager starts a trial. Installed at setup, or on a later run when the Manager does not have it yet. |
| `vme_manager.smtp` | dict |  | Outgoing mail of the Manager (its SMTP settings), set on every run. Leave out to keep the Manager's own settings. |
| `vme_manager.smtp.host` | str | yes | SMTP server (name or IP) the Manager sends mail through. |
| `vme_manager.smtp.port` | int |  | SMTP port. Default 25. |
| `vme_manager.smtp.from` | str |  | Sender address. Default &lt;admin_user&gt;@&lt;network.domain&gt;. |
| `vme_manager.smtp.tls` | bool |  | STARTTLS after connecting (usually port 587). Default false. |
| `vme_manager.smtp.ssl` | bool |  | TLS from the start (usually port 465). Default false. Not together with tls. |
| `vme_manager.smtp.user` | str |  | SMTP login. Default: none (no login). |
| `vme_manager.smtp.password` | str |  | *Secret.* Password of user. |
| `vme_manager.smtp.restart_webui_on_update` | bool |  | Restart the Manager's UI service (morpheus-ui, several minutes without UI and API) after a run changed the SMTP settings: the Manager uses settings set through its API only after a restart. Default true. false: they apply at the next restart of morpheus-ui. |
| `vme_manager.datastore` | str |  | A datastore of the Manager host's cluster to move the Manager's disk to once the cluster exists. Default: stays local. |
| `vme_manager.autostart` | bool |  | Start the Manager VM with its host (libvirt autostart). Default false, as hpe-vm sets it. |
| `vme_manager.ssh_private_key_file` | str |  | The Manager's key pair to every cluster's hosts as files: this and &lt;file&gt;.pub. It is stored in the Manager. Default: the Manager host's login key (its ansible_ssh_private_key_file, else ~/.ssh/id_ed25519). |
| `vme_manager.ssh_private_key` | str |  | *Secret.* The Manager's private key itself instead of the file (together with ssh_public_key). |
| `vme_manager.ssh_public_key` | str |  | The public key line of ssh_private_key. |
| `vme_groups` | list of dict |  | Manager groups to create (found by name, never changed or deleted). |
| `vme_groups[].name` | str | yes | Group name. |
| `vme_clouds` | list of dict |  | Manager clouds to create (found by name, never changed or deleted). |
| `vme_clouds[].name` | str | yes | Cloud name. |
| `vme_clouds[].type` | str: `hvm`, `vmware` | yes | hvm: an HPE VM private cloud for the HVM clusters; vmware: an existing vCenter. |
| `vme_clouds[].groups` | list of str | yes | Groups (vme_groups names) the cloud is in; can be several. |
| `vme_clouds[].vcenter` | dict |  | The vCenter of a vmware cloud. Its existing VMs are imported into the Manager as unmanaged VMs; nothing changes in vCenter. |
| `vme_clouds[].vcenter.url` | str | yes | vCenter URL, e.g. https://vcenter.example.com (/sdk is added when missing). |
| `vme_clouds[].vcenter.username` | str | yes | vCenter user (a read-only role is enough; best a vault reference). |
| `vme_clouds[].vcenter.password` | str | yes | *Secret.* Its password. |
| `vme_clouds[].vcenter.datacenter` | str | yes | The vCenter datacenter to sync. |
| `vme_clouds[].vcenter.cluster` | str |  | Only this vCenter cluster. Default: all of the datacenter. |
| `vme_clouds[].vcenter.import_existing` | bool |  | Import the existing VMs. Default true. |
| `vme_clusters` | list of dict |  | HVM clusters to create in the Manager, each with its hosts and datastores. Requires vme_manager. |
| `vme_clusters[].name` | str | yes | Cluster name. |
| `vme_clusters[].cloud` | str | yes | The hvm cloud (vme_clouds name) the cluster is in. |
| `vme_clusters[].group` | str |  | One of the cloud's groups to put the cluster in. Default the cloud's first group. |
| `vme_clusters[].hosts` | list of str | yes | HVM hosts (inventory names) of the cluster; a host is in at most one cluster, and the hosts of one cluster must share interface names. |
| `vme_clusters[].layout` | str |  | Manager cluster layout code. Default the newest HVM layout on the Manager. |
| `vme_clusters[].datastores` | list of dict |  | Shared storage of the cluster. |
| `vme_clusters[].datastores[].name` | str | yes | Datastore name in the Manager. |
| `vme_clusters[].datastores[].type` | str: `nfs` | yes | Storage type; NFS only so far. |
| `vme_clusters[].datastores[].host` | str | yes | NFS server address. |
| `vme_clusters[].datastores[].path` | str | yes | Exported path on the NFS server (absolute). |
| `vme_clusters[].datastores[].version` | str: `3`, `4` |  | NFS version. Default: the Manager's. |
| `vme_clusters[].datastores[].default` | bool |  | The cluster's default datastore (image target); at most one. Default false. |
| `wait_ssh_timeout` | int |  | Seconds to wait for a host to finish its install. Default 2700 (45 min). |
| `force_reinstall` | bool |  | Reinstall hosts that are installed already. Only with --limit. Usually -e force_reinstall=true for one run. |
| `keep_host_iso` | bool |  | Keep each host's ISO on the deploy server after its install. Default false (removed). |

## The deploy server (host vars of the one host in group deploy_server)

| Variable | Type | Required | What it is |
|---|---|---|---|
| `ansible_host` | str |  | Its address. Default: the inventory name. Not needed with ansible_connection local. |
| `ansible_user` | str |  | SSH user, with passwordless sudo. Required unless ansible_connection is local. |
| `ansible_ssh_private_key_file` | str |  | SSH key to log in with. Default ~/.ssh/id_ed25519. |
| `ansible_connection` | str |  | local when you run on the deploy server itself. Default ssh. |
| `media` | dict | yes | What the deploy server builds and serves. |
| `media.hvm_iso_path` | str | yes | Path of HPE's stock HVM install ISO on the deploy server. |
| `media.vme_iso_path` | str |  | Path of HPE's VM Essentials software ISO (holds the Manager image). Required with vme_manager. |
| `media.seed_mode` | str: `embedded`, `http` |  | How the answers reach the installer. Default embedded (in each host's ISO); http is not implemented. |
| `media.www_root` | str |  | Directory nginx serves the ISOs from. Default /srv/vme-stack/www. |
| `media.work_dir` | str |  | Scratch directory for ISO builds. Default /srv/vme-stack/work. |
| `media.port` | int |  | nginx port. Default 8080. |
| `media.url` | str |  | Base URL hosts and BMCs fetch the ISOs from. Default http://&lt;ansible_host&gt;:&lt;port&gt;. |

## An HVM host (group vars of hvm, or host vars of the host)

| Variable | Type | Required | What it is |
|---|---|---|---|
| `platform` | str: `manual`, `redfish` | yes | How the host boots its ISO: redfish through its BMC (iLO/iDRAC); manual: someone else boots it (e.g. VMs) from the printed URL. |
| `ansible_host` | str | yes | The host's static IP on the mgmt network. |
| `ansible_user` | str | yes | The admin user the install creates; the same on all hosts of a cluster. |
| `ansible_ssh_private_key_file` | str |  | SSH key to log in with; its public key is installed for the admin user. Default ~/.ssh/id_ed25519. |
| `hvm_admin_password` | str |  | *Secret.* Password of the admin user. Required for hosts in vme_clusters; one per cluster. |
| `hvm_ssh_keys` | list of str |  | Extra public keys (key lines) for the admin user. |
| `boot_disk` | raw |  | The disk to install on: auto (the smallest disk, default), a kernel name (/dev/sda), or installer match keys (serial, model, vendor; globs; e.g. {model: "*NS204i*"}). |
| `nic_layout` | str: `dedicated`, `shared` |  | Default for nics.layout: dedicated (mgmt bond + compute bond, default) or shared (one bond for both). |
| `nics` | dict |  | The host's network by NIC MAC addresses: bond0 for mgmt, bond1 for compute (dedicated). Or netplan + hpe_vm instead. |
| `nics.layout` | str: `dedicated`, `shared` |  | This host's layout. Default nic_layout. |
| `nics.mgmt` | list of str | yes | MAC addresses of the mgmt NICs (bond0). |
| `nics.compute` | list of str |  | MAC addresses of the compute NICs (bond1; dedicated layout). |
| `netplan` | dict |  | Raw netplan (the network: section) instead of nics; needs hpe_vm. |
| `hpe_vm` | dict |  | The interfaces HPE's cluster setup uses, with raw netplan. |
| `hpe_vm.mgmt_interface` | str | yes | Interface with the host's IP (e.g. bond0.100). |
| `hpe_vm.compute_interface` | str |  | Interface for VM traffic. Default: none (shared). |
| `storage` | dict |  | Raw installer storage config (autoinstall storage:) instead of boot_disk, e.g. software RAID. |
| `bmc` | dict |  | The host's BMC, for platform redfish. |
| `bmc.address` | str | yes | BMC address (IP or name). |
| `bmc.username` | str | yes | BMC user (best a vault reference). |
| `bmc.password` | str | yes | *Secret.* Its password. |
| `bmc.validate_certs` | bool |  | Check the BMC's TLS certificate. Default false. |
| `bmc.bios_setup` | bool |  | Set UEFI boot and Secure Boot off through Redfish before booting the ISO. Default false. |
| `bmc_auth` | str: `session`, `basic` |  | How Redfish logs in to the BMC. session (default): a session, with basic auth if the BMC refuses the session login (some older iDRAC firmware). basic: basic auth only, never a session attempt; for such BMCs, as each refused session login counts as a failed login and iDRAC IP blocking can then lock the controller out. Set for all hosts (all.vars), a group or a host. |

## Environment

| Variable | What it is |
|---|---|
| `VME_STACK_DEBUG` | `1`: more detail in the run, and a support bundle in `logs/` at the end (also after a failure). See [`ee/README.md`](../ee/README.md#logs-and-support-bundle). |
