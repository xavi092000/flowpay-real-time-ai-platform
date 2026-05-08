{{ config(materialized='view') }}

SELECT
  run_id,
  agent_decision.final_output.mrs AS mrs,
  agent_decision.final_output.severity AS severity,
  agent_decision.final_output.action_bundle AS action_bundle,
  agent_decision.final_output.human_review_required AS human_review_required,
  agent_decision.final_output.technical_confidence AS technical_confidence
FROM flowpay_decisions