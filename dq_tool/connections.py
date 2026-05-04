"""Credential storage and connectivity checks for AWS, Azure, Snowflake, Fabric SQL."""

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
    if provider == "fabric":
        return _test_fabric(credentials)
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


def parse_fabric_sql_connection_string(pasted: str) -> dict[str, str]:
    """
    Extract server and database from a Fabric / Azure SQL style connection string.

    Supports common **ADO.NET** fragments (`Data Source=...;Initial Catalog=...`),
    **ODBC** (`SERVER=...;DATABASE=...`), and **JDBC**
    (`jdbc:sqlserver://host:1433;databaseName=...`).
    Returns keys ``server`` and/or ``database`` when found.
    """
    out: dict[str, str] = {}
    raw = (pasted or "").strip()
    if not raw:
        return out

    lower = raw.lower()
    if lower.startswith("jdbc:sqlserver://"):
        rest = raw.split("://", 1)[1]
        hostpart, _, props = rest.partition(";")
        hostpart = hostpart.split("/", 1)[0].strip()
        if hostpart:
            host_only = hostpart.split(":")[0].strip() if ":" in hostpart else hostpart
            if host_only:
                out["server"] = host_only
        for segment in props.split(";"):
            segment = segment.strip()
            if "=" not in segment:
                continue
            k, _, v = segment.partition("=")
            kl = k.strip().lower()
            vl = v.strip()
            if kl == "databasename":
                out["database"] = vl
        return out

    for piece in raw.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        key, _, val = piece.partition("=")
        key_l = key.strip().lower()
        val = val.strip().strip('"').strip("'")
        if key_l in ("data source", "server"):
            v = val
            if v.lower().startswith("tcp:"):
                v = v[4:]
            hostport = v.split(",", 1)[0].strip()
            if ":" in hostport and not hostport.endswith(".fabric.microsoft.com"):
                parts = hostport.rsplit(":", 1)
                if parts[-1].isdigit():
                    hostport = parts[0].strip()
            out["server"] = hostport
        elif key_l in ("initial catalog", "database"):
            out["database"] = val
    return out


def _fabric_host_only_to_server(paste: str) -> str | None:
    """If the user pasted only a hostname (no Data Source= / JDBC), use it as server."""
    t = paste.strip()
    if not t or "=" in t or ";" in t or " " in t or "\n" in t:
        return None
    if "." not in t:
        return None
    host = t.removeprefix("tcp:").split(",", 1)[0].strip()
    if ":" in host:
        left, _, right = host.rpartition(":")
        if right.isdigit():
            host = left.strip()
    return host or None


def _fabric_resolve_credentials(credentials: dict[str, str]) -> dict[str, str]:
    """Merge optional pasted SQL connection string into server/database for ODBC."""
    merged = {k: str(v).strip() if v is not None else "" for k, v in credentials.items()}
    paste = merged.get("sql_connection_string", "").strip()
    if paste:
        parsed = parse_fabric_sql_connection_string(paste)
        if not merged.get("server") and parsed.get("server"):
            merged["server"] = parsed["server"]
        if not merged.get("database") and parsed.get("database"):
            merged["database"] = parsed["database"]
        if not merged.get("server"):
            host_only = _fabric_host_only_to_server(paste)
            if host_only:
                merged["server"] = host_only
    return merged


def build_fabric_odbc_connection_string(credentials: dict[str, str]) -> tuple[bool, str]:
    """
    Build an ODBC connection string for a Microsoft Fabric SQL endpoint (pyodbc).

    On success returns (True, connection_string). On validation failure returns (False, error_message).
    """
    conn_str, err = _fabric_odbc_connection_string_or_error(credentials)
    if err:
        return False, err
    return True, conn_str


def _fabric_odbc_connection_string_or_error(credentials: dict[str, str]) -> tuple[str, str | None]:
    creds = _fabric_resolve_credentials(credentials)
    server = (creds.get("server") or "").strip()
    database = (creds.get("database") or "").strip()
    if not server:
        return (
            "",
            "Fabric needs the SQL endpoint. Paste the full SQL connection string from Fabric, "
            "or set server to your *.datawarehouse.fabric.microsoft.com host.",
        )
    if not database:
        return (
            "",
            "Fabric needs the SQL database name. Paste the full SQL connection string "
            "(it contains Initial Catalog=... or Database=...), or type the database name "
            "shown in the same Fabric dialog as the endpoint (often the lakehouse name).",
        )

    driver = (creds.get("driver") or "").strip() or "ODBC Driver 18 for SQL Server"
    auth_mode = (creds.get("authentication") or "interactive").strip().lower()
    if auth_mode not in ("interactive", "password", "service_principal"):
        auth_mode = "interactive"

    raw = server
    lower = raw.lower()
    if lower.startswith("tcp:"):
        server_odbc = raw if "," in raw[4:] else f"{raw},1433"
    elif "," in raw:
        server_odbc = raw if lower.startswith("tcp:") else f"tcp:{raw}"
    else:
        server_odbc = f"tcp:{raw},1433"

    odbc_auth = {
        "interactive": "ActiveDirectoryInteractive",
        "password": "ActiveDirectoryPassword",
        "service_principal": "ActiveDirectoryServicePrincipal",
    }[auth_mode]

    parts = [
        f"DRIVER={{{driver}}};",
        f"SERVER={server_odbc};",
        f"DATABASE={database};",
        "Encrypt=yes;",
        "TrustServerCertificate=no;",
        "Connection Timeout=60;",
        f"Authentication={odbc_auth};",
    ]

    if auth_mode == "password":
        user = (creds.get("user") or "").strip()
        pwd = creds.get("password") or ""
        if not user:
            return "", "Fabric password auth requires user (UPN)."
        if not pwd:
            return "", "Fabric password auth requires password."
        parts.append(f"UID={user};")
        parts.append(f"PWD={pwd};")
    elif auth_mode == "service_principal":
        tenant = (creds.get("tenant_id") or "").strip()
        client_id = (creds.get("client_id") or "").strip()
        secret = creds.get("client_secret") or ""
        if not tenant:
            return "", "Fabric service principal auth requires tenant_id."
        if not client_id:
            return "", "Fabric service principal auth requires client_id."
        if not secret:
            return "", "Fabric service principal auth requires client_secret."
        parts.append(f"UID={client_id};")
        parts.append(f"PWD={secret};")
        parts.append(f"Authority Id={tenant};")

    return "".join(parts), None


def _test_fabric(credentials: dict[str, str]) -> tuple[bool, str]:
    try:
        import pyodbc
    except ImportError:
        return False, "Install Fabric SQL driver: pip install pyodbc (and ODBC Driver 18 for SQL Server)."

    conn_str, err = _fabric_odbc_connection_string_or_error(credentials)
    if err:
        return False, err

    try:
        conn = pyodbc.connect(conn_str, timeout=60)
        cur = None
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 AS ok")
            row = cur.fetchone()
            ok = row[0] if row else None
        finally:
            if cur is not None:
                cur.close()
            conn.close()
        return True, f"Fabric SQL connection successful (check={ok})"
    except pyodbc.Error as exc:
        return False, f"Fabric SQL connection failed: {exc}"
    except (TypeError, ValueError, OSError) as exc:
        return False, f"Fabric SQL connection failed: {exc}"
