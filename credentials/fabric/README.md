# Microsoft Fabric SQL (`credentials/fabric/`)

Profiles are **only** stored here as `<profile>.json` (for example `default.json`).  
Do not put secrets under `examples/`; the app reads **`credentials/<cloud>/<profile>.json`** only.

## Minimum profile

**Best:** paste the **full SQL connection string** from Fabric (includes `Data Source` and `Initial Catalog` / `Database`).

```json
{
  "authentication": "interactive",
  "sql_connection_string": "Data Source=....datawarehouse.fabric.microsoft.com;Initial Catalog=YourLakehouse;..."
}
```

**Host only:** if `sql_connection_string` is just the endpoint hostname (no `=`), the tool uses it as **server** and you must still set **`database`** (the SQL database / lakehouse name from Fabric):

```json
{
  "authentication": "interactive",
  "sql_connection_string": "your-workspace.datawarehouse.fabric.microsoft.com",
  "database": "YourLakehouseSqlName"
}
```

- **`authentication`**: `interactive` | `password` | `service_principal`
- **`sql_connection_string`**: paste the string from Fabric as a single line (semicolon-separated).

For **`password`** or **`service_principal`**, add the same extra keys as in the dashboard (user/password or tenant/client/secret).

## Optional overrides

Only if the pasted string does not include server or database (rare):

```json
{
  "authentication": "interactive",
  "sql_connection_string": "",
  "server": "your-endpoint.datawarehouse.fabric.microsoft.com",
  "database": "YourLakehouse",
  "driver": ""
}
```

`driver` defaults to `ODBC Driver 18 for SQL Server` when empty.

## Prerequisite

Install **ODBC Driver 18 for SQL Server** (or 17), then:

```bash
pip install pyodbc
```

Use **Cloud connections** in the dashboard to save/load, or edit JSON here.

## CLI: profile every table in a schema (default `BRONZE`)

From the repo root (after `pip install -r requirements-cloud.txt`):

```bash
python -m dq_tool --fabric-profile fabric --fabric-database YOUR_SQL_DATABASE_NAME --fabric-schema BRONZE --hide-paths --open-dashboard
```

- **`--fabric-profile`** — file name without `.json` under `credentials/fabric/` (e.g. `fabric` → `fabric.json`).
- **`--fabric-database`** — **Initial Catalog** / SQL database name from Fabric (use this if the JSON only has the endpoint host in `sql_connection_string`).
- **`--fabric-schema`** — defaults to **`BRONZE`**; only `A–Z`, `a–z`, `0–9`, `_` allowed.
- **`--fabric-max-rows`** — default `50000` (`SELECT TOP (n)` per table).
- **`--fabric-max-tables`** — default `0` = no cap; set e.g. `20` to smoke-test.

Only **`BASE TABLE`** rows from `INFORMATION_SCHEMA.TABLES` are included (not views).
