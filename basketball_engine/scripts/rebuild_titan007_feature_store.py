"""One-time/incremental rebuild of Titan player and derived feature tables."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from providers.titan007_history_adapter import (  # noqa: E402
    TitanHistoryStore, parse_box_score_blob, _season_for, _rebuild_team_stat_tables,
)
from providers.titan007_feature_store import (  # noqa: E402
    upsert_player_boxscores, rebuild_team_game_features, evaluate_source_capabilities,
    rebuild_player_season_stats, PARSER_VERSION, FIELD_CONTRACT_VERSION,
)


def rebuild(root):
    store = TitanHistoryStore(root)
    db = store.db
    db.row_factory = None
    now = datetime.now(timezone.utc).isoformat()
    total_players, parsed, failed = 0, 0, []
    try:
        snapshots = db.execute(
            "SELECT s.entity_id,s.snapshot_id,s.raw_path,s.sha256,s.captured_at "
            "FROM source_snapshot s JOIN (SELECT entity_id,MAX(captured_at) captured_at "
            "FROM source_snapshot WHERE entity_type='tech' GROUP BY entity_id) x "
            "ON x.entity_id=s.entity_id AND x.captured_at=s.captured_at WHERE s.entity_type='tech' "
            "ORDER BY CAST(s.entity_id AS INTEGER)").fetchall()
        for start in range(0, len(snapshots), 500):
            tech, tech_snapshots, matches = {}, {}, {}
            for match_id, snapshot_id, raw_path, digest, captured_at in snapshots[start:start+500]:
                row = db.execute(
                    "SELECT titan_match_id,league_id,league,tip_at,home_titan_team_id,away_titan_team_id,"
                    "home_score,away_score,match_kind,status FROM match_history WHERE titan_match_id=?",
                    (match_id,)).fetchone()
                if not row:
                    continue
                try:
                    text = Path(raw_path).read_text(encoding="utf-8-sig")
                    tech[match_id] = parse_box_score_blob(text)
                    tech_snapshots[match_id] = (snapshot_id, raw_path, digest, captured_at)
                    matches[match_id] = {
                        "match_id": row[0], "league_id": row[1], "league": row[2], "tip_at": row[3],
                        "home_team_id": row[4], "away_team_id": row[5], "home_score": row[6],
                        "away_score": row[7], "match_kind": row[8], "status": row[9],
                    }
                    parsed += 1
                except Exception as exc:
                    failed.append({"match_id": match_id, "error": type(exc).__name__ + ": " + str(exc)})
            total_players += upsert_player_boxscores(
                db, matches, tech, tech_snapshots, set(), now, _season_for)
            db.commit()
        league_ids = {row[0] for row in db.execute("SELECT DISTINCT league_id FROM team_game_stat")}
        aggregate = _rebuild_team_stat_tables(store, datetime.now(timezone.utc), league_ids)
        features = rebuild_team_game_features(db, datetime.now(timezone.utc), league_ids)
        player_seasons = rebuild_player_season_stats(db, datetime.now(timezone.utc))
        capabilities = evaluate_source_capabilities(db, datetime.now(timezone.utc))
        db.execute(
            "UPDATE source_snapshot SET request_at=COALESCE(request_at,captured_at),"
            "response_at=COALESCE(response_at,captured_at),http_status=COALESCE(http_status,200),"
            "parser_version=COALESCE(parser_version,?),field_contract_version=COALESCE(field_contract_version,?)",
            (PARSER_VERSION, FIELD_CONTRACT_VERSION))
        db.commit()
        report = {"generated_at": now, "database": str(store.db_path),
                  "tech_snapshots": len(snapshots), "parsed_snapshots": parsed,
                  "player_game_rows_written": total_players,
                  "player_game_rows_total": db.execute("SELECT COUNT(*) FROM player_game_boxscore").fetchone()[0],
                  "player_count": db.execute("SELECT COUNT(*) FROM player").fetchone()[0],
                  "team_game_features": features, "aggregate": aggregate,
                  "player_season_stats": player_seasons,
                  "source_capabilities": capabilities, "failures": failed[:100],
                  "failure_count": len(failed), "market_inputs_used": False,
                  "qualified_or_provisional_ledger_modified": False,
                  "real_execution_allowed": False}
        path = Path(root) / "feature_store_rebuild_audit.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path, report
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"D:\codex\outputs\basketball_odds_trader\reference_data\titan007_history")
    args = parser.parse_args()
    output, audit = rebuild(args.root)
    print(json.dumps({"audit": str(output), **{k: audit[k] for k in
          ("tech_snapshots", "parsed_snapshots", "player_game_rows_total", "player_count", "team_game_features", "failure_count")}},
          ensure_ascii=False, indent=2))
