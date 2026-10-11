#!/bin/bash
# Support bundle: state of the deploy server (read-only). Every item may fail;
# the bundle keeps what worked. Writes one .tar.gz and prints its path.
#   collect_deploy_server.sh <www_root>
www_root=${1:-/srv/vme-stack/www}
out=$(mktemp -d /tmp/vme-stack-collect.XXXXXX)
run() {  # run <file> <command...>: command line and output into <file>.txt
    local name=$1; shift
    { echo "\$ $*"; "$@"; } > "$out/$name.txt" 2>&1 || true
}
run os cat /etc/os-release
run uname uname -a
run uptime uptime
run df df -h
run findmnt findmnt
run fstab cat /etc/fstab
run www find "$www_root" -maxdepth 3 -ls
run nginx-config nginx -T
run nginx-status systemctl status nginx --no-pager
run packages sh -c 'dpkg -l 2>/dev/null | grep -Ei "nginx|xorriso|python3-netplan" || rpm -qa | grep -Ei "nginx|xorriso"'
run selinux sh -c 'getenforce 2>/dev/null || echo "no SELinux"'
run firewall sh -c 'firewall-cmd --list-all 2>/dev/null || ufw status verbose 2>/dev/null || echo "no firewalld/ufw"'
run journal-errors journalctl -p warning -b --no-pager -n 2000
mkdir -p "$out/logs"
cp /var/log/nginx/error.log "$out/logs/" 2>/dev/null || true
tail -n 2000 /var/log/nginx/access.log > "$out/logs/access.log" 2>/dev/null || true
tar -czf "$out.tar.gz" -C "$out" . && rm -rf "$out" && echo "$out.tar.gz"
