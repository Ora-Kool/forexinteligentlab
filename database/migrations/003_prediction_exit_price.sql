-- Add research exit (next-bar close) price to scored predictions.
ALTER TABLE model_predictions
  ADD COLUMN IF NOT EXISTS exit_price DOUBLE PRECISION;
