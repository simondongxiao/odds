"""V3 Legacy decision freeze engine.

The legacy page is the authoritative compatibility implementation for V3.
This Python entry point executes that exact legacy decision code against the
same cardsData input, then materializes immutable decision rows for bridge
and dashboard consumers. It intentionally does not alter business rules.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _cards_data(html: Path) -> str:
    text = html.read_text(encoding="utf-8")
    match = re.search(r"const cardsData = (.*?);\s*\n", text, re.S)
    if not match:
        raise RuntimeError("cardsData not found")
    return match.group(1).rstrip(";")


def run_legacy_engine(html: Path, list_date: str) -> list[dict[str, Any]]:
    text = html.read_text(encoding="utf-8")
    script = text[text.index("<script>") + len("<script>"):text.index("</script>")]
    script = re.sub(r"\ninit\(\);\s*$", "", script)
    export = f'''\nconst __legacy_rows = cardsData.filter(r => r.date === {json.dumps(list_date)}).map(r => {{
  const d = plannedSkillDecision(r);
  return {{match_id:r.match_id, match:r.match, action:d.action, selected_team:d.team,
    selected_side:d.mode === "reverse" ? reverseSide(r.intent_forward_side) : r.intent_forward_side,
    direction:d.mode === "reverse" ? "反向" : "正向", line:r.intent_line_bucket || "",
    water:d.water || 0, probability:d.rate || 0, threshold:d.threshold || 0,
    risk:(d.risk && d.risk["风控状态"]) || "", reason:d.reason || "",
    top5_status:(r.top5_policy && r.top5_policy.is_top5) ? "TOP5" : "STANDARD",
    rule_version:r.Cup_Refactor_Eligible ? (r.Cup_Gateway_Version || "V3_CUP_MATCH_STATE_R1_20260930") : "V3_LEGACY_PAGE_PARITY",
    cup_regression_guard:d.cupRegressionGuard || "",
    Cup_Refactor_Eligible:Boolean(r.Cup_Refactor_Eligible), Cup_Gateway_Status:r.Cup_Gateway_Status || "",
    Competition_Domain:r.Competition_Domain || "", Cup_Match_State:r.Cup_Match_State || "",
    Cup_Qualification_Utility:r.Cup_Qualification_Utility || "", Cup_Rotation_Risk:r.Cup_Rotation_Risk || "",
    Cup_Rest_Days:r.Cup_Rest_Days ?? "", Cup_Context_Missing:r.Cup_Context_Missing || "",
    Football_Pull_Score:r.Football_Pull_Score ?? "", Public_Pull:r.Public_Pull ?? "",
    fair_goal_margin:r.fair_goal_margin ?? "", fair_handicap:r.fair_handicap ?? "", line_gap:r.line_gap ?? "",
    Cup_Bayes_Level:r.Cup_Bayes_Level || "", Cup_Bayes_Posterior:r.Cup_Bayes_Posterior ?? "",
    Cup_Bayes_P10:r.Cup_Bayes_P10 ?? "", Cup_Bayes_Weight:r.Cup_Bayes_Weight ?? "",
    Cup_Intent:r.Cup_Intent || "", Cup_Raw_Intent:r.Cup_Raw_Intent || "", Cup_Intent_Reason:r.Cup_Intent_Reason || ""}};
}});
console.log(JSON.stringify(__legacy_rows));\n'''
    # The page script only needs a minimal DOM because init() is removed.
    source = (
        'var document={getElementById:function(){return {value:"",checked:false,addEventListener:function(){}}},querySelector:function(){return null}};'
        'var window={addEventListener:function(){}};\n' + script + export
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(source)
        temp = Path(f.name)
    try:
        proc = subprocess.run(["node", str(temp)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=True)
        return json.loads(proc.stdout.strip().splitlines()[-1])
    finally:
        temp.unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("list_date")
    parser.add_argument("--html", default=r"D:\codex\v3_legacy\dashboard\index.html")
    args = parser.parse_args()
    rows = run_legacy_engine(Path(args.html), args.list_date)
    print(json.dumps({"list_date": args.list_date, "rows": rows}, ensure_ascii=False))
