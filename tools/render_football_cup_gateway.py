"""Publish the cup/rotation design and code without recomputing match decisions."""
import hashlib
from pathlib import Path
import shutil

import markdown

from render_football_risk_audit import css, payload

WORK = Path(r"D:\codex")
ROOT = WORK / "outputs/football_odds_trader"
SKILL = WORK / "skills/worldcup-odds-trader"
REPORT = ROOT / "reviews/cup_rotation_gateway_20260907"
LOCAL = ROOT / "dashboard/audits/cup-rotation-gateway-20260907"
PUBLIC = ROOT / "github_publish/odds"


def main():
    old = (ROOT / "backups/cup_rotation_gateway_20260907/index.html").read_text(encoding="utf-8")
    current = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    assert payload(old) == payload(current), "Historical match data changed"
    REPORT.mkdir(parents=True, exist_ok=True)
    source = (SKILL / "references/cup-rotation-gateway.md").read_text(encoding="utf-8")
    code = (SKILL / "scripts/cup_rotation_gateway.py").read_text(encoding="utf-8")
    document = source + "\n\n## 完整Python实现\n\n```python\n" + code + "\n```\n"
    (REPORT / "cup-rotation-gateway.md").write_text(document, encoding="utf-8")
    body = markdown.markdown(document, extensions=["tables", "fenced_code"])
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    html = f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>杯赛与轮换前置网关</title><style>{css}</style></head><body><main>{body}</main></body></html>'
    (REPORT / "cup-rotation-gateway.html").write_text(html, encoding="utf-8")
    for destination in (LOCAL, PUBLIC / "audits/cup-rotation-gateway-20260907"):
        shutil.copytree(REPORT, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("qa", "__pycache__"))
    shutil.copy2(ROOT / "dashboard/index.html", PUBLIC / "index.html")
    for relative in ("SKILL.md", "references/cup-rotation-gateway.md", "scripts/cup_rotation_gateway.py", "scripts/test_cup_rotation_gateway.py"):
        shutil.copy2(SKILL / relative, PUBLIC / "skills/worldcup-odds-trader" / relative)
    for name in ("build_football_dashboard.py", "publish_football_dashboard_to_github.py", "render_football_cup_gateway.py"):
        shutil.copy2(WORK / "tools" / name, PUBLIC / "tools" / name)
    print("match_payload_unchanged=True")
    print("html_text_sha256=" + hashlib.sha256(current.encode()).hexdigest())
    print(LOCAL / "cup-rotation-gateway.html")


if __name__ == "__main__":
    main()
