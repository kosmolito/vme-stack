#!/bin/bash
# Support bundle: state of an HVM host (read-only). Every item may fail; the
# bundle keeps what worked. Writes one .tar.gz and prints its path.
out=$(mktemp -d /tmp/vme-stack-collect.XXXXXX)
run() {  # run <file> <command...>: command line and output into <file>.txt
    local name=$1; shift
    { echo "\$ $*"; "$@"; } > "$out/$name.txt" 2>&1 || true
}
run os cat /etc/os-release
run uname uname -a
run uptime uptime
run install-id cat /etc/vme-stack/install-id
run packages sh -c 'dpkg -l | grep -Ei "hpe-vm|morpheus|openvswitch|libvirt|qemu-system|chrony|timesyncd|cloud-init|^ii  linux-image"'
# network
run ip-addr ip -d addr
run ip-route ip route
run ip-link ip -d link
run ovs ovs-vsctl show
run networkctl networkctl status --all --no-pager
run resolvectl resolvectl status
run netplan-get netplan get
run sshd-dropins sh -c 'grep -H . /etc/ssh/sshd_config.d/*'
# time
run timedatectl timedatectl
run timesync timedatectl timesync-status
run chrony sh -c 'chronyc tracking && chronyc sources -v'
# disks
run lsblk lsblk -o NAME,SIZE,TYPE,MODEL,SERIAL,MOUNTPOINTS
run lvm sh -c 'pvs; vgs; lvs'
run df df -h
run findmnt findmnt
# virtualisation (the Manager host and cluster members)
run virsh-list virsh list --all
run virsh-pools virsh pool-list --all --details
run pacemaker sh -c 'pcs status 2>/dev/null || echo "no pcs"'
# services and journal
run systemctl-failed systemctl --failed --no-pager
run journal-errors journalctl -p warning -b --no-pager -n 3000
run journal-networkd journalctl -u systemd-networkd -b --no-pager -n 1000
run cloud-init-status cloud-init status --long
mkdir -p "$out/logs"
cp -a /var/log/installer "$out/logs/" 2>/dev/null || true
cp /var/log/cloud-init.log /var/log/cloud-init-output.log "$out/logs/" 2>/dev/null || true
cp /var/log/vme-stack-hpe-vm-install.log /var/log/vme-stack-hpe-vm-install.log.rc "$out/logs/" 2>/dev/null || true
# Files under /etc/netplan (the IP config as written; secrets are none)
mkdir -p "$out/netplan" && cp -a /etc/netplan/. "$out/netplan/" 2>/dev/null || true
tar -czf "$out.tar.gz" -C "$out" . && rm -rf "$out" && echo "$out.tar.gz"
