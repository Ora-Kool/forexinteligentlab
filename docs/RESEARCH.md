# Research experiments

The research engine asks a different question from Baseline V1:

> Under what conditions does a directional move survive estimated costs, and
> does that result repeat in unseen walk-forward periods?

It is paper research only. It never places orders.

## Baseline V1 remains

`backend/app/ml/` still contains the next-close logistic regression baseline.
New experiments do not replace or silently promote themselves into the live
collector. They are a separate control-and-challenger workflow.

## First research target

The first target is a side-specific triple barrier:

- Long candidate: TP above entry, SL below entry.
- Short candidate: TP below entry, SL above entry.
- TP and SL are ATR multiples.
- The event times out after a configured number of bars.
- Spread and transaction cost are subtracted from every accepted paper signal.
- A TP only receives a positive opportunity label when its net result also
  exceeds `minimum_edge_pips`.

If TP and SL touch in the same OHLC candle, intrabar ordering is unknowable.
The default is pessimistic (loss); experiments can instead exclude ambiguous
rows. The chosen policy is stored with the experiment.

## Evaluation contract

- Causal features only (`timestamp <= entry timestamp`).
- Expanding walk-forward folds.
- Maximum target horizon purged from fold boundaries.
- Threshold selected on an inner tuning tail, never the outer validation fold.
- Threshold objective: after-cost expectancy, not accuracy.
- UP, DOWN, or ABSTAIN.
- One active paper signal per symbol; overlapping signals are skipped.
- 95% bootstrap interval around mean net pips.
- Positive mean with an interval crossing zero is `NO_CONVINCING_EDGE`.
- Results are validation-only until a separately locked holdout engine exists.

## Reproducibility

`research_experiments` stores:

- workspace, symbol, timeframe, and immutable experiment code;
- target / feature / evaluator versions;
- full parameters and cost assumptions;
- a SHA-256 fingerprint of the exact candle dataset;
- aggregate metrics and scientific status.

`research_folds` stores every train/validation period, selected threshold, sample
count, signal count, and fold metrics.

## API and desk

```text
POST /api/research/experiments
GET  /api/research/experiments
GET  /api/research/experiments/{id}
```

Open **Research → Experiments** in the desk. A typical first run is:

```text
TP 1.5 ATR / SL 1.0 ATR / timeout 12 bars
4 folds / 1000 minimum training bars / 500 validation bars per fold
threshold candidates 0.50–0.85
same-bar ambiguity counted pessimistically
```

Do not interpret `PROMISING_VALIDATION` as profitability. It means only that the
validation evidence passed the current confidence rule. A locked final holdout,
cross-pair replication, and stress testing remain required.
