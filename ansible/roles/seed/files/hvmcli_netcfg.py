"""Make HPE's installer network config usable by its first-boot hvmcli (HVM OS 26.04).

HPE's installer saves the network only to installer-config; on first boot
configure_mgmt_ip.sh builds the virtSwitch vs0 from the first VLAN/bond/ethernet
in it, by interface name. Keeps only the management chain (VLAN -> bond -> ports),
names ports as the kernel does (ours are matched by MAC and renamed, which no
netplan does here) and turns a one-port bond into the port (hvmcli takes bonding
options only with two or more uplinks).

    python3 - <mgmt_interface> [config file]
"""

import os
import sys

import yaml

mgmt = sys.argv[1]
path = sys.argv[2] if len(sys.argv) > 2 else "/target/opt/HPE/installer-config/00-installer-config.yaml"
with open(path) as f:
    cfg = yaml.safe_load(f)
net = cfg["network"]
eths, bonds, vlans = (dict(net.get(k) or {}) for k in ("ethernets", "bonds", "vlans"))

by_mac = {}
for dev in os.listdir("/sys/class/net"):
    if os.path.exists(f"/sys/class/net/{dev}/device"):
        with open(f"/sys/class/net/{dev}/address") as f:
            by_mac[f.read().strip().lower()] = dev

vlan = dict(vlans[mgmt]) if mgmt in vlans else None
top = vlan["link"] if vlan else mgmt
bond = dict(bonds[top]) if top in bonds else None
members = bond.get("interfaces", []) if bond else [top]
if not members or any(m not in eths for m in members):
    sys.exit(f"vme-stack: {path}: {mgmt} does not lead to ethernets ({members})")

ports = {}
for m in members:
    e = dict(eths[m])
    mac = str((e.pop("match", None) or {}).get("macaddress", "")).lower()
    e.pop("set-name", None)
    real = by_mac.get(mac) if mac else m
    if not real:
        sys.exit(f"vme-stack: no NIC with MAC {mac} for {m}")
    ports[real] = e
names = list(ports)

out = {"version": net.get("version", 2), "ethernets": ports}
if bond and len(names) > 1:
    bond["interfaces"] = names
    out["bonds"] = {top: bond}
elif bond:
    bond.pop("interfaces", None)
    bond.pop("parameters", None)
    ports[names[0]].update(bond)
    top = names[0]
if vlan:
    vlan["link"] = top
    out["vlans"] = {mgmt: vlan}

with open(path, "w") as f:
    yaml.safe_dump({"network": out}, f, default_flow_style=False, sort_keys=False)
print(f"vme-stack: {path}: management on {mgmt} over {', '.join(names)}")
