# V4 Shadow Data Contract

Prematch shadow fields are immutable after kickoff: match_id, list_date, kickoff, decision_at, prior_snapshot_id, odds_snapshot_id, evidence_snapshot_id, rule_version, model_version, kappa, competition, line, water, intent, candidate_team, candidate_side, posterior_EV_mean, EV_p10, P_EV_gt_0, shadow_grade, daily_rank, shadow_policy, reverse_shadow_status.

Post-match fields may be appended only: final_score, settlement, PnL_1u, result_source, settled_at. Forward shadow ledgers must not read historical replay rows as forward performance.
