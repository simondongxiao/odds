# Cloudflare Cron fallback (optional)

The repository keeps GitHub `schedule` as the built-in fallback. For an independent trigger when a scheduled GitHub event is delayed or dropped:

1. Create a Cloudflare Worker and paste `automation/cloudflare/football-cron-worker.js`.
2. Add Cron Triggers `7 12 * * *` and `7 21 * * *` UTC. These are 20:07 and 05:07 Beijing.
3. Set `GITHUB_REPOSITORY=simondongxiao/odds`, `GITHUB_REF=main`, and secret `GITHUB_TOKEN`.
4. Use a fine-grained token restricted to this repository with **Actions: Write** only. Do not put the token in the repository.
5. Test each trigger with the Worker preview, then inspect the resulting GitHub `workflow_dispatch` run and its `run_manifest.json`.

The worker passes `target_date` and `planned_run_bjt` explicitly. The workflow resolver treats those values as the planned slot, applies a 12-hour stale-run guard, and computes a deterministic run key (`target date + slot + content commit`) so a native schedule and the external trigger do not send duplicate Feishu success messages while a genuinely newer content version can still be published. The Worker is a configuration artifact only; it is not deployed by this repository commit.
