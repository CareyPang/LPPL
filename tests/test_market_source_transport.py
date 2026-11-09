"""Only mocked DNS/TLS; never connect to a real source or fetch market data."""
import hashlib
import json
import socket
import ssl

import pytest

from scripts import probe_market_source_transport as probe


@pytest.fixture
def transport(monkeypatch):
    state = {"dns": [], "connections": [], "tls": [], "timeouts": [], "sleeps": [],
             "dns_error": None, "tcp_error": None, "tls_error": None,
             "addresses": [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.1", 443))],
             "certificate": b"synthetic-certificate", "verify_mode": ssl.CERT_REQUIRED,
             "check_hostname": True}

    def resolve(host, port, *, type):
        state["dns"].append((host, port, type))
        if state["dns_error"]:
            raise state["dns_error"]
        return state["addresses"]

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.family = family

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, seconds):
            state["timeouts"].append(seconds)

        def connect(self, address):
            state["connections"].append(address)
            if state["tcp_error"]:
                raise state["tcp_error"]

        def send(self, *_):
            pytest.fail("must not send HTTP or application payload")

        sendall = send
        recv = send

    class FakeTLS(FakeSocket):
        def getpeercert(self, *, binary_form):
            assert binary_form is True
            return state["certificate"]

        def cipher(self):
            return ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)

        def version(self):
            return "TLSv1.3"

    class FakeContext:
        @property
        def check_hostname(self):
            return state["check_hostname"]

        @property
        def verify_mode(self):
            return state["verify_mode"]

        def wrap_socket(self, connection, *, server_hostname):
            state["tls"].append(server_hostname)
            if state["tls_error"]:
                raise state["tls_error"]
            return FakeTLS(connection.family, socket.SOCK_STREAM, socket.IPPROTO_TCP)

    monkeypatch.setattr(probe.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(probe.socket, "socket", FakeSocket)
    monkeypatch.setattr(probe.ssl, "create_default_context", FakeContext)
    monkeypatch.setattr(probe.time, "sleep", state["sleeps"].append)
    return state


def test_two_rounds_are_serial_bounded_and_send_no_http(tmp_path, transport):
    output = tmp_path / "new-package"
    result = probe.run_probe(output)
    report = json.loads((output / "transport.json").read_bytes())
    expected = list(probe.HOSTS) * 2
    assert [d[0] for d in transport["dns"]] == expected
    assert transport["tls"] == expected
    assert len(transport["connections"]) == 4
    assert transport["timeouts"] == [5] * 4
    assert transport["sleeps"] == [3] * 3
    assert [r["round"] for r in report["results"]] == [1, 1, 2, 2]
    assert result["tls_successes"] == 4
    assert all(r["dns_success"] and r["tls_success"] and r["http_requests"] == 0 for r in report["results"])
    assert all(r["certificate_sha256"] == hashlib.sha256(b"synthetic-certificate").hexdigest() for r in report["results"])
    assert report["limits"]["dns_timeout_enforced"] is False
    assert report["mainland_network"] == "NOT_ESTABLISHED"
    assert report["publication_eligible"] is False
    assert report["provider_payload_fetched"] is False
    assert report["started_at"] <= report["finished_at"]
    assert all(r["started_at"] <= r["finished_at"] and r["elapsed_seconds"] >= 0 for r in report["results"])


def test_manifest_binds_exact_report_bytes(tmp_path, transport):
    output = tmp_path / "evidence"
    result = probe.run_probe(output, tun_detected=True)
    raw = (output / "transport.json").read_bytes()
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["bytes"] == len(raw)
    assert json.loads((output / "manifest.json").read_text()) == result
    environment = json.loads(raw)["environment"]
    assert environment["tun_detected"] is True
    assert environment["tun_evidence"] == "caller_declaration_only"
    assert environment["exit_location"] == environment["user_location"] == "NOT_ESTABLISHED"
    assert environment["proxy_configuration_inspected"] is False
    assert environment["proxy_configuration_changed"] is False


@pytest.mark.parametrize("host", ["example.com", "push2ex.eastmoney.com.attacker.test", "https://push2ex.eastmoney.com", "127.0.0.1", "PUSH2EX.EASTMONEY.COM"])
def test_non_allowlisted_hosts_fail_before_dns(host, transport):
    with pytest.raises(ValueError, match="allowlisted"):
        probe.probe_one(host)
    assert not transport["dns"]


@pytest.mark.parametrize(("field", "error", "stage", "failure"), [
    ("dns_error", socket.gaierror("secret-token"), "dns", "DNS_ERROR"),
    ("tcp_error", TimeoutError("secret-token"), "tcp", "TIMEOUT"),
    ("tcp_error", OSError("secret-token"), "tcp", "CONNECTION_ERROR"),
    ("tls_error", ssl.SSLError("secret-token"), "tls", "TLS_ERROR"),
    ("tls_error", ssl.SSLCertVerificationError("secret-token"), "tls", "CERTIFICATE_VERIFY_FAILED"),
])
def test_failures_are_sanitized_without_retry(transport, field, error, stage, failure):
    transport[field] = error
    row = probe.probe_one(probe.HOSTS[0])
    assert row["tls_success"] is False
    assert row["failure_stage"] == stage
    assert row["failure_type"] == failure
    assert "secret-token" not in json.dumps(row)
    assert len(transport["dns"]) == 1
    assert len(transport["connections"]) <= 1
    assert len(transport["tls"]) <= 1


@pytest.mark.parametrize("addresses", [[], [(-1, socket.SOCK_STREAM, 0, "", "/tmp/socket")]])
def test_missing_usable_dns_address_does_not_connect(transport, addresses):
    transport["addresses"] = addresses
    row = probe.probe_one(probe.HOSTS[0])
    assert row["failure_type"] == "DNS_NO_USABLE_ADDRESS"
    assert row["dns_success"] is False
    assert not transport["connections"]


def test_only_first_ip_attempted_even_when_connection_fails(transport):
    transport["addresses"].append((socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2001:db8::1", 443, 0, 0)))
    transport["tcp_error"] = OSError("failure")
    row = probe.probe_one(probe.HOSTS[0])
    assert row["resolved_ips"] == ["192.0.2.1", "2001:db8::1"]
    assert row["target_ip"] == "192.0.2.1"
    assert transport["connections"] == [("192.0.2.1", 443)]


@pytest.mark.parametrize(("key", "value"), [("check_hostname", False), ("verify_mode", ssl.CERT_NONE)])
def test_certificate_verification_cannot_be_disabled(transport, key, value):
    transport[key] = value
    row = probe.probe_one(probe.HOSTS[0])
    assert row["failure_stage"] == "tls_configuration"
    assert row["tls_success"] is False
    assert not transport["connections"]


def test_missing_certificate_is_not_tls_success(transport):
    transport["certificate"] = None
    row = probe.probe_one(probe.HOSTS[0])
    assert row["tls_success"] is False
    assert row["certificate_sha256"] is None
    assert row["failure_type"] == "PROBE_ERROR"


def test_existing_directory_refused_without_network(tmp_path, transport):
    existing = tmp_path / "existing"
    existing.mkdir()
    marker = existing / "transport.json"
    marker.write_bytes(b"keep-original")
    with pytest.raises(FileExistsError):
        probe.run_probe(existing)
    assert marker.read_bytes() == b"keep-original"
    assert not transport["dns"]


def test_invalid_metadata_rejected_before_files_or_network(tmp_path, transport):
    with pytest.raises(ValueError):
        probe.run_probe(tmp_path / "out", tun_detected="true")
    assert not (tmp_path / "out").exists()
    assert not transport["dns"]


@pytest.mark.parametrize("flag", ["true", "false", "unknown"])
def test_cli_success_retains_unestablished_mainland(tmp_path, transport, capsys, flag):
    output = tmp_path / "package"
    assert probe.main(["--output", str(output), "--tun-detected", flag]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["mainland_network"] == "NOT_ESTABLISHED"
    assert printed["provider_payload_fetched"] is False


def test_cli_failure_still_writes_bounded_report(tmp_path, transport, capsys):
    transport["tls_error"] = ssl.SSLCertVerificationError("sensitive details")
    output = tmp_path / "failed"
    assert probe.main(["--output", str(output)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["attempts"] == 4
    assert result["tls_successes"] == 0
    assert len(transport["tls"]) == 4
    assert transport["sleeps"] == [3] * 3
    assert "sensitive details" not in (output / "transport.json").read_text()
