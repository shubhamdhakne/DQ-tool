"""Credential storage and connectivity checks for AWS, Azure, Snowflake."""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1] / "credentials"


def _safe_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    return cleaned or "default"


def credentials_root() -> Path:
    """Return credentials root folder used by DQ tool."""
    return BASE_DIR


def _provider_dir(provider: str, create: bool) -> Path:
    provider_dir = BASE_DIR / _safe_name(provider).lower()
    if create:
        provider_dir.mkdir(parents=True, exist_ok=True)
    return provider_dir


def _profile_path(provider: str, profile_name: str, create_dir: bool) -> Path:
    provider_dir = _provider_dir(provider, create=create_dir)
    return provider_dir / f"{_safe_name(profile_name)}.json"


def list_profiles(provider: str) -> list[str]:
    provider_dir = _provider_dir(provider, create=False)
    if not provider_dir.exists():
        return []
    names = [p.stem for p in provider_dir.glob("*.json") if p.is_file()]
    return sorted(names)


def save_profile(provider: str, profile_name: str, credentials: dict[str, str]) -> tuple[bool, str]:
    """Save a provider/profile as editable JSON in project credentials folder."""
    provider = provider.strip().lower()
    profile_name = profile_name.strip()
    if not provider or not profile_name:
        return False, "Provider and profile name are required."

    clean = {k: (v or "") for k, v in credentials.items()}
    path = _profile_path(provider, profile_name, create_dir=True)
    path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return True, f"Credentials saved: {path}"


def load_profile(provider: str, profile_name: str) -> tuple[bool, dict[str, str], str]:
    provider = provider.strip().lower()
    profile_name = profile_name.strip()
    if not provider or not profile_name:
        return False, {}, "Provider and profile name are required."

    path = _profile_path(provider, profile_name, create_dir=False)
    if not path.exists():
        return False, {}, "Profile not found."

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, {}, "Stored profile is invalid."
    return True, {k: str(v) for k, v in data.items()}, "Profile loaded."


def test_connection(provider: str, credentials: dict[str, str]) -> tuple[bool, str]:
    provider = provider.strip().lower()
    if provider == "aws":
        return _test_aws(credentials)
    if provider == "azure":
        return _test_azure(credentials)
    if provider == "snowflake":
        return _test_snowflake(credentials)
    return False, f"Unsupported provider: {provider}"


def _test_aws(credentials: dict[str, str]) -> tuple[bool, str]:
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        return False, "Install AWS SDK: pip install boto3"

    try:
        client = boto3.client(
            "sts",
            aws_access_key_id=credentials.get("access_key_id") or None,
            aws_secret_access_key=credentials.get("secret_access_key") or None,
            aws_session_token=credentials.get("session_token") or None,
            region_name=credentials.get("region") or None,
        )
        ident = client.get_caller_identity()
        arn = ident.get("Arn", "unknown")
        return True, f"AWS connection successful ({arn})"
    except (BotoCoreError, ClientError, TypeError, ValueError, OSError) as exc:
        return False, f"AWS connection failed: {exc}"


def _test_azure(credentials: dict[str, str]) -> tuple[bool, str]:
    try:
        from azure.core.exceptions import AzureError
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        return False, "Install Azure SDK: pip install azure-storage-blob"

    connection_string = credentials.get("connection_string", "")
    if not connection_string:
        return False, "Azure requires connection_string."
    try:
        client = BlobServiceClient.from_connection_string(connection_string)
        info = client.get_account_information()
        sku = info.get("sku_name", "unknown")
        return True, f"Azure Blob connection successful (sku={sku})"
    except (AzureError, TypeError, ValueError, OSError) as exc:
        return False, f"Azure connection failed: {exc}"


def _test_snowflake(credentials: dict[str, str]) -> tuple[bool, str]:
    try:
        import snowflake.connector
        from snowflake.connector.errors import Error as SnowflakeError
    except ImportError:
        return False, "Install Snowflake SDK: pip install snowflake-connector-python"

    required = ["account", "user", "password", "warehouse", "database", "schema"]
    missing = [k for k in required if not credentials.get(k)]
    if missing:
        return False, f"Snowflake missing required fields: {', '.join(missing)}"

    try:
        conn = snowflake.connector.connect(
            account=credentials.get("account"),
            user=credentials.get("user"),
            password=credentials.get("password"),
            warehouse=credentials.get("warehouse"),
            database=credentials.get("database"),
            schema=credentials.get("schema"),
            role=credentials.get("role") or None,
        )
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("select current_version()")
            version = cur.fetchone()[0]
        finally:
            if cur is not None:
                cur.close()
            conn.close()
        return True, f"Snowflake connection successful (version={version})"
    except (SnowflakeError, TypeError, ValueError, OSError) as exc:
        return False, f"Snowflake connection failed: {exc}"
