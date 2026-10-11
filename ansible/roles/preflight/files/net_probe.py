#!/usr/bin/env python3
"""Probe DNS and NTP servers from where the hosts will live. Prints JSON.

usage: net_probe.py --domain example.com --dns 10.0.0.10,10.0.0.11 --ntp 10.0.0.10
                    [--resolve vme.example.com,ntp1.example.com]   (A records, per name and DNS server)
Standard library only, so it runs on any jump host or controller with python3.
"""

import argparse
import json
import os
import socket
import struct
import time

NTP_EPOCH = 2208988800


def dns_query(server, name, timeout=3):
    """Send one SOA query; any well-formed reply (even NXDOMAIN) means the server answers."""
    qid = int.from_bytes(os.urandom(2), "big")
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.rstrip(".").split(".")) + b"\0"
    pkt = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 6, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (server, 53))
        data, _ = s.recvfrom(4096)
        rid, flags, _, ancount = struct.unpack("!HHHH", data[:8])
        if rid != qid:
            return {"ok": False, "error": "reply id mismatch"}
        rcode = flags & 0xF
        return {
            "ok": rcode in (0, 3),
            "rcode": rcode,
            "answers": ancount,
            **({} if rcode in (0, 3) else {"error": f"rcode {rcode}"}),
        }
    except OSError as e:
        return {"ok": False, "error": str(e) or type(e).__name__}
    finally:
        s.close()


def _skip_name(data, i):
    """Offset after a (possibly compressed) name in a DNS message."""
    while True:
        n = data[i]
        if n == 0:
            return i + 1
        if n & 0xC0 == 0xC0:
            return i + 2
        i += n + 1


def dns_resolve(server, name, timeout=3):
    """A records of name from this server (recursive query; CNAME chains are followed by the server)."""
    qid = int.from_bytes(os.urandom(2), "big")
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.rstrip(".").split(".")) + b"\0"
    pkt = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(pkt, (server, 53))
        data, _ = s.recvfrom(4096)
        rid, flags, qdcount, ancount = struct.unpack("!HHHH", data[:8])
        if rid != qid:
            return {"ok": False, "error": "reply id mismatch"}
        rcode = flags & 0xF
        i = 12
        for _ in range(qdcount):
            i = _skip_name(data, i) + 4
        ips = []
        for _ in range(ancount):
            i = _skip_name(data, i)
            rtype, _, _, rdlen = struct.unpack("!HHIH", data[i : i + 10])
            i += 10
            if rtype == 1 and rdlen == 4:
                ips.append(socket.inet_ntoa(data[i : i + 4]))
            i += rdlen
        return {"ok": True, "rcode": rcode, "ips": ips}
    except (OSError, struct.error, IndexError) as e:
        return {"ok": False, "error": str(e) or type(e).__name__}
    finally:
        s.close()


def ntp_query(server, timeout=3):
    """SNTP client query. root_distance follows systemd-timesyncd (delay/2 + dispersion)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.time()
        s.sendto(b"\x23" + 47 * b"\0", (server, 123))
        data, _ = s.recvfrom(48)
        t1 = time.time()
        first, stratum = data[0], data[1]
        root_delay, root_disp = (v / 65536 for v in struct.unpack("!II", data[4:12]))
        tx = struct.unpack("!II", data[40:48])
        server_time = tx[0] - NTP_EPOCH + tx[1] / 2**32
        return {
            "ok": True,
            "leap": first >> 6,  # 3 = server clock not synchronised
            "stratum": stratum,
            "refid": data[12:16].decode("ascii", "replace").strip("\0")
            if stratum <= 1
            else ".".join(map(str, data[12:16])),
            "root_distance": round(root_delay / 2 + root_disp, 3),
            "offset": round(server_time - (t0 + t1) / 2, 3),  # vs the probing machine's clock
        }
    except OSError as e:
        return {"ok": False, "error": str(e) or type(e).__name__}
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True)
    ap.add_argument("--dns", default="")
    ap.add_argument("--ntp", default="")
    ap.add_argument("--resolve", default="")
    a = ap.parse_args()
    servers = list(filter(None, a.dns.split(",")))
    print(
        json.dumps(
            {
                "dns": {s: dns_query(s, a.domain) for s in servers},
                "ntp": {s: ntp_query(s) for s in filter(None, a.ntp.split(","))},
                "resolve": {n: {s: dns_resolve(s, n) for s in servers} for n in filter(None, a.resolve.split(","))},
            }
        )
    )


if __name__ == "__main__":
    main()
