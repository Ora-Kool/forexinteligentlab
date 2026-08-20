-- Correct bar timestamps captured before the MT5 server-clock fix.
--
-- MetaTrader returns candle/tick times as epoch seconds built from the broker
-- server wall clock. The adapter used to relabel those as UTC, so every stored
-- bar sits ahead of real UTC by the server offset (FBS runs EET/EEST: +2h in
-- winter, +3h in summer). That shifted hour_of_day and the session flags.
--
-- Every affected row here was captured during EEST, so a single -3h shift is
-- correct. EURUSD D1 is excluded: it reaches back to 2024 and crosses DST
-- boundaries, so it is deleted and re-imported by the fixed adapter instead.
--
-- Adjust the interval if your broker's offset differs.

BEGIN;

DELETE FROM market_candles WHERE timeframe = 'D1';

-- The candle uniqueness constraint is not deferrable, and Postgres validates it
-- per row, so a bulk shift trips over bars that have not moved yet. Drop it for
-- the duration of the shift and restore it once every row has moved.
ALTER TABLE market_candles DROP CONSTRAINT IF EXISTS uq_candle_symbol_tf_ts;

UPDATE market_candles SET timestamp = timestamp - INTERVAL '3 hours';

ALTER TABLE market_candles
  ADD CONSTRAINT uq_candle_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp);

ALTER TABLE features DROP CONSTRAINT IF EXISTS uq_feature_symbol_tf_ts;

UPDATE features SET timestamp = timestamp - INTERVAL '3 hours';

ALTER TABLE features
  ADD CONSTRAINT uq_feature_symbol_tf_ts UNIQUE (symbol, timeframe, timestamp);

UPDATE model_predictions SET timestamp = timestamp - INTERVAL '3 hours';

UPDATE collection_status
   SET last_candle = last_candle - INTERVAL '3 hours'
 WHERE last_candle IS NOT NULL;

UPDATE collection_jobs
   SET first_timestamp = first_timestamp - INTERVAL '3 hours'
 WHERE first_timestamp IS NOT NULL;

UPDATE collection_jobs
   SET last_timestamp = last_timestamp - INTERVAL '3 hours'
 WHERE last_timestamp IS NOT NULL;

COMMIT;
