-- Feed-reported status text alongside our estimated (predicted-scheduled) delay. Additive.
ALTER TABLE train_status ADD COLUMN reported_status TEXT;
