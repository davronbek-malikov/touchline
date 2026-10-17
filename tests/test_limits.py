from api.limits import client_ip


def test_forwarded_for_ignored_unless_behind_trusted_proxy():
    spoofed = {"x-forwarded-for": "1.2.3.4"}
    assert client_ip(spoofed, "10.0.0.9", trusted_hops=0) == "10.0.0.9"


def test_uses_hop_appended_by_trusted_proxy_not_client_value():
    # Client sends a fake value; Railway's edge appends the real address on the right.
    headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.7"}
    assert client_ip(headers, "10.0.0.9", trusted_hops=1) == "203.0.113.7"
    assert client_ip({}, "10.0.0.9", trusted_hops=1) == "10.0.0.9"
