# Azure credentials (DQ-tool)

Save one JSON file per profile, for example:

- `default.json` — used when profile name is `default`

## File format

Create `default.json` (or any `<profile>.json`) with:

```json
{
  "connection_string": "PASTE_ONLY_THE_FULL_CONNECTION_STRING_HERE"
}
```

In Azure Portal you only need **one** value: **Storage account → Access keys → Connection string** (copy the whole string).  
You do **not** need to copy or store **Key1 / Key2** separately — the connection string already includes what the tool needs.

You can also use the Streamlit dashboard **Cloud connections** → Azure → **Save profile**; it writes to this folder automatically.

**Do not commit** `*.json` files here (they are gitignored).
