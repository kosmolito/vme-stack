#!/bin/bash
# Example site task (vme_manager.tasks[].file): a read-only summary of a Linux VM or host.
echo "== $(hostname -f 2>/dev/null || hostname)  $(date -Is)"
uptime
echo "== OS";      grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release
echo "== disks";   df -hT -x tmpfs -x devtmpfs
echo "== memory";  free -h
echo "== network"; ip -br addr
