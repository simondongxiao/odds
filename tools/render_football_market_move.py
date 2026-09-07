"""Verify and publish the rule change without recalculating match decisions."""
import ast
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import unittest

import markdown

from render_football_risk_audit import css, payload

WORK = Path(r"D:\codex")
ROOT = WORK / "outputs/football_odds_trader"
SKILL = WORK / "skills/worldcup-odds-trader"
REPORT = ROOT / "reviews/market_move_20260908"
LOCAL = ROOT / "dashboard/audits/market-move-20260908"
PUBLIC = ROOT / "github_publish/odds"


def main():
    sys.path.insert(0, str(SKILL / "scripts"))
    result = unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromNames(
        ["test_asian_risk_v3", "test_cup_rotation_gateway", "test_market_move_guard"]))
    if not result.wasSuccessful():
        raise RuntimeError(str(result.errors + result.failures))
    current = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    for backup in ("market_move_weekend_20260907", "cancel_weekend_tightening_20260908"):
        old = (ROOT / "backups" / backup / "index.html").read_text(encoding="utf-8")
        assert payload(old) == payload(current), "Historical match data changed"
    template = (WORK / "tools/build_football_dashboard.py").read_text(encoding="utf-8")
    ast.parse(template)
    def js_section(text):
        return text[text.index("function cupContextRows"):text.index("function isOddsUnavailable")].strip()
    assert js_section(current) == js_section(template).replace("{{", "{").replace("}}", "}"), "Renderer/template drift"
    for relative in ("scripts/asian_risk_v3.py", "scripts/market_move_guard.py", "scripts/test_market_move_guard.py"):
        ast.parse((SKILL / relative).read_text(encoding="utf-8"))
    REPORT.mkdir(parents=True, exist_ok=True)
    checks = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "match_payload_unchanged": True, "template_matches_dashboard": True,
              "weekend_policy": "AUDIT_ONLY", "live_collector_migrated": False,
              "html_sha256": hashlib.sha256(current.encode()).hexdigest()}
    (REPORT / "verification.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    source = (SKILL / "references/market-move-weekend.md").read_text(encoding="utf-8")
    source += f"\n\n## 本次验收记录\n\n{result.testsRun}项自动化测试通过；与两份修改前备份逐项比较，比赛数据完全一致。HTML模板与当前网页渲染函数一致。未抓新赔率、未重算旧推荐、未执行真实投注。\n"
    (REPORT / "market-move-weekend.md").write_text(source, encoding="utf-8")
    body = markdown.markdown(source, extensions=["tables", "fenced_code"])
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>临场改向审查：周末不加严</title><style>{css}</style></head><body><main>{body}</main></body></html>'
    (REPORT / "market-move-weekend.html").write_text(html, encoding="utf-8")
    for destination in (LOCAL, PUBLIC / "audits/market-move-20260908"):
        shutil.copytree(REPORT, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("qa", "__pycache__"))
    shutil.copy2(ROOT / "dashboard/index.html", PUBLIC / "index.html")
    for relative in ("SKILL.md", "references/asian-side-risk-v3.md", "references/v3-implementation-contract.md",
                     "references/market-move-weekend.md", "scripts/asian_risk_v3.py", "scripts/test_asian_risk_v3.py",
                     "scripts/market_move_guard.py", "scripts/test_market_move_guard.py"):
        shutil.copy2(SKILL / relative, PUBLIC / "skills/worldcup-odds-trader" / relative)
    for name in ("build_football_dashboard.py", "publish_football_dashboard_to_github.py", "render_football_market_move.py"):
        shutil.copy2(WORK / "tools" / name, PUBLIC / "tools" / name)
    print(json.dumps(checks, ensure_ascii=False))
    print(LOCAL / "market-move-weekend.html")


if __name__ == "__main__":
    main()
