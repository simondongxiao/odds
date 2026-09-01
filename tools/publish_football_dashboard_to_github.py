from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
from pathlib import Path


WORKSPACE = Path(r"D:\codex")
ROOT = WORKSPACE / "outputs" / "football_odds_trader"
PUBLISH_REPO = ROOT / "github_publish" / "odds"


def latest_file(root: Path, pattern: str) -> Path | None:
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def copy_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def run_git(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(PUBLISH_REPO), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )


def publish(push: bool = True) -> dict[str, object]:
    if not PUBLISH_REPO.exists():
        raise FileNotFoundError(f"publish repo not found: {PUBLISH_REPO}")
    if not (PUBLISH_REPO / ".git").exists():
        raise FileNotFoundError(f"publish repo is not a git repo: {PUBLISH_REPO}")

    copied: list[str] = []
    pairs = [
        (ROOT / "dashboard" / "index.html", PUBLISH_REPO / "index.html"),
        (WORKSPACE / "skills" / "worldcup-odds-trader" / "SKILL.md", PUBLISH_REPO / "skills" / "worldcup-odds-trader" / "SKILL.md"),
        (WORKSPACE / "tools" / "sequential_asian_backtest_engine.py", PUBLISH_REPO / "tools" / "sequential_asian_backtest_engine.py"),
        (WORKSPACE / "tools" / "build_football_dashboard.py", PUBLISH_REPO / "tools" / "build_football_dashboard.py"),
        (WORKSPACE / "tools" / "build_football_daily_update.py", PUBLISH_REPO / "tools" / "build_football_daily_update.py"),
        (WORKSPACE / "tools" / "rebuild_top5_country_tier_tables.py", PUBLISH_REPO / "tools" / "rebuild_top5_country_tier_tables.py"),
        (WORKSPACE / "tools" / "build_top5_high_win_side_policy.py", PUBLISH_REPO / "tools" / "build_top5_high_win_side_policy.py"),
        (WORKSPACE / "tools" / "export_current_intent_matches.py", PUBLISH_REPO / "tools" / "export_current_intent_matches.py"),
        (WORKSPACE / "tools" / "publish_football_dashboard_to_github.py", PUBLISH_REPO / "tools" / "publish_football_dashboard_to_github.py"),
        (ROOT / "ledger" / "DATA_STRUCTURE.md", PUBLISH_REPO / "docs" / "DATA_STRUCTURE.md"),
    ]

    latest_outputs = [
        (ROOT / "daily", "*_titan007_strict_update.md", PUBLISH_REPO / "reports" / "daily"),
        (ROOT / "reviews", "grouped_edge_review_*.md", PUBLISH_REPO / "reports" / "reviews"),
        (ROOT / "reviews", "micro_region_tag_edge_*.md", PUBLISH_REPO / "reports" / "reviews"),
        (ROOT / "reviews", "snapshot_drift_*.md", PUBLISH_REPO / "reports" / "reviews"),
        (ROOT / "backtests" / "sequential_asian", "sequential_asian_backtest_*.md", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "sequential_asian", "sequential_asian_backtest_*_summary.json", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "sequential_asian", "sequential_asian_backtest_*_intent_matches.csv", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "sequential_asian", "sequential_asian_backtest_*_by_region.csv", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "sequential_asian", "sequential_asian_backtest_*_by_tag.csv", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "sequential_asian", "sequential_asian_backtest_*_by_type.csv", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "sequential_asian", "current_intent_matches_*.csv", PUBLISH_REPO / "backtests" / "sequential_asian"),
        (ROOT / "backtests" / "top5_tier_split", "top5_tier_split_backtest_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_tier_split_by_league_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_tier_split_backtest_*_clean.md", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_region_full_sample_matches_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_region_full_sample_summary_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_region_full_ledger_matches_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_region_full_ledger_summary_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
        (ROOT / "backtests" / "top5_tier_split", "top5_dashboard_policy_audit_*.csv", PUBLISH_REPO / "backtests" / "top5_tier_split"),
    ]
    for root, pattern, dst_dir in latest_outputs:
        src = latest_file(root, pattern)
        if src:
            pairs.append((src, dst_dir / src.name))

    for src, dst in pairs:
        if copy_file(src, dst):
            copied.append(str(dst))

    readme = PUBLISH_REPO / "README.md"
    readme.write_text(
        "# Football Odds Dashboard\n\n"
        "This public snapshot is generated from `D:\\codex\\outputs\\football_odds_trader`.\n\n"
        "- Dashboard: `index.html`\n"
        "- Latest reports: `reports/`\n"
        "- Latest sequential backtest: `backtests/sequential_asian/`\n"
        "- Skill and scripts: `skills/`, `tools/`\n",
        encoding="utf-8",
    )
    copied.append(str(readme))

    add = run_git(["add", "-A"])
    if add.returncode != 0:
        return {"copied": copied, "committed": False, "pushed": False, "error": add.stderr.strip() or add.stdout.strip()}

    diff = run_git(["diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return {"copied": copied, "committed": False, "pushed": False, "message": "no changes"}

    message = f"Update football odds dashboard {dt.datetime.now():%Y-%m-%d %H:%M}"
    commit = run_git(["commit", "-m", message])
    if commit.returncode != 0:
        return {"copied": copied, "committed": False, "pushed": False, "error": commit.stderr.strip() or commit.stdout.strip()}

    if not push:
        return {"copied": copied, "committed": True, "pushed": False, "message": "committed without push"}

    push_result = run_git(["push", "origin", "HEAD"], timeout=180)
    if push_result.returncode != 0:
        return {
            "copied": copied,
            "committed": True,
            "pushed": False,
            "error": push_result.stderr.strip() or push_result.stdout.strip(),
        }
    return {"copied": copied, "committed": True, "pushed": True, "message": push_result.stdout.strip()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync football dashboard and latest reports to GitHub publish repo.")
    parser.add_argument("--no-push", action="store_true", help="Copy and commit only; do not push.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = publish(push=not args.no_push)
    print(f"copied={len(result.get('copied', []))}")
    print(f"committed={result.get('committed')}")
    print(f"pushed={result.get('pushed')}")
    if result.get("error"):
        print(f"error={result['error']}")
        return 1
    if result.get("message"):
        print(f"message={result['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
