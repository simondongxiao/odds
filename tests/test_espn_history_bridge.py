import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "basketball_engine"))
sys.path.insert(0, str(ROOT / "basketball_engine" / "scripts"))

from providers.espn_history_adapter import _final_score_summary  # noqa: E402


def _summary():
    def competitor(team_id, name, side, periods, score):
        return {
            "homeAway": side,
            "score": str(score),
            "team": {"id": str(team_id), "displayName": name},
            # Completed ESPN payloads use displayValue, not value.
            "linescores": [{"displayValue": str(x)} for x in periods],
        }

    def box(team_id):
        return {
            "team": {"id": str(team_id)},
            "statistics": [
                {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "40-80"},
                {"name": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "displayValue": "10-30"},
                {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "20-25"},
                {"name": "offensiveRebounds", "displayValue": "8"},
                {"name": "totalTurnovers", "displayValue": "12"},
                {"name": "points", "displayValue": "110"},
            ],
        }

    return {
        "header": {
            "date": "2026-10-01T23:00:00Z",
            "league": {"abbreviation": "NBA", "name": "National Basketball Association"},
            "competitions": [{
                "date": "2026-10-01T23:00:00Z",
                "competitors": [
                    competitor(1, "Home Team", "home", [28, 27, 30, 25], 110),
                    competitor(2, "Away Team", "away", [25, 29, 24, 27], 105),
                ],
            }],
        },
        "boxscore": {"teams": [box(1), box(2)]},
    }


def test_completed_summary_accepts_display_value_and_derives_possessions():
    row = _final_score_summary(_summary(), "fixture", "https://example.test/summary", "raw.json", "2026-10-02T00:00:00Z")
    assert row is not None
    assert row["evidence_kind"] == "TEAM_HISTORY"
    assert row["source_evidence_kind"] == "ESPN_BOX_SCORE"
    assert row["box_score_teams"][0]["possessions_estimate"] == 95.0
