# Catalog RLS — hiding tables from the reader

## Problem

S3 policy blocks data access, but `SHOW TABLES` still lists every table. DuckLake's `SHOW TABLES` reads from the Postgres `ducklake_table` table — so Postgres RLS can filter it.

## Solution

Enable RLS on `ducklake_table`. RLS is deny-by-default: once enabled, rows are hidden unless a policy grants access.

```sql
ALTER TABLE ducklake_table ENABLE ROW LEVEL SECURITY;

CREATE POLICY admin_all ON ducklake_table
  FOR SELECT TO ducklake USING (true);

CREATE POLICY reader_tables ON ducklake_table
  FOR SELECT TO reader USING (table_name = 'customer');
```

## Adding more tables

```sql
DROP POLICY reader_tables ON ducklake_table;
CREATE POLICY reader_tables ON ducklake_table
  FOR SELECT TO reader USING (table_name IN ('customer', 'nation'));
```

Update the S3 bucket policy too.

## Limitations

Only `ducklake_table` is filtered. Other metadata tables (`ducklake_column`, `ducklake_data_file`, etc.) are not — a reader could still infer table names from those. S3 still enforces actual data access, so this is fine for now.

## Sources

- [PostgreSQL Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PostgreSQL CREATE POLICY](https://www.postgresql.org/docs/current/sql-createpolicy.html)
- [DuckLake `ducklake_table` specification](https://ducklake.select/docs/stable/specification/tables/ducklake_table)
