# vme-stack: rules for a site file that JSON Schema cannot express.
# Used by the preflight role: {{ vme_site | vme_site_errors(roles_dir) }} -> list of problems.
# Also newest_hvm_layout (vme_clusters): the default cluster layout code.
from __future__ import annotations

import ipaddress
import os
import re
from collections import Counter

REDFISH_PLATFORMS = {"redfish"}
IMPLEMENTED_SEED_MODES = {"embedded"}


def _dupes(values):
    return sorted(v for v, n in Counter(values).items() if n > 1)


def _host_macs(h):
    if "nics" in h:
        return h["nics"]["mgmt"] + h["nics"].get("compute", [])
    eths = h["netplan"].get("ethernets") or {}
    return [
        e["match"]["macaddress"]
        for e in eths.values()
        if isinstance(e, dict) and isinstance(e.get("match"), dict) and "macaddress" in e["match"]
    ]


def _netplan_errors(h):
    """What HPE's cluster join needs from a raw netplan (syntax is checked by netplan itself in preflight)."""
    errs = []
    np, hv = h["netplan"], h["hpe_vm"]
    defs = {}
    for kind in ("ethernets", "bonds", "vlans", "bridges"):
        for name, d in (np.get(kind) or {}).items():
            defs[name] = (kind, d if isinstance(d, dict) else {})
    mgmt, compute = hv["mgmt_interface"], hv.get("compute_interface")
    if mgmt not in defs:
        return [f"hpe_vm.mgmt_interface '{mgmt}' is not defined in netplan"]
    kind, md = defs[mgmt]
    if kind == "bridges":
        errs.append(
            f"hpe_vm.mgmt_interface '{mgmt}' is a bridge; hpe-vm needs an ethernet, bond or VLAN "
            "(it builds the OVS bridge itself)"
        )
    if md.get("dhcp4") in (True, "true", "yes", "on"):
        errs.append(f"hpe_vm.mgmt_interface '{mgmt}' uses DHCP; hpe-vm needs a static address")
    addrs = [str(a).split("/")[0] for a in md.get("addresses") or []]
    if h["ip"] not in addrs:
        errs.append(f"ip {h['ip']} is not among the addresses of '{mgmt}' in netplan ({', '.join(addrs) or 'none'})")
    if compute:
        if compute not in defs:
            errs.append(f"hpe_vm.compute_interface '{compute}' is not defined in netplan")
        elif compute == mgmt:
            errs.append("hpe_vm.compute_interface equals mgmt_interface")
        elif kind == "vlans" and md.get("link") == compute:
            errs.append(
                f"hpe_vm.compute_interface '{compute}' is the parent of mgmt VLAN '{mgmt}'; "
                "hpe-vm would move it into the compute OVS bridge and cut mgmt off"
            )
    return errs


def vme_site_errors(site, roles_dir):
    """Return every cross-field problem in a schema-valid site, as readable strings.

    roles_dir is searched for boot drivers: boot_<platform>/tasks/main.yml.
    """
    drivers = {
        d[5:]
        for d in os.listdir(roles_dir)
        if d.startswith("boot_") and os.path.isfile(os.path.join(roles_dir, d, "tasks", "main.yml"))
    }
    errs = []
    net = site["network"]
    hosts = site["hosts"]
    defaults = site["defaults"]

    subnet = ipaddress.ip_interface(f"{net['gateway']}/{net['prefix']}").network
    if ipaddress.ip_address(net["gateway"]) in (subnet.network_address, subnet.broadcast_address):
        errs.append(f"network.gateway {net['gateway']} is the network or broadcast address of {subnet}")

    seed_mode = site["media"].get("seed_mode", "embedded")
    if seed_mode not in IMPLEMENTED_SEED_MODES:
        errs.append(
            f"media.seed_mode '{seed_mode}' is not implemented yet (use: {', '.join(sorted(IMPLEMENTED_SEED_MODES))})"
        )

    for ip in _dupes([h["ip"] for h in hosts]):
        errs.append(f"IP {ip} is used by more than one host")
    taken = {net["gateway"]: "the gateway", site["deploy_server"]["address"]: "the deploy server"}
    for h in hosts:
        if h["ip"] in taken:
            errs.append(f"hosts[{h['name']}]: ip {h['ip']} is {taken[h['ip']]}")

    macs = [m.lower() for h in hosts for m in _host_macs(h)]
    for m in _dupes(macs):
        errs.append(f"MAC {m} is listed more than once")

    for h in hosts:
        n = f"hosts[{h['name']}]"
        platform = h.get("platform", defaults["platform"])

        ip = ipaddress.ip_address(h["ip"])
        if ip not in subnet or ip in (subnet.network_address, subnet.broadcast_address):
            errs.append(f"{n}: ip {h['ip']} is not a usable address in {subnet}")

        if platform not in drivers:
            errs.append(
                f"{n}: platform '{platform}' has no driver yet (available: {', '.join(sorted(drivers)) or 'none'})"
            )

        if "nics" in h:
            # NIC layout rules (spec: Decisions log, "NIC layouts").
            layout = h["nics"].get("layout", defaults.get("nic_layout", "dedicated"))
            if layout == "dedicated" and not h["nics"].get("compute"):
                errs.append(f"{n}: nic layout 'dedicated' needs nics.compute MACs (or use layout 'shared')")
            if layout == "shared" and "compute" in h["nics"]:
                errs.append(f"{n}: nic layout 'shared' takes mgmt MACs only; remove nics.compute")
        else:
            errs += [f"{n}: {e}" for e in _netplan_errors(h)]

        if "storage" in h and "boot_disk" in h:
            errs.append(f"{n}: give either boot_disk or storage, not both")

        if platform in REDFISH_PLATFORMS and "bmc" not in h:
            errs.append(f"{n}: platform '{platform}' needs a bmc block")
        if platform == "manual" and "bmc" in h:
            errs.append(f"{n}: platform 'manual' does not use a bmc block; remove it or use platform redfish")

    mgr = site.get("vme_manager")
    if mgr:
        names = {h["name"] for h in hosts}
        if mgr["host"] not in names:
            errs.append(f"vme_manager.host '{mgr['host']}' is not one of the hosts")
        if "vme_iso" not in site["media"]:
            errs.append("vme_manager needs media.vme_iso (HPE's VM Essentials software ISO on the deploy server)")
        mip = ipaddress.ip_address(mgr["ip"])
        if mip not in subnet or mip in (subnet.network_address, subnet.broadcast_address):
            errs.append(f"vme_manager.ip {mgr['ip']} is not a usable address in {subnet}")
        if mgr["ip"] in taken or mgr["ip"] in {h["ip"] for h in hosts}:
            errs.append(f"vme_manager.ip {mgr['ip']} is already used (gateway, deploy server or a host)")
        if mgr["hostname"] in names:
            errs.append(f"vme_manager.hostname '{mgr['hostname']}' is also a host name")

    # Manager objects: groups, clouds, HVM clusters (referenced by name).
    groups = [g["name"] for g in site.get("vme_groups", [])]
    clouds = site.get("vme_clouds", [])
    clusters = site.get("vme_clusters", [])
    if (groups or clouds or clusters) and not mgr:
        errs.append("vme_groups, vme_clouds and vme_clusters need vme_manager (the Manager creates them)")
    for kind, names in (
        ("vme_groups", groups),
        ("vme_clouds", [c["name"] for c in clouds]),
        ("vme_clusters", [c["name"] for c in clusters]),
    ):
        for n in _dupes(names):
            errs.append(f"{kind}: name '{n}' is used more than once")
    for c in clouds:
        for g in c["groups"]:
            if g not in groups:
                errs.append(f"vme_clouds '{c['name']}': group '{g}' is not one of vme_groups")
    cloud_by = {c["name"]: c for c in clouds}
    by_name = {h["name"]: h for h in hosts}
    cluster_of = {}
    for cl in clusters:
        label = f"vme_clusters '{cl['name']}'"
        cloud = cloud_by.get(cl["cloud"])
        if not cloud:
            errs.append(f"{label}: cloud '{cl['cloud']}' is not one of vme_clouds")
        elif cloud["type"] != "hvm":
            errs.append(f"{label}: cloud '{cl['cloud']}' is type {cloud['type']}; HVM clusters need type hvm")
        elif cl.get("group") and cl["group"] not in cloud["groups"]:
            errs.append(
                f"{label}: group '{cl['group']}' is not one of cloud '{cl['cloud']}' groups: "
                + ", ".join(cloud["groups"])
            )
        members = cl["hosts"]
        for n in members:
            if n not in by_name:
                errs.append(f"{label}: host '{n}' is not one of the hosts")
            elif n in cluster_of:
                errs.append(f"{label}: host '{n}' is already in cluster '{cluster_of[n]}'")
            else:
                cluster_of[n] = cl["name"]
        ifaces = {n: _interfaces(by_name[n], net, defaults) for n in members if n in by_name}
        if len(set(ifaces.values())) > 1:
            errs.append(
                f"{label}: all hosts need the same mgmt/compute interface names (HPE requirement): "
                + ", ".join(f"{n}={m}/{c or '-'}" for n, (m, c) in sorted(ifaces.items()))
            )
        present = [by_name[n] for n in members if n in by_name]
        if any(not h.get("admin_password", defaults.get("admin_password")) for h in present):
            errs.append(f"{label}: the hosts need admin_password (a vault variable); the Manager logs in with it")
        if len({h.get("admin_user", defaults.get("admin_user", "hvmadmin")) for h in present}) > 1:
            errs.append(f"{label}: all hosts need the same admin_user (the Manager uses one SSH login)")
        # The cluster API takes one SSH password for all hosts (the first host's).
        pw_vars = {h["name"]: h.get("admin_password", defaults.get("admin_password")) for h in present}
        if len(set(pw_vars.values())) > 1:
            errs.append(
                f"{label}: all hosts need the same admin_password vault variable (the Manager uses one SSH login): "
                + ", ".join(f"{n}={v or '-'}" for n, v in sorted(pw_vars.items()))
            )
        ds = cl.get("datastores", [])
        for n in _dupes([d["name"] for d in ds]):
            errs.append(f"{label}: datastore name '{n}' is used more than once")
        if sum(1 for d in ds if d.get("default")) > 1:
            errs.append(f"{label}: only one datastore can be the default (image target)")
        if any(c for _, c in ifaces.values()) and not net.get("compute_vlans"):
            errs.append(f"{label}: network.compute_vlans is required when the hosts have a compute interface")
    if mgr and clusters and not (mgr.get("ssh_private_key") and mgr.get("ssh_public_key")):
        errs.append("vme_clusters need vme_manager.ssh_private_key and ssh_public_key (the Manager's key to the hosts)")
    if mgr and mgr.get("datastore"):
        home = next((cl for cl in clusters if mgr["host"] in cl["hosts"]), None)
        if not home:
            errs.append(f"vme_manager.datastore needs vme_manager.host '{mgr['host']}' in one of vme_clusters")
        elif mgr["datastore"] not in [d["name"] for d in home.get("datastores", [])]:
            errs.append(f"vme_manager.datastore '{mgr['datastore']}' is not one of cluster '{home['name']}' datastores")

    return errs


def _interfaces(h, net, defaults):
    """(mgmt_interface, compute_interface) as the inventory plugin derives them."""
    if "nics" in h:
        layout = h["nics"].get("layout", defaults.get("nic_layout", "dedicated"))
        vlan = net.get("mgmt_vlan", 0)
        mgmt = f"bond0.{vlan}" if layout == "dedicated" and vlan > 0 else "bond0"
        return mgmt, ("bond1" if layout == "dedicated" else "")
    return h["hpe_vm"]["mgmt_interface"], h["hpe_vm"].get("compute_interface", "")


HVM_LAYOUT = re.compile(r"^mvm-(\d+)\.(\d+)-ubuntu-24\.04-std-morpheus-amd64$")


def newest_hvm_layout(codes):
    """The newest standard HVM cluster layout code among codes ('' if none):
    mvm-1.2-... on VME 8.1, mvm-1.3-... on 9.0."""
    hvm = [(tuple(map(int, m.groups())), c) for c in codes if (m := HVM_LAYOUT.match(c or ""))]
    return max(hvm)[1] if hvm else ""


class FilterModule:
    def filters(self):
        return {"vme_site_errors": vme_site_errors, "newest_hvm_layout": newest_hvm_layout}
