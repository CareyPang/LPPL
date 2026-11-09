#!/usr/bin/env python3
"""Bounded DNS/TLS diagnostics only: never issue an HTTP request or fetch a pool.

The system DNS resolver can block longer than the socket timeout. This probe
does not claim to enforce a DNS deadline, infer an exit country, inspect proxy
configuration, or establish Mainland availability from a successful handshake.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path

HOSTS = ("push2ex.eastmoney.com", "data.10jqka.com.cn")
ROUNDS = 2
SOCKET_TIMEOUT_SECONDS = 5
MIN_INTERVAL_SECONDS = 3


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def probe_one(host: str) -> dict:
    if host not in HOSTS:
        raise ValueError("host is not allowlisted")
    started, tick = utc_now(), time.monotonic()
    row = {"host": host, "port": 443, "started_at": started, "dns_success": False,
           "resolved_ips": [], "target_ip": None, "tcp_success": False,
           "tls_success": False, "cipher": None, "tls_version": None,
           "certificate_sha256": None, "failure_stage": None, "failure_type": None,
           "provider_payload_fetched": False, "http_requests": 0}
    stage = "dns"
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        usable = [a for a in addresses if a[0] in (socket.AF_INET, socket.AF_INET6)
                  and a[1] == socket.SOCK_STREAM]
        if not usable:
            raise LookupError("no usable DNS addresses")
        row["dns_success"] = True
        row["resolved_ips"] = list(dict.fromkeys(a[4][0] for a in usable))
        # One selected address, one connection attempt. No failover/retry.
        family, socktype, proto, _, target = usable[0]
        row["target_ip"] = target[0]
        stage = "tls_configuration"
        context = ssl.create_default_context()
        if context.check_hostname is not True or context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("certificate verification must remain enabled")
        stage = "tcp"
        with socket.socket(family, socktype, proto) as connection:
            connection.settimeout(SOCKET_TIMEOUT_SECONDS)
            connection.connect(target)
            row["tcp_success"] = True
            stage = "tls"
            with context.wrap_socket(connection, server_hostname=host) as secured:
                certificate = secured.getpeercert(binary_form=True)
                if not isinstance(certificate, bytes) or not certificate:
                    raise ValueError("peer certificate missing")
                cipher = secured.cipher()
                row.update({"tls_success": True, "tls_version": secured.version(),
                            "cipher": list(cipher) if cipher else None,
                            "certificate_sha256": hashlib.sha256(certificate).hexdigest()})
    except Exception as exc:  # noqa: BLE001 - error messages may contain sensitive routing details.
        if isinstance(exc, ssl.SSLCertVerificationError):
            failure = "CERTIFICATE_VERIFY_FAILED"
        elif isinstance(exc, ssl.SSLError):
            failure = "TLS_ERROR"
        elif isinstance(exc, socket.gaierror):
            failure = "DNS_ERROR"
        elif isinstance(exc, TimeoutError):
            failure = "TIMEOUT"
        elif isinstance(exc, LookupError):
            failure = "DNS_NO_USABLE_ADDRESS"
        elif isinstance(exc, OSError):
            failure = "CONNECTION_ERROR"
        else:
            failure = "PROBE_ERROR"
        row.update({"failure_stage": stage, "failure_type": failure})
    row.update({"finished_at": utc_now(), "elapsed_seconds": round(time.monotonic() - tick, 6)})
    return row


def run_probe(output: Path, *, tun_detected: bool | None = None) -> dict:
    if tun_detected is not None and type(tun_detected) is not bool:
        raise ValueError("tun_detected must be bool or None")
    output = Path(output)
    # mkdir is exclusive; never overwrite an earlier evidence package.
    output.mkdir(parents=True, exist_ok=False)
    started = utc_now()
    rows = []
    for round_number in range(1, ROUNDS + 1):
        for host in HOSTS:
            if rows:
                time.sleep(MIN_INTERVAL_SECONDS)
            rows.append({"round": round_number, **probe_one(host)})
    report = {"schema_version": "market-source-transport.v1", "started_at": started,
              "finished_at": utc_now(), "publication_eligible": False,
              "provider_payload_fetched": False, "mainland_network": "NOT_ESTABLISHED",
              "environment": {"user_location": "NOT_ESTABLISHED", "exit_location": "NOT_ESTABLISHED",
                              "tun_detected": tun_detected, "tun_evidence": "caller_declaration_only",
                              "proxy_configuration_inspected": False, "proxy_configuration_changed": False},
              "limits": {"allowlisted_hosts": list(HOSTS), "rounds": ROUNDS,
                         "max_dns_resolver_calls": len(HOSTS) * ROUNDS,
                         "max_tls_connection_attempts": len(HOSTS) * ROUNDS,
                         "min_interval_seconds": MIN_INTERVAL_SECONDS,
                         "socket_timeout_seconds": SOCKET_TIMEOUT_SECONDS,
                         "dns_timeout_enforced": False, "retries": 0, "http_requests": 0},
              "limitations": ["System DNS resolution may outlast the socket timeout.",
                              "Socket connections may traverse a system TUN; this probe does not detect or alter routing.",
                              "DNS/TLS success does not establish API access, licensing, data completeness, frequency limits, or Mainland direct connectivity."],
              "results": rows}
    raw = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    with (output / "transport.json").open("xb") as handle:
        handle.write(raw)
    summary = {"schema_version": "market-source-transport-manifest.v1",
               "file": "transport.json", "sha256": hashlib.sha256(raw).hexdigest(),
               "bytes": len(raw), "attempts": len(rows),
               "tls_successes": sum(r["tls_success"] for r in rows),
               "publication_eligible": False, "provider_payload_fetched": False,
               "mainland_network": "NOT_ESTABLISHED"}
    with (output / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; existing paths are refused")
    parser.add_argument("--tun-detected", choices=("true", "false", "unknown"), default="unknown",
                        help="Caller declaration only; never establishes geographic connectivity")
    args = parser.parse_args(argv)
    summary = run_probe(args.output, tun_detected={"true": True, "false": False, "unknown": None}[args.tun_detected])
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["tls_successes"] == summary["attempts"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
