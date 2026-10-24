import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt

from cognis.providers.auth.jwt import JWTAuthProvider
from tests.e2e import conftest as fixture


def test_probe_auth_is_per_call_with_real_signer(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    signer = JWTAuthProvider(private, public)
    subject = "e2e-admin@cognis-test.example.com"
    token = signer.sign_service_jwt(subject, fixture.E2E_AGENT_ID, ["mnemory"])
    observed = []

    def get(url, *, timeout, headers):
        observed.append(url)
        if "mnemory" in url:
            claims = jwt.decode(
                headers["Authorization"].removeprefix("Bearer "),
                public.read_text(),
                algorithms=["ES256"],
                issuer="cognis",
                audience="mnemory",
            )
            assert claims["sub"] == subject
            assert claims["aud"] == ["mnemory"]
            assert claims["typ"] == "service"
            assert claims["agent_id"] == fixture.E2E_AGENT_ID
        else:
            assert headers is None
        assert timeout == 5
        return httpx.Response(200)

    monkeypatch.setattr(fixture.httpx, "get", get)
    fixture._wait_healthy("http://mnemory", headers={"Authorization": f"Bearer {token}"})
    for service in ("mock-llm", "intaris", "cognis/api"):
        fixture._wait_healthy(f"http://{service}")
    assert len(observed) == 4


@pytest.mark.parametrize("statuses, succeeds", [([401, 200], True), ([401, 401], False)])
def test_401_retries_but_never_counts_as_ready(monkeypatch, statuses, succeeds):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(fixture.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        fixture.time, "sleep", lambda duration: clock.__setitem__(0, clock[0] + duration)
    )

    def get(url, *, timeout, headers):
        calls.append(headers)
        return httpx.Response(statuses[len(calls) - 1])

    monkeypatch.setattr(fixture.httpx, "get", get)
    if succeeds:
        fixture._wait_healthy("http://fixture", timeout=2, interval=1)
    else:
        with pytest.raises(RuntimeError, match="HTTP 401"):
            fixture._wait_healthy("http://fixture", timeout=2, interval=1)
    assert len(calls) == 2
    assert clock[0] <= 2
