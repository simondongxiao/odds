/**
 * Cloudflare Worker Cron -> GitHub Actions dispatcher.
 *
 * Deploy with two Cron Triggers: `7 12 * * *` and `7 21 * * *` (UTC).
 * Store a fine-grained GitHub token with Actions:write for this repository in
 * the Worker secret GITHUB_TOKEN. The Worker never needs repository contents.
 * This file is a deployable template; it is not deployed by this commit.
 */
const SLOTS = {
  "7 12 * * *": { workflow: "football-cloud-2000.yml", hour: 20, minute: 7, mode: "evening" },
  "7 21 * * *": { workflow: "football-cloud-0500.yml", hour: 5, minute: 7, mode: "morning" },
};

function isoBjt(date) {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  const h = String(date.getUTCHours()).padStart(2, "0");
  const mi = String(date.getUTCMinutes()).padStart(2, "0");
  return `${y}-${m}-${d}T${h}:${mi}:00+08:00`;
}

export default {
  async scheduled(controller, env, ctx) {
    const slot = SLOTS[controller.cron];
    if (!slot) throw new Error(`Unsupported cron slot: ${controller.cron}`);
    const planned = new Date(controller.scheduledTime);
    const plannedBjt = isoBjt(new Date(planned.getTime() + 8 * 3600 * 1000));
    // The target date is deliberately explicit so a delayed 20:07 dispatch
    // crossing Beijing midnight cannot be interpreted as the next-next day.
    const target = new Date(planned.getTime() + (slot.mode === "evening" ? 24 : 8) * 3600 * 1000);
    const targetDate = target.toISOString().slice(0, 10);
    const url = `https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/${slot.workflow}/dispatches`;
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "odds-football-cron-worker/1",
      },
      body: JSON.stringify({
        ref: env.GITHUB_REF || "main",
        inputs: { target_date: targetDate, planned_run_bjt: plannedBjt },
      }),
    });
    if (!response.ok) throw new Error(`GitHub dispatch failed ${response.status}: ${await response.text()}`);
    ctx.waitUntil(Promise.resolve());
  },
};
