# vme-stack: a site file (site.yml) as Ansible inventory.
from __future__ import annotations

DOCUMENTATION = r"""
name: vme_site
short_description: vme-stack site file as inventory
description:
  - Reads a vme-stack site file (named C(site.yml) or C(*.site.yml)) and validates it
    against C(schemas/site.schema.json). Every schema error is listed at once.
  - Builds group C(hvm) (one host per C(hosts[]) entry) and C(deploy_server),
    and maps site fields onto the host variables the roles use. Cross-field rules (unique
    IP/MAC, IP inside the subnet, driver exists) are checked by the preflight role, not here.
  - The whole validated site is also exposed as C(vme_site).
  - Secrets are written in the site file as templates naming vault variables
    (C("{{ vault_x }}")). They are passed on as templates (trusted), so they resolve
    from the vault when a task uses them; C(vme_site) keeps them as plain text.
    C(secrets)/C(site_secrets) map each secret field to its value and
    C(secret_refs)/C(site_secret_refs) to its template, for preflight.
"""

import ipaddress
import json
import os
from pathlib import Path

from ansible.errors import AnsibleParserError
from ansible.template import trust_as_template

from ansible.plugins.inventory import BaseInventoryPlugin

SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "site.schema.json"

# Defaults the schema documents; applied here so roles get one value per variable.
DEFAULTS = {"hvm_admin_user": "hvmadmin", "boot_disk": "auto", "nic_layout": "dedicated"}
DEPLOY_DEFAULTS = {"name": "deploy", "www_root": "/srv/vme-stack/www", "work_dir": "/srv/vme-stack/work", "port": 8080}
SSH_OPTS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30"


def _secret(value):
    """A site value that may be a vault reference: trusted, so Ansible renders it on use."""
    return trust_as_template(value) if isinstance(value, str) else value


def _message(err):
    # A regex in an error message helps nobody; say what the field expects instead.
    if err.validator == "pattern" and "description" in err.schema:
        return f"{err.instance!r} is not valid: {err.schema['description']}"
    if err.validator == "oneOf" and isinstance(err.instance, dict) and "ip" in err.instance:
        return "network: give either nics, or netplan + hpe_vm (not both)"
    if err.validator == "oneOf" and err.absolute_path and err.absolute_path[-1] == "boot_disk":
        return (
            f"{err.instance!r} is not valid: 'auto', a kernel device name (/dev/sda), or "
            "installer match keys (serial, model, vendor, path, id_path, ssd, size), "
            "e.g. {model: '*NS204i*'}; /dev/disk/by-* paths do not work"
        )
    if err.validator == "not" and err.schema.get("not") == {}:
        return err.schema["description"]
    if err.validator == "not" and err.schema.get("not") == {"required": ["vcenter"]}:
        return "vcenter is only for clouds of type vmware"
    return err.message


def _path(err):
    out = ""
    for p in err.absolute_path:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else p)
    return out or "(top level)"


class InventoryModule(BaseInventoryPlugin):
    NAME = "vme_site"

    def verify_file(self, path):
        name = os.path.basename(path)
        return super().verify_file(path) and (
            name in ("site.yml", "site.yaml") or name.endswith((".site.yml", ".site.yaml"))
        )

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache)
        site = self.loader.load_from_file(path, cache="none")
        # Round-trip through JSON: plain types for jsonschema and for the host vars.
        site = json.loads(json.dumps(site))
        self._validate(site, path)

        base = os.path.dirname(os.path.abspath(path))
        access = site["access"]
        key = os.path.normpath(os.path.join(base, os.path.expanduser(access["ssh_private_key"])))
        net = site["network"]
        dep = {**DEPLOY_DEFAULTS, **site["deploy_server"]}

        names = [h["name"] for h in site["hosts"]] + [dep["name"]]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise AnsibleParserError(f"{path}: names used more than once (hosts/deploy_server): {', '.join(dupes)}")

        conn = {"ansible_ssh_private_key_file": key}
        if access.get("jump"):
            conn["ansible_ssh_common_args"] = (
                f'{SSH_OPTS} -o ServerAliveCountMax=6 -o ProxyCommand="ssh {SSH_OPTS} -i {key} '
                f'-o IdentitiesOnly=yes -W %h:%p {access["jump"]}"'
            )

        self.inventory.add_group("hvm")
        self.inventory.add_group("deploy_server")
        self.inventory.set_variable("all", "vme_site", site)
        self.inventory.set_variable("all", "vme_site_file", os.path.abspath(path))

        # Secrets of the whole site (Manager, vCenters): field -> value (rendered on
        # use) and field -> the template as written, for preflight's messages.
        site_secret_refs = {}
        if "vme_manager" in site:
            m = site["vme_manager"]
            for k in ("admin_password", "license_key", "ssh_private_key", "ssh_public_key"):
                if k in m:
                    site_secret_refs[f"vme_manager.{k}"] = m[k]
            self.inventory.add_group("vme_manager")
            self.inventory.set_variable(
                "all",
                "vme_manager",
                {
                    "host": m["host"],
                    "ip": m["ip"],
                    "hostname": m["hostname"],
                    "url": m.get("url", f"https://{m['ip']}"),
                    "size": m.get("size", "S"),
                    "admin_user": m.get("admin_user", "vmeadmin"),
                    "admin_password": _secret(m["admin_password"]),
                    "netmask": str(ipaddress.ip_network(f"0.0.0.0/{net['prefix']}").netmask),
                    "gateway": net["gateway"],
                    "dns": net["dns"],
                    "compute_vlans": net.get("compute_vlans", []),
                    "vme_iso": site["media"].get("vme_iso"),
                    "tenant": m.get("tenant", site["site"]),
                    "email": m.get("email", f"{m.get('admin_user', 'vmeadmin')}@{net['domain']}"),
                    "license_key": _secret(m.get("license_key")),
                    "datastore": m.get("datastore"),
                    "autostart": m.get("autostart", False),
                    "ssh_private_key": _secret(m.get("ssh_private_key")),
                    "ssh_public_key": _secret(m.get("ssh_public_key")),
                },
            )

        # Manager objects: groups, clouds (hvm/vmware) and HVM clusters, by name.
        clouds = {c["name"]: c for c in site.get("vme_clouds", [])}
        self.inventory.set_variable("all", "vme_groups", [g["name"] for g in site.get("vme_groups", [])])
        self.inventory.set_variable(
            "all",
            "vme_clouds",
            [
                {
                    "name": c["name"],
                    "type": c["type"],
                    "groups": c["groups"],
                    **(
                        {
                            "vcenter": {
                                "url": c["vcenter"]["url"],
                                "datacenter": c["vcenter"]["datacenter"],
                                "cluster": c["vcenter"].get("cluster", ""),
                                "import_existing": c["vcenter"].get("import_existing", True),
                            }
                        }
                        if c["type"] == "vmware"
                        else {}
                    ),
                }
                for c in site.get("vme_clouds", [])
            ],
        )
        # vCenter logins by cloud name, kept out of vme_clouds (loop items get printed).
        vcenter_logins = {}
        for c in site.get("vme_clouds", []):
            if c["type"] == "vmware":
                vcenter_logins[c["name"]] = {k: _secret(c["vcenter"][k]) for k in ("username", "password")}
                for k in ("username", "password"):
                    site_secret_refs[f"vme_clouds[{c['name']}].vcenter.{k}"] = c["vcenter"][k]
        self.inventory.set_variable("all", "vme_vcenter_logins", vcenter_logins)
        self.inventory.set_variable("all", "site_secret_refs", site_secret_refs)
        self.inventory.set_variable(
            "all",
            "site_secrets",
            {k: _secret(v) for k, v in site_secret_refs.items()},
        )
        self.inventory.set_variable(
            "all",
            "vme_clusters",
            [
                {
                    "name": c["name"],
                    "cloud": c["cloud"],
                    "group": c.get("group") or (clouds[c["cloud"]]["groups"][0] if c["cloud"] in clouds else ""),
                    "hosts": c["hosts"],
                    "layout": c.get("layout", ""),  # empty: the newest standard HVM layout
                    "compute_vlans": net.get("compute_vlans", []),
                    "datastores": c.get("datastores", []),
                }
                for c in site.get("vme_clusters", [])
            ],
        )

        self.inventory.add_host(dep["name"], group="deploy_server")
        if dep.get("connection", "ssh") == "local":
            # The playbook runs on the deploy server itself.
            dep_vars = {"ansible_connection": "local", "ansible_host": dep["address"]}
        else:
            dep_vars = {**conn, "ansible_host": dep["address"], "ansible_user": dep["user"]}
        for k, v in dep_vars.items():
            self.inventory.set_variable(dep["name"], k, v)

        for h in site["hosts"]:
            s = {
                **DEFAULTS,
                **site["defaults"],
                **{k: v for k, v in h.items() if k in DEFAULTS or k in ("platform", "ssh_keys", "hvm_admin_password")},
            }
            secret_refs = {}
            if "hvm_admin_password" in s:
                secret_refs["hvm_admin_password"] = s["hvm_admin_password"]
            hv = {
                **conn,
                "ansible_host": h["ip"],
                "ansible_user": s["hvm_admin_user"],
                "platform": s["platform"],
                "admin_user": s["hvm_admin_user"],
                "admin_password": _secret(s.get("hvm_admin_password")),
                "ssh_keys": s["ssh_keys"],
                "boot_disk": s["boot_disk"],
                "ip": h["ip"],
                "prefix": net["prefix"],
                "gateway": net["gateway"],
                "dns": net["dns"],
                "ntp_servers": net["ntp"],
                "domain": net["domain"],
                "mgmt_vlan": net.get("mgmt_vlan", 0),
                "timezone": net.get("timezone", "UTC"),
                "bond_mode": net.get("bond_mode", "active-backup"),
                "seed_mode": site["media"].get("seed_mode", "embedded"),
                # Media: built and served by the deploy server, which is also where
                # SSH banners, DNS and NTP are probed from (it sits on the mgmt network).
                "deploy_host": dep["name"],
                "probe_from": dep["name"],
                "hvm_src_iso": site["media"]["hvm_iso"],
                "media_www_root": dep["www_root"],
                "media_work_dir": dep["work_dir"],
                "media_port": dep["port"],
                "media_url": dep.get("media_url", f"http://{dep['address']}:{dep['port']}"),
            }
            # Network: generated from a nics layout, or raw netplan (edge cases).
            # Either way the roles get mgmt_interface/compute_interface (HPE's -m/-c).
            if "nics" in h:
                layout = h["nics"].get("layout", s["nic_layout"])
                hv["nics"] = {
                    "layout": layout,
                    "mgmt": h["nics"]["mgmt"],
                    **({"compute": h["nics"]["compute"]} if "compute" in h["nics"] else {}),
                }
                vlan = net.get("mgmt_vlan", 0)
                hv["mgmt_interface"] = f"bond0.{vlan}" if layout == "dedicated" and vlan > 0 else "bond0"
                hv["compute_interface"] = "bond1" if layout == "dedicated" else ""
            else:
                hv["netplan"] = h["netplan"]
                hv["mgmt_interface"] = h["hpe_vm"]["mgmt_interface"]
                hv["compute_interface"] = h["hpe_vm"].get("compute_interface", "")
            # Disk: boot_disk (auto or installer match keys), or a raw storage section.
            if "storage" in h:
                hv["storage"] = h["storage"]
            if "proxy" in net:
                hv["proxy"] = net["proxy"]
            if "bmc" in h:
                # The login stays out of the bmc dict (task names and labels show it).
                hv["bmc"] = {k: v for k, v in h["bmc"].items() if k not in ("username", "password")}
                hv["bmc_username"] = _secret(h["bmc"]["username"])
                hv["bmc_password"] = _secret(h["bmc"]["password"])
                secret_refs["bmc.username"] = h["bmc"]["username"]
                secret_refs["bmc.password"] = h["bmc"]["password"]
            hv["secret_refs"] = secret_refs
            hv["secrets"] = {k: _secret(v) for k, v in secret_refs.items()}

            self.inventory.add_host(h["name"], group="hvm")
            if site.get("vme_manager", {}).get("host") == h["name"]:
                self.inventory.add_host(h["name"], group="vme_manager")
            for k, v in hv.items():
                self.inventory.set_variable(h["name"], k, v)

    def _validate(self, site, path):
        try:
            from jsonschema import Draft202012Validator
        except ImportError as e:
            raise AnsibleParserError(
                "vme_site needs python 'jsonschema' on the controller (pip install jsonschema)"
            ) from e
        validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
        errors = sorted(validator.iter_errors(site), key=lambda e: list(map(str, e.absolute_path)))
        if errors:
            # dict: drop duplicates (if/else schema branches can report the same thing twice)
            lines = "\n".join(dict.fromkeys(f"  - {_path(e)}: {_message(e)}" for e in errors))
            raise AnsibleParserError(f"{path} does not match {SCHEMA.name} ({len(errors)} problems):\n{lines}")
