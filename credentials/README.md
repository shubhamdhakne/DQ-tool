# Credentials layout (`credentials/`)

All cloud profiles live **inside the DQ-tool project** under this folder, **one subfolder per cloud**, **one JSON file per profile name**.

| Cloud      | Folder             | Example path (profile `default`)     | JSON keys |
|------------|--------------------|--------------------------------------|-----------|
| **AWS**    | `credentials/aws/` | `credentials/aws/default.json`       | `access_key_id`, `secret_access_key`, `region`, `session_token` (optional) |
| **Azure**  | `credentials/azure/` | `credentials/azure/default.json` | `connection_string` |
| **Snowflake** | `credentials/snowflake/` | `credentials/snowflake/default.json` | `account`, `user`, `password`, `warehouse`, `database`, `schema`, `role` (optional) |

- **Profile name** = file name without `.json` (e.g. profile `prod` → `prod.json`).
- **`*.json` files are gitignored** so secrets are not pushed to GitHub.
- You can **edit JSON by hand** or use the Streamlit dashboard **Cloud connections** → **Save profile**.

### Multiple Azure storage accounts (or any cloud)

Use **one JSON file per account**, with a clear profile name:

- `credentials/azure/default.json` → profile **`default`**
- `credentials/azure/azure_account_2.json` → profile **`azure_account_2`**

In the dashboard, pick the profile in **Saved profiles**, then **Load profile** / **Test connection**.  
Same for AWS: e.g. `credentials/aws/prod.json` → profile **`prod`**.

Absolute path pattern on your machine:

`<DQ-tool repo root>\credentials\<cloud>\<profile>.json`
