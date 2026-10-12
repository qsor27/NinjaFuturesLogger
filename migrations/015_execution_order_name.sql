-- migrations/015_execution_order_name.sql
-- Setup Gate spec §12a: keep the CSV `Name` column (the NinjaTrader order name)
-- so positions can derive their entry method. Nullable: rows imported before
-- this migration have no stored name and classify as "unknown".
ALTER TABLE executions ADD COLUMN order_name TEXT;
