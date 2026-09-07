"""Render the dated audit and stage only its related public artifacts."""
from pathlib import Path
import hashlib
import shutil

import markdown

WORK = Path(r"D:\codex")
ROOT = WORK / "outputs/football_odds_trader"
AUDIT = ROOT / "reviews/direction_audit_20260907"
LOCAL = ROOT / "dashboard/audits/direction-audit-20260907"
PUBLIC = ROOT / "github_publish/odds"
SKILL = WORK / "skills/worldcup-odds-trader"

css = """body{margin:0;background:#f2f7fc;color:#173c58;font:16px/1.7 'Microsoft YaHei',Arial,sans-serif;letter-spacing:0}main{max-width:1100px;margin:auto;padding:24px}h1{font-size:26px;line-height:1.4;color:#155b96}h2{font-size:20px;color:#155b96;margin-top:28px;border-bottom:1px solid #bed3e5}a{color:#075da5}table{width:100%;border-collapse:collapse;font-size:14px;background:#fff}th,td{padding:9px;border:1px solid #bed3e5;vertical-align:top;overflow-wrap:anywhere}th{background:#dcecf9}pre{overflow:auto;background:#e7eef5;padding:12px}code{overflow-wrap:anywhere}p,li{overflow-wrap:anywhere}.table-wrap{overflow-x:auto}@media(max-width:600px){main{padding:14px}h1{font-size:23px}table{min-width:660px}}"""


def payload(html: str) -> str:
    start = html.index("const cardsData = ")
    end = html.index("\nconst stats = ", start)
    return html[start:end]


def main():
    old = (ROOT / "backups/skill_pre_risk_restructure_20260907/index.html").read_text(encoding="utf-8")
    current = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert payload(old) == payload(current), "Audit addition must not alter match data"
    AUDIT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL / "references/asian-side-risk-v3.md", AUDIT / "asian-side-risk-v3.md")
    for name in ("report", "asian-side-risk-v3"):
        body = markdown.markdown((AUDIT / f"{name}.md").read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
        body = body.replace('href="asian-side-risk-v3.md"', 'href="asian-side-risk-v3.html"')
        body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
        title = "9/4选边变化审计" if name == "report" else "亚盘风控v3完整工作流"
        html = f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{css}</style></head><body><main>{body}</main></body></html>'
        (AUDIT / f"{name}.html").write_text(html, encoding="utf-8")
    shutil.copytree(AUDIT, LOCAL, dirs_exist_ok=True, ignore=shutil.ignore_patterns("qa", "__pycache__"))
    shutil.copytree(LOCAL, PUBLIC / "audits/direction-audit-20260907", dirs_exist_ok=True, ignore=shutil.ignore_patterns("qa", "__pycache__"))
    shutil.copy2(ROOT / "dashboard/index.html", PUBLIC / "index.html")
    (PUBLIC / "skills/worldcup-odds-trader/scripts").mkdir(parents=True, exist_ok=True)
    (PUBLIC / "skills/worldcup-odds-trader/references").mkdir(parents=True, exist_ok=True)
    for rel in ("SKILL.md", "references/asian-side-risk-v3.md", "scripts/asian_risk_v3.py", "scripts/test_asian_risk_v3.py"):
        shutil.copy2(SKILL / rel, PUBLIC / "skills/worldcup-odds-trader" / rel)
    for name in ("build_football_dashboard.py", "publish_football_dashboard_to_github.py", "audit_football_snapshot_directions.cjs", "render_football_risk_audit.py"):
        shutil.copy2(WORK / "tools" / name, PUBLIC / "tools" / name)
    print("match_payload_unchanged=True")
    print("html_sha256=" + hashlib.sha256(current.encode()).hexdigest())
    print(LOCAL / "report.html")


if __name__ == "__main__":
    main()
