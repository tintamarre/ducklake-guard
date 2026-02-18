-- Enable Row-Level Security on ducklake_table so that
-- SHOW TABLES only reveals tables the connected user is allowed to see.

ALTER TABLE ducklake_table ENABLE ROW LEVEL SECURITY;

-- Admin: full visibility
CREATE POLICY admin_all ON ducklake_table
  FOR SELECT TO ducklake USING (true);

-- Reader: only allowed tables
CREATE POLICY reader_tables ON ducklake_table
  FOR SELECT TO reader USING (table_name = 'customer');
