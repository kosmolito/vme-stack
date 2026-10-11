# vme-stack: rules for a site inventory that per-variable checks (roles/preflight/
# meta/argument_specs.yml) cannot express: formats, uniqueness, references.
# Used by the preflight role: {{ view | vme_site_errors(roles_dir) }} -> list of problems,
# with view assembled from the inventory by preflight (see its "Site view" task).
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


NAME = re.compile(r"^(?![0-9]+$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
FQDN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAC = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
SSH_KEY = re.compile(r"^(ssh-(ed25519|rsa)|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/=]+( .*)?$")
BOOT_DISK_KEYS = {"serial", "model", "vendor", "path", "id_path", "ssd", "size"}


def _is_ipv4(v):
    try:
        return isinstance(ipaddress.ip_address(str(v)), ipaddress.IPv4Address)
    except ValueError:
        return False


def _usable(ip, subnet):
    a = ipaddress.ip_address(ip)
    return a in subnet and a not in (subnet.network_address, subnet.broadcast_address)


def _format_errors(site):
    """Formats of the site-wide values (types and required keys: argument specs)."""
    errs = []
    net, media = site["network"], site["media"]
    if not NAME.match(str(site["site"])):
        errs.append(f"site '{site['site']}': lowercase letters, digits and hyphens (a host label)")
    if not FQDN.match(str(net["domain"])):
        errs.append(f"network.domain '{net['domain']}' is not a DNS domain like example.com")
    for k in ("gateway",):
        if not _is_ipv4(net[k]):
            errs.append(f"network.{k} '{net[k]}' is not an IPv4 address")
    if not 8 <= int(net["prefix"]) <= 30:
        errs.append(f"network.prefix {net['prefix']} is not between 8 and 30")
    if not 0 <= int(net.get("mgmt_vlan", 0)) <= 4094:
        errs.append(f"network.mgmt_vlan {net['mgmt_vlan']} is not between 0 and 4094")
    errs += [f"network.dns '{d}' is not an IPv4 address" for d in net["dns"] if not _is_ipv4(d)]
    errs += [
        f"network.ntp '{n}' is neither an IPv4 address nor a host name"
        for n in net["ntp"]
        if not (_is_ipv4(n) or FQDN.match(str(n)))
    ]
    errs += [
        f"network.compute_vlans {v} is not between 1 and 4094"
        for v in net.get("compute_vlans", [])
        if not 1 <= int(v) <= 4094
    ]
    if net.get("proxy") and not re.match(r"^https?://\S+$", net["proxy"]):
        errs.append(f"network.proxy '{net['proxy']}' is not an http(s) URL")
    if net.get("timezone") and not re.match(r"^[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}$", net["timezone"]):
        errs.append(f"network.timezone '{net['timezone']}' is not an IANA time zone like Europe/Stockholm")
    for k in ("hvm_iso", "vme_iso"):
        if k in media and not re.match(r"^/.+\.iso$", str(media[k])):
            errs.append(f"media.{k} '{media[k]}' is not an absolute path to an .iso file")
    for k in ("www_root", "work_dir"):
        if k in media and not str(media[k]).startswith("/"):
            errs.append(f"media.{k} '{media[k]}' is not an absolute path")
    if "port" in media and not 1 <= int(media["port"]) <= 65535:
        errs.append(f"media.port {media['port']} is not a port")
    if media.get("url") and not re.match(r"^https?://\S+[^/]$", media["url"]):
        errs.append(f"media.url '{media['url']}' is not an http(s) URL without a trailing slash")
    if site.get("ssh_jump") and not re.match(r"^[a-z_][a-z0-9_.-]*@[^\s@]+$", site["ssh_jump"]):
        errs.append(f"ssh_jump '{site['ssh_jump']}' is not user@host")
    mgr = site.get("vme_manager")
    if mgr:
        if not _is_ipv4(mgr["ip"]):
            errs.append(f"vme_manager.ip '{mgr['ip']}' is not an IPv4 address")
        if not NAME.match(str(mgr["hostname"])):
            errs.append(f"vme_manager.hostname '{mgr['hostname']}' is not a host label")
        if mgr.get("url") and not re.match(r"^https://[^\s/]+$", mgr["url"]):
            errs.append(f"vme_manager.url '{mgr['url']}' is not https://<name or IP> (no path)")
        if not USER.match(str(mgr.get("admin_user", "vmeadmin"))):
            errs.append(f"vme_manager.admin_user '{mgr['admin_user']}' is not a Linux user name")
        if mgr.get("email") and not re.match(r"^[^@\s]+@[^@\s]+$", mgr["email"]):
            errs.append(f"vme_manager.email '{mgr['email']}' is not an email address")
        if mgr.get("ssh_public_key") and not SSH_KEY.match(mgr["ssh_public_key"]):
            errs.append("vme_manager.ssh_public_key is not an OpenSSH public key line")
    for c in site.get("vme_clouds", []):
        url = (c.get("vcenter") or {}).get("url")
        if url and not re.match(r"^https://[^\s/]+(/\S*)?$", url):
            errs.append(f"vme_clouds '{c['name']}': vcenter.url '{url}' is not an https URL")
    for cl in site.get("vme_clusters", []):
        for d in cl.get("datastores", []):
            if not str(d["path"]).startswith("/"):
                errs.append(f"vme_clusters '{cl['name']}': datastore '{d['name']}' path is not absolute")
    return errs


def _boot_disk_errors(n, bd):
    if bd in (None, "auto"):
        return []
    if isinstance(bd, str):
        if re.match(r"^/dev/(?!disk/)[^\s/]+$", bd):
            return []
        return [
            f"{n}: boot_disk '{bd}' is not auto, a kernel device name (/dev/sda) or installer match keys "
            "(/dev/disk/by-* paths do not work in the installer)"
        ]
    if isinstance(bd, dict) and bd:
        errs = [
            f"{n}: boot_disk key '{k}' is not one of {', '.join(sorted(BOOT_DISK_KEYS))}"
            for k in bd
            if k not in BOOT_DISK_KEYS
        ]
        if "size" in bd and bd["size"] not in ("smallest", "largest"):
            errs.append(f"{n}: boot_disk.size is smallest or largest")
        if "path" in bd and str(bd["path"]).startswith("/dev/disk/"):
            errs.append(f"{n}: boot_disk.path '{bd['path']}': /dev/disk/by-* paths do not work in the installer")
        return errs
    return [f"{n}: boot_disk is auto, a kernel device name or installer match keys"]


def vme_site_errors(site, roles_dir):
    """Return every problem of a site inventory that the argument specs do not catch.

    site is the view preflight assembles: the site-wide variables plus 'hosts' (per
    HVM host its resolved values), 'deploy' (the members of group deploy_server) and
    'manager_hosts' (the members of group vme_manager). Passwords only as hashes.
    roles_dir is searched for boot drivers: boot_<platform>/tasks/main.yml.
    """
    drivers = {
        d[5:]
        for d in os.listdir(roles_dir)
        if d.startswith("boot_") and os.path.isfile(os.path.join(roles_dir, d, "tasks", "main.yml"))
    }
    errs = _format_errors(site)
    net = site["network"]
    hosts = site["hosts"]

    if len(site["deploy"]) != 1:
        errs.append(f"group deploy_server needs exactly one host (has {len(site['deploy'])})")
    for d in site["deploy"]:
        if not d["local"] and not (d["user"] and d["key"]):
            errs.append(
                f"deploy server {d['name']}: needs ansible_user and ansible_ssh_private_key_file "
                "(or ansible_connection: local)"
            )
    if not hosts:
        errs.append("group hvm has no hosts")

    if errs and not _is_ipv4(net["gateway"]):
        return errs
    subnet = ipaddress.ip_interface(f"{net['gateway']}/{net['prefix']}").network
    if ipaddress.ip_address(net["gateway"]) in (subnet.network_address, subnet.broadcast_address):
        errs.append(f"network.gateway {net['gateway']} is the network or broadcast address of {subnet}")

    seed_mode = site["media"].get("seed_mode", "embedded")
    if seed_mode not in IMPLEMENTED_SEED_MODES:
        errs.append(
            f"media.seed_mode '{seed_mode}' is not implemented yet (use: {', '.join(sorted(IMPLEMENTED_SEED_MODES))})"
        )

    good_ip = [h for h in hosts if _is_ipv4(h["ip"])]
    for h in hosts:
        if h not in good_ip:
            errs.append(f"{h['name']}: ansible_host '{h['ip']}' is not an IPv4 address (the host's static IP)")
    for ip in _dupes([h["ip"] for h in good_ip]):
        errs.append(f"IP {ip} is used by more than one host")
    taken = {net["gateway"]: "the gateway", **{d["address"]: "the deploy server" for d in site["deploy"]}}
    for h in good_ip:
        if h["ip"] in taken:
            errs.append(f"{h['name']}: ip {h['ip']} is {taken[h['ip']]}")

    macs = [m.lower() for h in hosts for m in _host_macs(h)]
    for m in _dupes(macs):
        errs.append(f"MAC {m} is listed more than once")

    for h in hosts:
        n = h["name"]
        if not NAME.match(n):
            errs.append(f"{n}: the inventory name becomes the hostname: lowercase letters, digits, hyphens")
        if h in good_ip and not _usable(h["ip"], subnet):
            errs.append(f"{n}: ip {h['ip']} is not a usable address in {subnet}")
        if h["platform"] not in drivers:
            errs.append(
                f"{n}: platform '{h['platform']}' has no driver (available: {', '.join(sorted(drivers)) or 'none'})"
            )
        if not USER.match(str(h["admin_user"])):
            errs.append(f"{n}: ansible_user '{h['admin_user']}' is not a Linux user name")
        errs += [
            f"{n}: hvm_ssh_keys entry is not an OpenSSH public key line: {k[:30]}..."
            for k in h["ssh_keys"]
            if not SSH_KEY.match(k)
        ]
        errs += _boot_disk_errors(n, h.get("boot_disk"))

        has_nics, has_netplan = "nics" in h, "netplan" in h
        if has_nics == has_netplan:
            errs.append(f"{n}: give either nics, or netplan + hpe_vm (not both, not neither)")
        elif has_nics:
            nics = h["nics"]
            for role in ("mgmt", "compute"):
                vals = nics.get(role) or []
                if len(vals) > 4:
                    errs.append(f"{n}: nics.{role} has more than 4 MACs")
                errs += [
                    f"{n}: nics.{role} '{m}' is not a MAC address like 52:54:00:aa:bb:cc"
                    for m in vals
                    if not MAC.match(str(m))
                ]
            # NIC layout rules (spec: Decisions log, "NIC layouts").
            if h["layout"] == "dedicated" and not nics.get("compute"):
                errs.append(f"{n}: nic layout 'dedicated' needs nics.compute MACs (or use layout 'shared')")
            if h["layout"] == "shared" and nics.get("compute"):
                errs.append(f"{n}: nic layout 'shared' takes mgmt MACs only; remove nics.compute")
        elif "hpe_vm" not in h:
            errs.append(f"{n}: netplan needs hpe_vm (mgmt_interface, compute_interface)")
        elif h["netplan"].get("version") != 2:
            errs.append(f"{n}: netplan needs version: 2")
        else:
            errs += [f"{n}: {e}" for e in _netplan_errors(h)]

        if h["platform"] in REDFISH_PLATFORMS and not h["bmc"]:
            errs.append(f"{n}: platform '{h['platform']}' needs a bmc block")
        if h["platform"] == "manual" and h["bmc"]:
            errs.append(f"{n}: platform 'manual' does not use a bmc block; remove it or use platform redfish")

    names = {h["name"] for h in hosts}
    mgr = site.get("vme_manager")
    mhosts = site["manager_hosts"]
    if mgr:
        if len(mhosts) != 1:
            errs.append(
                f"group vme_manager needs exactly one host, the one that runs the Manager VM (has {len(mhosts)})"
            )
        elif mhosts[0] not in names:
            errs.append(f"group vme_manager: '{mhosts[0]}' is not an HVM host (group hvm)")
        if "vme_iso" not in site["media"]:
            errs.append("vme_manager needs media.vme_iso (HPE's VM Essentials software ISO on the deploy server)")
        if _is_ipv4(mgr["ip"]):
            if not _usable(mgr["ip"], subnet):
                errs.append(f"vme_manager.ip {mgr['ip']} is not a usable address in {subnet}")
            if mgr["ip"] in taken or mgr["ip"] in {h["ip"] for h in hosts}:
                errs.append(f"vme_manager.ip {mgr['ip']} is already used (gateway, deploy server or a host)")
        if mgr["hostname"] in names:
            errs.append(f"vme_manager.hostname '{mgr['hostname']}' is also a host name")
    elif mhosts:
        errs.append("group vme_manager has a host but vme_manager (the Manager's settings) is not set")
    mgr_host = mhosts[0] if len(mhosts) == 1 else None

    # Manager objects: groups, clouds, HVM clusters (referenced by name).
    groups = [g["name"] for g in site.get("vme_groups", [])]
    clouds = site.get("vme_clouds", [])
    clusters = site.get("vme_clusters", [])
    if (groups or clouds or clusters) and not mgr:
        errs.append("vme_groups, vme_clouds and vme_clusters need vme_manager (the Manager creates them)")
    for kind, objs in (
        ("vme_groups", groups),
        ("vme_clouds", [c["name"] for c in clouds]),
        ("vme_clusters", [c["name"] for c in clusters]),
    ):
        for n in _dupes(objs):
            errs.append(f"{kind}: name '{n}' is used more than once")
    for c in clouds:
        for g in c["groups"]:
            if g not in groups:
                errs.append(f"vme_clouds '{c['name']}': group '{g}' is not one of vme_groups")
        if (c["type"] == "vmware") != ("vcenter" in c):
            errs.append(f"vme_clouds '{c['name']}': vcenter is needed for type vmware and only for it")
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
                errs.append(f"{label}: host '{n}' is not one of the HVM hosts")
            elif n in cluster_of:
                errs.append(f"{label}: host '{n}' is already in cluster '{cluster_of[n]}'")
            else:
                cluster_of[n] = cl["name"]
        present = [by_name[n] for n in members if n in by_name]
        ifaces = {h["name"]: (h["mgmt_interface"], h["compute_interface"]) for h in present}
        if len(set(ifaces.values())) > 1:
            errs.append(
                f"{label}: all hosts need the same mgmt/compute interface names (HPE requirement): "
                + ", ".join(f"{n}={m}/{c or '-'}" for n, (m, c) in sorted(ifaces.items()))
            )
        if any(not h["admin_password_hash"] for h in present):
            errs.append(f"{label}: the hosts need hvm_admin_password; the Manager logs in with it")
        if len({h["admin_user"] for h in present}) > 1:
            errs.append(f"{label}: all hosts need the same ansible_user (the Manager uses one SSH login)")
        # The cluster API takes one SSH password for all hosts (the first host's).
        by_pw = {}
        for h in present:
            by_pw.setdefault(h["admin_password_hash"], []).append(h["name"])
        if len(by_pw) > 1:
            errs.append(
                f"{label}: all hosts need the same hvm_admin_password (the Manager uses one SSH login); "
                "the same password on: " + " | ".join(", ".join(sorted(v)) for v in by_pw.values())
            )
        ds = cl.get("datastores", [])
        for n in _dupes([d["name"] for d in ds]):
            errs.append(f"{label}: datastore name '{n}' is used more than once")
        if sum(1 for d in ds if d.get("default")) > 1:
            errs.append(f"{label}: only one datastore can be the default (image target)")
        if any(h["compute_interface"] for h in present) and not net.get("compute_vlans"):
            errs.append(f"{label}: network.compute_vlans is required when the hosts have a compute interface")
    if mgr and clusters and not (mgr.get("has_private_key") and mgr.get("ssh_public_key")):
        errs.append("vme_clusters need vme_manager.ssh_private_key and ssh_public_key (the Manager's key to the hosts)")
    if mgr and mgr.get("datastore") and mgr_host:
        home = next((cl for cl in clusters if mgr_host in cl["hosts"]), None)
        if not home:
            errs.append(f"vme_manager.datastore needs the Manager host '{mgr_host}' in one of vme_clusters")
        elif mgr["datastore"] not in [d["name"] for d in home.get("datastores", [])]:
            errs.append(f"vme_manager.datastore '{mgr['datastore']}' is not one of cluster '{home['name']}' datastores")

    return errs


HVM_LAYOUT = re.compile(r"^mvm-(\d+)\.(\d+)-ubuntu-24\.04-std-morpheus-amd64$")


def newest_hvm_layout(codes):
    """The newest standard HVM cluster layout code among codes ('' if none):
    mvm-1.2-... on VME 8.1, mvm-1.3-... on 9.0."""
    hvm = [(tuple(map(int, m.groups())), c) for c in codes if (m := HVM_LAYOUT.match(c or ""))]
    return max(hvm)[1] if hvm else ""


class FilterModule:
    def filters(self):
        return {"vme_site_errors": vme_site_errors, "newest_hvm_layout": newest_hvm_layout}
