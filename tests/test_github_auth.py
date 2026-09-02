import os
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import get_settings


@pytest.fixture
def rsa_keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_create_app_jwt_is_signed_and_verifiable(rsa_keypair: tuple[str, str]) -> None:
    private_pem, public_pem = rsa_keypair
    with patch.dict(
        os.environ, {"GITHUB_APP_ID": "123456", "GITHUB_PRIVATE_KEY": private_pem}
    ):
        from app.github.auth import create_app_jwt

        token = create_app_jwt()

    decoded = jwt.decode(token, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == "123456"
    assert decoded["exp"] > decoded["iat"]


def test_create_app_jwt_requires_configured_credentials() -> None:
    with patch.dict(os.environ, {"GITHUB_APP_ID": "", "GITHUB_PRIVATE_KEY": ""}):
        from app.github.auth import create_app_jwt

        with pytest.raises(RuntimeError):
            create_app_jwt()


def test_get_installation_access_token_calls_github_api(rsa_keypair: tuple[str, str]) -> None:
    private_pem, _ = rsa_keypair
    with patch.dict(
        os.environ, {"GITHUB_APP_ID": "123456", "GITHUB_PRIVATE_KEY": private_pem}
    ):
        from app.github.auth import get_installation_access_token

        mock_response = MagicMock()
        mock_response.json.return_value = {"token": "ghs_faketoken"}
        mock_response.raise_for_status.return_value = None

        with patch("app.github.auth.httpx.post", return_value=mock_response) as mock_post:
            token = get_installation_access_token(999)

    assert token == "ghs_faketoken"
    mock_post.assert_called_once()
    assert "999" in mock_post.call_args.args[0]
