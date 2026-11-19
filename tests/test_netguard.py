import pytest

from catch.core import netguard


@pytest.mark.parametrize(
    "url",
    [
        "https://fcm.googleapis.com/fcm/send/abc",
        "https://web.push.apple.com/QPx",
        "https://updates.push.services.mozilla.com/wpush/v2/abc",
        "https://wns2-par02p.notify.windows.com/w/?token=abc",
    ],
)
def test_real_push_services_are_accepted(url):
    assert netguard.validate_push_endpoint(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://fcm.googleapis.com/x",  # not https
        "https://169.254.169.254/latest/meta-data",  # metadata service
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://[::ffff:10.0.0.1]/x",
        "https://localhost/x",
        "https://10.0.0.5:443/x",
        "https://evil.example.com/x",
        "https://fcm.googleapis.com.evil.com/x",  # suffix trick
        "https://evilfcm.googleapis.com.attacker.io/x",
        "https://notfcm.googleapis.com/x",
        "https://user:pw@fcm.googleapis.com/x",  # userinfo
        "https://fcm.googleapis.com:8443/x",  # non-standard port
        "https://fcm.googleapis.com/x#frag",
        "file:///etc/passwd",
        "gopher://fcm.googleapis.com/",
        "",
        "https://" + "a" * 2000 + ".push.apple.com/x",
    ],
)
def test_everything_else_is_refused(url):
    with pytest.raises(netguard.UnsafeUrl):
        netguard.validate_push_endpoint(url)


@pytest.mark.parametrize("addr", ["10.1.2.3", "192.168.0.1", "172.16.5.5", "127.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "::ffff:192.168.1.1", "0.0.0.0"])
def test_non_public_addresses(addr):
    assert not netguard.is_public_address(addr)


def test_public_address():
    assert netguard.is_public_address("8.8.8.8")


def test_resolution_to_a_private_address_is_refused_and_failure_is_closed():
    def private(host, port, **kw):
        return [(2, 1, 6, "", ("10.0.0.7", port))]

    def mixed(host, port, **kw):
        return [(2, 1, 6, "", ("8.8.8.8", port)), (2, 1, 6, "", ("127.0.0.1", port))]

    def broken(host, port, **kw):
        raise OSError("no such host")

    assert not netguard.resolves_public("x.example", resolver=private)
    assert not netguard.resolves_public("x.example", resolver=mixed)
    assert not netguard.resolves_public("x.example", resolver=broken)
    assert netguard.resolves_public("x.example", resolver=lambda h, p, **kw: [(2, 1, 6, "", ("8.8.8.8", p))])


def test_outbound_base_url_private_allowed_only_when_asked():
    assert netguard.validate_outbound_base_url("http://192.168.1.20:11434", allow_private=True)
    with pytest.raises(netguard.UnsafeUrl):
        netguard.validate_outbound_base_url("http://192.168.1.20:11434", allow_private=False)
    with pytest.raises(netguard.UnsafeUrl):
        netguard.validate_outbound_base_url("http://169.254.169.254/", allow_private=False)
    with pytest.raises(netguard.UnsafeUrl):
        netguard.validate_outbound_base_url("ftp://example.com", allow_private=True)
    with pytest.raises(netguard.UnsafeUrl):
        netguard.validate_outbound_base_url("http://u:p@example.com", allow_private=True)
