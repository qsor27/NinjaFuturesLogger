-- Purge existing bars that were fetched against the continuous front-month
-- symbol but stamped with specific contract-month instrument labels. The
-- coverage maintainer will re-populate from the correct per-contract
-- symbols on next startup.
DELETE FROM bars;
