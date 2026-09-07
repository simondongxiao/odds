"""Build the v3.1 design report without recomputing any football pick."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import markdown

from render_football_risk_audit import css, payload

WORK = Path(r"D:\codex")
ROOT = WORK / "outputs/football_odds_trader"
SKILL = WORK / "skills/worldcup-odds-trader"
REPORT = ROOT / "reviews/execution_workflow_v31_20260907"
LOCAL = ROOT / "dashboard/audits/execution-workflow-v31-20260907"
PUBLIC = ROOT / "github_publish/odds"
sys.path.insert(0, str(SKILL / "scripts"))
import asian_risk_v3 as risk


def main():
    old = (ROOT / "backups/risk_workflow_v31_20260907/index.html").read_text(encoding="utf-8")
    current = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert payload(old) == payload(current), "Workflow documentation must not change match cards"
    REPORT.mkdir(parents=True, exist_ok=True)
    for name in ("v3-implementation-contract", "asian-side-risk-v3"):
        source = (SKILL / "references" / f"{name}.md").read_text(encoding="utf-8")
        (REPORT / f"{name}.md").write_text(source, encoding="utf-8")
        body = markdown.markdown(source, extensions=["tables", "fenced_code"])
        for linked in ("v3-implementation-contract", "asian-side-risk-v3"):
            body = body.replace(f'href="{linked}.md"', f'href="{linked}.html"')
        body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        html = f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>亚盘v3.1执行工作流</title><style>{css}</style></head><body><main>{body}</main></body></html>'
        (REPORT / f"{name}.html").write_text(html, encoding="utf-8")
    args = dict(masses=dict(zip(risk.OUTCOMES, [.54, 0, 0, 0, .46])), water=.96,
                effective_rate=risk.combined_rate(.6, 20, .56, 100), bankroll=10000,
                signed_handicap=-.5, fundamental_status="pass", conversion_passed=True,
                calibration_passed=True, remaining_capacity=1000)
    examples = {"synthetic_only": True, "not_real_matches_or_orders": True,
                "one_percent_unit_normal": risk.execution_plan(**args, unit_rate=.01),
                "one_percent_unit_high": risk.execution_plan(**args, unit_rate=.01, high_confidence=True),
                "five_percent_unit_normal": risk.execution_plan(**args),
                "five_percent_unit_high": risk.execution_plan(**args, high_confidence=True)}
    (REPORT / "synthetic_sizing_examples.json").write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    for destination in (LOCAL, PUBLIC / "audits/execution-workflow-v31-20260907"):
        shutil.copytree(REPORT, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("qa", "__pycache__"))
    shutil.copy2(ROOT / "dashboard/index.html", PUBLIC / "index.html")
    for relative in ("SKILL.md", "references/asian-side-risk-v3.md", "references/v3-implementation-contract.md",
                     "scripts/asian_risk_v3.py", "scripts/test_asian_risk_v3.py"):
        shutil.copy2(SKILL / relative, PUBLIC / "skills/worldcup-odds-trader" / relative)
    for name in ("build_football_dashboard.py", "publish_football_dashboard_to_github.py", "render_football_execution_workflow.py"):
        shutil.copy2(WORK / "tools" / name, PUBLIC / "tools" / name)
    print(json.dumps(examples, ensure_ascii=False))
    print("match_payload_unchanged=True")
    print("html_text_sha256=" + hashlib.sha256(current.encode()).hexdigest())
    print(LOCAL / "v3-implementation-contract.html")


if __name__ == "__main__":
    main()
