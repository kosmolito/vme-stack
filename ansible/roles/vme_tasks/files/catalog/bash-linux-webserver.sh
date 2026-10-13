#!/bin/bash
# vme-stack catalog task bash-linux-webserver: nginx with a self-signed TLS
# certificate. Ubuntu/Debian (apt) and RHEL family (dnf). Re-runnable: an existing
# page and certificate are kept; delete /etc/nginx/tls to get a new certificate.
set -euo pipefail

fqdn=$(hostname -f 2>/dev/null || hostname)
short=$(hostname -s)
root=/var/www/site
tls=/etc/nginx/tls

echo "== packages (nginx, openssl, curl)"
if command -v apt-get >/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null
  apt-get install -y -qq nginx openssl curl >/dev/null
  rm -f /etc/nginx/sites-enabled/default        # its default_server would take port 80
else
  dnf install -y -q nginx openssl curl >/dev/null
fi

echo "== page"
mkdir -p "$root"
if [ ! -f "$root/index.html" ]; then
  printf '<!doctype html>\n<title>%s</title>\n<h1>%s</h1>\n<p>Served by nginx on %s (set up by vme-stack).</p>\n' \
    "$short" "$short" "$fqdn" > "$root/index.html"
fi

echo "== certificate"
mkdir -p "$tls"
if [ ! -f "$tls/site.crt" ]; then
  san="DNS:$fqdn"
  if [ "$short" != "$fqdn" ]; then san="$san,DNS:$short"; fi
  for ip in $(hostname -I); do san="$san,IP:$ip"; done
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=$fqdn" \
    -addext "subjectAltName=$san" -keyout "$tls/site.key" -out "$tls/site.crt" 2>/dev/null
  chmod 600 "$tls/site.key"
fi
openssl x509 -in "$tls/site.crt" -noout -subject -enddate -ext subjectAltName | sed 's/^/  /'

echo "== nginx"
cat > /etc/nginx/conf.d/vme-stack-site.conf <<CONF
# vme-stack catalog task bash-linux-webserver (rewritten on every run)
server {
    listen 80;
    listen [::]:80;
    return 301 https://\$host\$request_uri;
}
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    ssl_certificate     $tls/site.crt;
    ssl_certificate_key $tls/site.key;
    root  $root;
    index index.html;
}
CONF
if command -v restorecon >/dev/null; then restorecon -R "$root" "$tls"; fi
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "== firewall"
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && echo "  ufw: 80, 443 open"
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd -q --permanent --add-service=http --add-service=https && firewall-cmd -q --reload && echo "  firewalld: http, https open"
else
  echo "  no active host firewall"
fi

echo "== check"
http=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/)
https=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/)
echo "  http://127.0.0.1/ -> $http (expect 301), https://127.0.0.1/ -> $https (expect 200)"
[ "$http" = 301 ] && [ "$https" = 200 ]
echo "Web server ready: https://$fqdn/ (self-signed certificate)"
