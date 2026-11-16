"""net.py: address checks, pinning, redirects and limits."""

from __future__ import annotations

import socket

import pytest

from seokit import net
from tests.site_server import Site


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.0.1", "172.16.5.4", "169.254.169.254",
                                "100.64.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1",
                                "224.0.0.1", "2002:7f00:1::1"])
def test_non_public_addresses_rejected(ip):
    assert not net.is_public_ip(ip)


@pytest.mark.parametrize("ip", ["93.184.215.14", "8.8.8.8", "2606:4700::1111"])
def test_public_addresses_accepted(ip):
    assert net.is_public_ip(ip)


def _resolve_to(monkeypatch, ip):
    monkeypatch.setattr(net.socket, "getaddrinfo",
                        lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))])


def test_check_url_rules(monkeypatch):
    _resolve_to(monkeypatch, "93.184.215.14")
    assert net.check_url("https://example.com/x") == ("example.com", 443, "93.184.215.14")
    for bad in ("ftp://example.com/", "file:///etc/passwd", "https://user:pw@example.com/", "https:///x"):
        with pytest.raises(net.BlockedURL):
            net.check_url(bad)
    _resolve_to(monkeypatch, "10.0.0.5")
    with pytest.raises(net.BlockedURL, match="non-public"):
        net.check_url("https://internal.example/")


def test_any_private_answer_blocks(monkeypatch):
    monkeypatch.setattr(net.socket, "getaddrinfo", lambda host, port, type=0: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", port)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))])
    with pytest.raises(net.BlockedURL):
        net.check_url("https://mixed.example/")


def test_localhost_needs_opt_in(monkeypatch):
    site = Site({"/": (200, {}, "<p>hi</p>")})
    try:
        assert "blocked" in net.fetch(site.base + "/").error
        monkeypatch.setenv("SEOKIT_ALLOW_HOSTS", f"127.0.0.1:{site.port}")
        res = net.fetch(site.base + "/")
        assert res.ok and res.text == "<p>hi</p>"
        monkeypatch.setenv("SEOKIT_ALLOW_HOSTS", "127.0.0.1:1")  # other port only
        assert "blocked" in net.fetch(site.base + "/").error
    finally:
        site.close()


def test_redirects_followed_and_rechecked(monkeypatch):
    site = Site({
        "/a": (301, {"Location": "/b"}, ""),
        "/b": (302, {"Location": "{base}/c"}, ""),
        "/c": (200, {}, "done"),
        "/evil": (301, {"Location": "http://10.0.0.1/admin"}, ""),
        "/loop": (301, {"Location": "/loop"}, ""),
    })
    monkeypatch.setenv("SEOKIT_ALLOW_HOSTS", f"127.0.0.1:{site.port}")
    try:
        res = net.fetch(site.base + "/a")
        assert res.status == 200 and res.final_url == site.base + "/c"
        assert [code for _, code in res.redirects] == [301, 302]
        evil = net.fetch(site.base + "/evil")
        assert evil.error and "non-public" in evil.error
        loop = net.fetch(site.base + "/loop", max_redirects=3)
        assert "more than 3 redirects" in loop.error
    finally:
        site.close()


def test_body_limit_and_charset(monkeypatch):
    site = Site({"/big": (200, {}, "x" * 5000),
                 "/latin": (200, {"Content-Type": "text/html; charset=iso-8859-1"}, "caf\xe9".encode("latin-1"))})
    monkeypatch.setenv("SEOKIT_ALLOW_HOSTS", f"127.0.0.1:{site.port}")
    try:
        big = net.fetch(site.base + "/big", max_bytes=1000)
        assert big.truncated and len(big.body) == 1000
        assert net.fetch(site.base + "/latin").text == "café"
    finally:
        site.close()


def test_unchecked_host_cannot_connect():
    session, adapter = net.new_session()
    with pytest.raises(Exception):
        session.get("http://example.com/", timeout=5)  # no pin was recorded for this host
