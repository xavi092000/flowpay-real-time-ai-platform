{{ config(materialized='view') }}

SELECT
  run_id,

  decision_quality_metrics.total_windows,
  decision_quality_metrics.avg_mrs,
  decision_quality_metrics.max_mrs,
  decision_quality_metrics.min_mrs,
  decision_quality_metrics.mrs_trend,
  decision_quality_metrics.escalation_rate,
  decision_quality_metrics.human_review_rate,
  decision_quality_metrics.technical_confidence_rate,

  -- 🔥 FinOps metrics
  finops_metrics.event_count,
  finops_metrics.total_estimated_cost_usd,
  finops_metrics.cost_per_decision_usd,
  finops_metrics.estimated_lambda_cost_usd,
  finops_metrics.estimated_stepfunctions_cost_usd,
  finops_metrics.estimated_s3_put_cost_usd

FROM flowpay_decision_metrics_raw
