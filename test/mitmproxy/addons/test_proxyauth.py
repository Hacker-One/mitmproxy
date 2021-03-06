import binascii
import ldap3

import pytest

from mitmproxy import exceptions
from mitmproxy.addons import proxyauth
from mitmproxy.test import taddons
from mitmproxy.test import tflow
from mitmproxy.test import tutils


def test_parse_http_basic_auth():
    assert proxyauth.parse_http_basic_auth(
        proxyauth.mkauth("test", "test")
    ) == ("basic", "test", "test")
    with pytest.raises(ValueError):
        proxyauth.parse_http_basic_auth("")
    with pytest.raises(ValueError):
        proxyauth.parse_http_basic_auth("foo bar")
    with pytest.raises(ValueError):
        proxyauth.parse_http_basic_auth("basic abc")
    with pytest.raises(ValueError):
        v = "basic " + binascii.b2a_base64(b"foo").decode("ascii")
        proxyauth.parse_http_basic_auth(v)


def test_configure():
    up = proxyauth.ProxyAuth()
    with taddons.context() as ctx:
        with pytest.raises(exceptions.OptionsError):
            ctx.configure(up, proxyauth="foo")

        ctx.configure(up, proxyauth="foo:bar")
        assert up.singleuser == ["foo", "bar"]

        ctx.configure(up, proxyauth=None)
        assert up.singleuser is None

        ctx.configure(up, proxyauth="any")
        assert up.nonanonymous
        ctx.configure(up, proxyauth=None)
        assert not up.nonanonymous

        ctx.configure(up, proxyauth="ldap:fake_server:fake_dn:fake_group")
        assert up.ldapserver

        ctx.configure(up, proxyauth="ldap:fake_server:uid=?,dc=example,dc=com:person")
        assert up.ldapserver
        ctx.configure(up, proxyauth="ldaps:fake_server.com:uid=?,dc=example,dc=com:person")
        assert up.ldapserver

        with pytest.raises(exceptions.OptionsError):
            ctx.configure(up, proxyauth="ldap:fake_serveruid=?dc=example,dc=com:person")

        with pytest.raises(exceptions.OptionsError):
            ctx.configure(up, proxyauth="ldapssssssss:fake_server.com:uid=?,dc=example,dc=com:person")

        with pytest.raises(exceptions.OptionsError):
            ctx.configure(
                up,
                proxyauth= "@" + tutils.test_data.path("mitmproxy/net/data/server.crt")
            )
        with pytest.raises(exceptions.OptionsError):
            ctx.configure(up, proxyauth="@nonexistent")

        ctx.configure(
            up,
            proxyauth= "@" + tutils.test_data.path(
                "mitmproxy/net/data/htpasswd"
            )
        )
        assert up.htpasswd
        assert up.htpasswd.check_password("test", "test")
        assert not up.htpasswd.check_password("test", "foo")
        ctx.configure(up, proxyauth=None)
        assert not up.htpasswd

        with pytest.raises(exceptions.OptionsError):
            ctx.configure(up, proxyauth="any", mode="transparent")
        with pytest.raises(exceptions.OptionsError):
            ctx.configure(up, proxyauth="any", mode="socks5")


def test_check(monkeypatch):
    up = proxyauth.ProxyAuth()
    with taddons.context() as ctx:
        ctx.configure(up, proxyauth="any", mode="regular")
        f = tflow.tflow()
        assert not up.check(f)
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "test"
        )
        assert up.check(f)

        f.request.headers["Proxy-Authorization"] = "invalid"
        assert not up.check(f)

        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "test", scheme="unknown"
        )
        assert not up.check(f)

        ctx.configure(up, proxyauth="test:test")
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "test"
        )
        assert up.check(f)
        ctx.configure(up, proxyauth="test:foo")
        assert not up.check(f)

        ctx.configure(
            up,
            proxyauth="@" + tutils.test_data.path(
                "mitmproxy/net/data/htpasswd"
            )
        )
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "test"
        )
        assert up.check(f)
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "foo"
        )
        assert not up.check(f)

        ctx.configure(
            up,
            proxyauth="ldap:fake-server:cn=?,ou=test,o=lab:test"
        )
        conn = ldap3.Connection("fake-server", user="cn=user0,ou=test,o=lab", password="password", client_strategy=ldap3.MOCK_SYNC)
        conn.bind()
        conn.strategy.add_entry('cn=user0,ou=test,o=lab', {'userPassword': 'test0', 'sn': 'user0_sn', 'revision': 0, 'objectClass': 'test'})

        def conn_mp(ldap, user, password, **kwargs):
            return conn

        monkeypatch.setattr(ldap3, "Connection", conn_mp)
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "user0", "test0"
        )
        assert up.check(f)
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "", ""
        )
        assert not up.check(f)


def test_authenticate():
    up = proxyauth.ProxyAuth()
    with taddons.context() as ctx:
        ctx.configure(up, proxyauth="any", mode="regular")

        f = tflow.tflow()
        assert not f.response
        up.authenticate(f)
        assert f.response.status_code == 407

        f = tflow.tflow()
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "test"
        )
        up.authenticate(f)
        assert not f.response
        assert not f.request.headers.get("Proxy-Authorization")

        f = tflow.tflow()
        ctx.configure(up, mode="reverse")
        assert not f.response
        up.authenticate(f)
        assert f.response.status_code == 401

        f = tflow.tflow()
        f.request.headers["Authorization"] = proxyauth.mkauth(
            "test", "test"
        )
        up.authenticate(f)
        assert not f.response
        assert not f.request.headers.get("Authorization")


def test_handlers():
    up = proxyauth.ProxyAuth()
    with taddons.context() as ctx:
        ctx.configure(up, proxyauth="any", mode="regular")

        f = tflow.tflow()
        assert not f.response
        up.requestheaders(f)
        assert f.response.status_code == 407

        f = tflow.tflow()
        f.request.method = "CONNECT"
        assert not f.response
        up.http_connect(f)
        assert f.response.status_code == 407

        f = tflow.tflow()
        f.request.method = "CONNECT"
        f.request.headers["Proxy-Authorization"] = proxyauth.mkauth(
            "test", "test"
        )
        up.http_connect(f)
        assert not f.response

        f2 = tflow.tflow(client_conn=f.client_conn)
        up.requestheaders(f2)
        assert not f2.response
        assert f2.metadata["proxyauth"] == ('test', 'test')
