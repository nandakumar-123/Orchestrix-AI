from __future__ import annotations

import logging
import socket
import struct
from typing import Any

logger = logging.getLogger("orchestrix.dns")

_orig_getaddrinfo = socket.getaddrinfo
_patched = False


def _resolve_a_record_udp(hostname: str, dns_server: str = "8.8.8.8", timeout: float = 2.0) -> list[str]:
    """Perform a direct DNS query over UDP for A records."""
    packet = b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    for part in hostname.split("."):
        packet += bytes([len(part)]) + part.encode()
    packet += b"\x00\x00\x01\x00\x01"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(packet, (dns_server, 53))
        resp, _ = sock.recvfrom(2048)
    except Exception:
        return []
    finally:
        sock.close()

    ips: list[str] = []
    idx = len(packet)
    while idx + 12 <= len(resp):
        if (resp[idx] & 0xC0) == 0xC0:
            idx += 2
        else:
            while idx < len(resp) and resp[idx] != 0:
                idx += 1 + resp[idx]
            idx += 1

        if idx + 10 > len(resp):
            break

        qtype, _qcls, _ttl, rdlen = struct.unpack("!HHIH", resp[idx : idx + 10])
        idx += 10
        if qtype == 1 and rdlen == 4 and idx + 4 <= len(resp):
            ips.append(socket.inet_ntoa(resp[idx : idx + 4]))
        idx += rdlen

    return ips


def enable_dns_fallback() -> None:
    """
    Wrap socket.getaddrinfo to fall back to public DNS (8.8.8.8)
    when the local system resolver returns gaierror (e.g. institutional DNS refusal).
    """
    global _patched
    if _patched:
        return

    def fallback_getaddrinfo(
        host: str | bytes | None,
        port: str | int | None,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Any:
        try:
            return _orig_getaddrinfo(host, port, family, type, proto, flags)
        except socket.gaierror as gai_err:
            if isinstance(host, str) and host and "." in host and not host.replace(".", "").isdigit():
                for dns_server in ("8.8.8.8", "1.1.1.1"):
                    ips = _resolve_a_record_udp(host, dns_server=dns_server)
                    if ips:
                        port_int = int(port) if port is not None else 0
                        results: list[Any] = []
                        for ip in ips:
                            results.append(
                                (
                                    socket.AF_INET,
                                    type or socket.SOCK_STREAM,
                                    proto or 6,
                                    "",
                                    (ip, port_int),
                                )
                            )
                        return results
            raise gai_err

    socket.getaddrinfo = fallback_getaddrinfo  # type: ignore[assignment]
    _patched = True
