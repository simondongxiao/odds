"""Cutoff-safe Titan007 basketball feature store and pricing challenger.

This module is part of the existing basketball-odds-trader pipeline.  It
derives features only from immutable source facts already captured by the
Titan adapter.  Market prices are intentionally absent from every function
that creates a team state or theoretical price.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone


SCHEMA_VERSION = "titan-feature-store-1.0"
PARSER_VERSION = "titan-tech-player-v1"
FIELD_CONTRACT_VERSION = "titan-tech-27f-team16f-v1"

# The official Titan fair-price path is league-average anchored.  These are
# calibration-sample policies, not team-history gates and they never alter the
# independent 8-game/3-opponent evidence gate elsewhere in the pipeline.
EFFICIENCY_BETA_FEATURES = ("delta_efg", "delta_tov", "delta_orb", "delta_ftr", "delta_3pa")
EFFICIENCY_LEAGUE_MIN_OBS = 30
EFFICIENCY_GLOBAL_MIN_OBS = 60
EFFICIENCY_BASELINE_PRIOR = (0.5, 0.5, 0.0, 0.0, 0.0, 0.0, 0.0)


def _iso(value):
    if isinstance(value, datetime):
        out = value
    else:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return out.replace(tzinfo=timezone.utc) if out.tzinfo is None else out.astimezone(timezone.utc)


def _stamp(value=None):
    return _iso(value or datetime.now(timezone.utc)).isoformat()


def _mean(values, weights=None):
    pairs = [(float(v), 1.0 if weights is None else float(weights[i]))
             for i, v in enumerate(values) if v is not None and math.isfinite(float(v))]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def _ratio(a, b):
    return float(a) / float(b) if a is not None and b is not None and float(b) > 0 else None


def _quantile(values, q):
    seq = sorted(float(v) for v in values if v is not None and math.isfinite(float(v)))
    if not seq:
        return None
    pos = (len(seq) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return seq[lo] if lo == hi else seq[lo] * (hi - pos) + seq[hi] * (pos - lo)


def _regulation_minutes(league_id, league_name=""):
    label = str(league_name or "").upper()
    if str(league_id) == "1" or ("NBA" in label and "WNBA" not in label):
        return 48
    return 40


def ensure_feature_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS player(
      titan_player_id TEXT PRIMARY KEY, name_zh TEXT, name_tw TEXT, name_en TEXT,
      display_name TEXT, position TEXT, jersey_number TEXT, image_path TEXT,
      latest_source_snapshot_id TEXT, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS league(
      league_id TEXT PRIMARY KEY, league_name TEXT, regulation_minutes REAL,
      source_capability_grade TEXT, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS period_score(
      titan_match_id TEXT NOT NULL, period_number INTEGER NOT NULL,
      home_points REAL, away_points REAL, period_type TEXT NOT NULL,
      source_snapshot_id TEXT, updated_at TEXT NOT NULL,
      PRIMARY KEY(titan_match_id,period_number));
    CREATE TABLE IF NOT EXISTS player_game_boxscore(
      titan_match_id TEXT NOT NULL, titan_team_id TEXT NOT NULL,
      opponent_titan_team_id TEXT NOT NULL, titan_player_id TEXT NOT NULL,
      league_id TEXT NOT NULL, season TEXT NOT NULL, tip_at TEXT NOT NULL,
      is_home INTEGER NOT NULL, starter INTEGER, minutes REAL,
      fgm REAL, fga REAL, three_pm REAL, three_pa REAL, ftm REAL, fta REAL,
      orb REAL, drb REAL, reb REAL, ast REAL, pf REAL, stl REAL, tov REAL,
      blk REAL, pts REAL, plus_minus REAL, source_snapshot_id TEXT NOT NULL,
      parser_version TEXT NOT NULL, field_contract_version TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(titan_match_id,titan_team_id,titan_player_id));
    CREATE INDEX IF NOT EXISTS idx_player_game_team_tip
      ON player_game_boxscore(titan_team_id,tip_at);
    CREATE INDEX IF NOT EXISTS idx_player_game_lookup
      ON player_game_boxscore(titan_team_id,league_id,season,tip_at DESC);
    CREATE TABLE IF NOT EXISTS player_season_stat(
      league_id TEXT NOT NULL, season TEXT NOT NULL, titan_team_id TEXT NOT NULL,
      titan_player_id TEXT NOT NULL, games INTEGER NOT NULL, starts INTEGER NOT NULL,
      minutes REAL, fgm REAL, fga REAL, three_pm REAL, three_pa REAL,
      ftm REAL, fta REAL, orb REAL, drb REAL, reb REAL, ast REAL, pf REAL,
      stl REAL, tov REAL, blk REAL, pts REAL, plus_minus REAL,
      cutoff_at TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(league_id,season,titan_team_id,titan_player_id));
    CREATE TABLE IF NOT EXISTS market_history(
      quote_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, source TEXT,
      bookmaker TEXT, market_type TEXT NOT NULL, period TEXT, ot_rule TEXT,
      line_team1 REAL, raw_line REAL, decimal_prices_json TEXT,
      source_quote_at TEXT, received_at TEXT, status TEXT, raw_path TEXT,
      observation_hash TEXT NOT NULL, independent_model_eligible INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS source_capability(
      league_id TEXT NOT NULL, season TEXT NOT NULL, capability_grade TEXT NOT NULL,
      schedule_history INTEGER NOT NULL, period_scores INTEGER NOT NULL,
      team_boxscore INTEGER NOT NULL, player_boxscore INTEGER NOT NULL,
      team_profile INTEGER NOT NULL, league_rank INTEGER NOT NULL,
      final_games INTEGER NOT NULL, period_games INTEGER NOT NULL,
      team_boxscore_games INTEGER NOT NULL, player_boxscore_games INTEGER NOT NULL,
      period_coverage REAL, team_boxscore_coverage REAL, player_boxscore_coverage REAL,
      missing_fields_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
      evaluated_at TEXT NOT NULL, PRIMARY KEY(league_id,season));
    CREATE TABLE IF NOT EXISTS team_game_feature(
      titan_match_id TEXT NOT NULL, titan_team_id TEXT NOT NULL,
      opponent_titan_team_id TEXT NOT NULL, league_id TEXT NOT NULL,
      season TEXT NOT NULL, match_kind INTEGER, tip_at TEXT NOT NULL,
      is_home INTEGER NOT NULL, regulation_minutes REAL NOT NULL,
      actual_minutes REAL NOT NULL, game_possessions REAL, regulation_pace REAL,
      ortg REAL, drtg REAL, netrtg REAL, efg_pct REAL, tov_pct REAL,
      orb_pct REAL, ft_rate REAL, defensive_efg_pct REAL, defensive_tov_pct REAL,
      defensive_orb_pct REAL, opponent_ft_rate REAL, pf_per_100 REAL,
      opponent_fta_per_100 REAL, pregame_opponent_netrtg REAL,
      opponent_strength_bucket TEXT, adjusted_ortg REAL, adjusted_drtg REAL,
      adjusted_netrtg REAL, quarter_json TEXT NOT NULL, source_snapshot_id TEXT NOT NULL,
      feature_contract_version TEXT NOT NULL, updated_at TEXT NOT NULL,
      PRIMARY KEY(titan_match_id,titan_team_id));
    CREATE INDEX IF NOT EXISTS idx_team_feature_team_tip
      ON team_game_feature(titan_team_id,league_id,tip_at);
    CREATE INDEX IF NOT EXISTS idx_team_feature_lookup
      ON team_game_feature(titan_team_id,league_id,season,match_kind,tip_at DESC);
    CREATE TABLE IF NOT EXISTS team_state_feature(
      state_id TEXT PRIMARY KEY, titan_team_id TEXT NOT NULL, league_id TEXT NOT NULL,
      season TEXT NOT NULL, phase_code TEXT NOT NULL, cutoff_at TEXT NOT NULL,
      games INTEGER NOT NULL, distinct_opponents INTEGER NOT NULL, ess REAL NOT NULL,
      metrics_json TEXT NOT NULL, style_vector_json TEXT NOT NULL,
      tactical_splits_json TEXT NOT NULL, roster_continuity_json TEXT NOT NULL,
      sos_json TEXT NOT NULL, capability_grade TEXT NOT NULL,
      source_max_tip_at TEXT, market_inputs_used INTEGER NOT NULL DEFAULT 0,
      feature_hash TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_team_state_lookup
      ON team_state_feature(titan_team_id,league_id,cutoff_at);
    CREATE INDEX IF NOT EXISTS idx_market_history_event_time
      ON market_history(event_id,market_type,received_at DESC);
    CREATE TABLE IF NOT EXISTS league_environment(
      environment_id TEXT PRIMARY KEY, league_id TEXT NOT NULL, season TEXT NOT NULL,
      phase_code TEXT NOT NULL, cutoff_at TEXT NOT NULL, games INTEGER NOT NULL,
      regulation_minutes REAL, pace REAL, ortg REAL, home_advantage REAL,
      average_total REAL, close_game_count INTEGER NOT NULL,
      observed_ot_games INTEGER NOT NULL, observed_ot_points REAL,
      late_foul_premium REAL, late_foul_status TEXT NOT NULL,
      source_max_tip_at TEXT, market_inputs_used INTEGER NOT NULL DEFAULT 0,
      payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS matchup_feature(
      matchup_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, league_id TEXT NOT NULL,
      cutoff_at TEXT NOT NULL, team1_titan_id TEXT NOT NULL, team2_titan_id TEXT NOT NULL,
      expected_team1_score REAL, expected_team2_score REAL,
      expected_margin REAL, fair_handicap_team1 REAL, fair_total REAL,
      model_b_json TEXT NOT NULL, model_c_json TEXT NOT NULL,
      ensemble_json TEXT NOT NULL, top_factors_json TEXT NOT NULL,
      source_max_tip_at TEXT, market_inputs_used INTEGER NOT NULL DEFAULT 0,
      feature_hash TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS pregame_snapshot(
      snapshot_id TEXT PRIMARY KEY, event_id TEXT NOT NULL, cutoff_at TEXT NOT NULL,
      model_version TEXT NOT NULL, league_id TEXT, team1_titan_id TEXT,
      team2_titan_id TEXT, expected_team1_score REAL, expected_team2_score REAL,
      fair_margin REAL, fair_spread_team1 REAL, fair_total REAL,
      feature_hash TEXT NOT NULL, payload_hash TEXT NOT NULL,
      source_max_tip_at TEXT, market_inputs_used INTEGER NOT NULL DEFAULT 0,
      immutable INTEGER NOT NULL DEFAULT 1, payload_json TEXT NOT NULL,
      created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_matchup_event_cutoff
      ON matchup_feature(event_id,cutoff_at DESC);
    CREATE INDEX IF NOT EXISTS idx_pregame_event_cutoff
      ON pregame_snapshot(event_id,cutoff_at DESC);
    CREATE VIEW IF NOT EXISTS leagues AS SELECT * FROM league;
    CREATE VIEW IF NOT EXISTS teams AS SELECT * FROM team;
    CREATE VIEW IF NOT EXISTS players AS SELECT * FROM player;
    CREATE VIEW IF NOT EXISTS games AS SELECT * FROM match_history;
    CREATE VIEW IF NOT EXISTS team_game_boxscore AS SELECT * FROM team_game_stat;
    CREATE VIEW IF NOT EXISTS period_scores AS SELECT * FROM period_score;
    CREATE VIEW IF NOT EXISTS team_state_features AS SELECT * FROM team_state_feature;
    CREATE VIEW IF NOT EXISTS matchup_features AS SELECT * FROM matchup_feature;
    """)
    # Source metadata was introduced after the original immutable store.
    columns = {row[1] for row in db.execute("PRAGMA table_info(source_snapshot)")}
    for name, definition in (
        ("request_at", "TEXT"), ("response_at", "TEXT"), ("http_status", "INTEGER"),
        ("parser_version", "TEXT"), ("field_contract_version", "TEXT")):
        if name not in columns:
            db.execute(f"ALTER TABLE source_snapshot ADD COLUMN {name} {definition}")
    db.commit()


def upsert_player_boxscores(db, matches, tech_data, tech_snapshots, invalid_periods, updated_at, season_for):
    ensure_feature_schema(db)
    rows = []
    for match_id, box in tech_data.items():
        match = matches.get(match_id)
        if not match or match_id in invalid_periods or match.get("status") != "FINAL":
            continue
        snapshot = tech_snapshots.get(match_id)
        snapshot_id = snapshot[0] if snapshot else "UNKNOWN"
        team_ids = [match["home_team_id"], match["away_team_id"]]
        season = season_for(match["league_id"], match["tip_at"])
        for side, players in enumerate((box.get("home_players") or [], box.get("away_players") or [])):
            for player in players:
                pid = player["player_id"]
                db.execute(
                    "INSERT INTO player VALUES(?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(titan_player_id) DO UPDATE SET "
                    "name_zh=excluded.name_zh,name_tw=excluded.name_tw,name_en=excluded.name_en,"
                    "display_name=excluded.display_name,position=excluded.position,"
                    "jersey_number=excluded.jersey_number,image_path=excluded.image_path,"
                    "latest_source_snapshot_id=excluded.latest_source_snapshot_id,updated_at=excluded.updated_at",
                    (pid, player.get("name_zh"), player.get("name_tw"), player.get("name_en"),
                     player.get("display_name"), player.get("position"), player.get("jersey_number"),
                     player.get("image_path"), snapshot_id, updated_at))
                stat_values = [player.get(name) for name in
                               ("FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "ORB", "DRB",
                                "REB", "AST", "PF", "STL", "TOV", "BLK", "PTS")]
                rows.append((match_id, team_ids[side], team_ids[1-side], pid,
                             match["league_id"], season, match["tip_at"], int(side == 0),
                             player.get("starter"), player.get("MIN"), *stat_values,
                             player.get("plus_minus"), snapshot_id, PARSER_VERSION,
                             FIELD_CONTRACT_VERSION, updated_at))
    if rows:
        db.executemany(
            "INSERT OR REPLACE INTO player_game_boxscore VALUES(" + ",".join("?" for _ in range(30)) + ")",
            rows)
    return len(rows)


def _quarter_payload(own, opp, is_home):
    try:
        home = json.loads(own["periods_home_json"] or "[]")
        away = json.loads(own["periods_away_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        home, away = [], []
    if not isinstance(home, list):
        home = []
    if not isinstance(away, list):
        away = []
    team, other = (home, away) if is_home else (away, home)
    quarters = []
    cumulative = 0
    for index, (a, b) in enumerate(zip(team[:4], other[:4]), 1):
        cumulative += float(a) - float(b)
        quarters.append({"quarter": index, "points_for": a, "points_against": b,
                         "margin": float(a) - float(b), "cumulative_margin": cumulative})
    if len(quarters) == 4:
        entering = quarters[2]["cumulative_margin"]
        state = "LEADING" if entering > 4 else "TRAILING" if entering < -4 else "CLOSE"
    else:
        state = "UNAVAILABLE"
    return {"quarters": quarters, "entering_q4_state": state,
            "blowout": bool(abs(cumulative) >= 15) if quarters else None}


def rebuild_team_game_features(db, cutoff, league_ids=None):
    """Rebuild derived game features chronologically with strict as-of inputs."""
    ensure_feature_schema(db)
    cutoff_at = _stamp(cutoff)
    params = [cutoff_at]
    clause = ""
    if league_ids:
        values = sorted({str(v) for v in league_ids})
        clause = " AND g.league_id IN (" + ",".join("?" for _ in values) + ")"
        params.extend(values)
    db.row_factory = sqlite3.Row
    raw = db.execute(
        "SELECT g.*,o.pts opponent_pts,o.fgm opponent_fgm,o.fga opponent_fga,"
        "o.three_pm opponent_three_pm,o.three_pa opponent_three_pa,o.fta opponent_fta,"
        "o.orb opponent_orb,o.drb opponent_drb,o.tov opponent_tov,o.pf opponent_pf,"
        "m.league,m.periods_home_json,m.periods_away_json,m.source_snapshot_id match_snapshot "
        "FROM team_game_stat g JOIN team_game_stat o ON o.titan_match_id=g.titan_match_id "
        "AND o.titan_team_id=g.opponent_titan_team_id JOIN match_history m USING(titan_match_id) "
        "WHERE g.tip_at<?" + clause + " ORDER BY g.league_id,g.season,g.tip_at,g.titan_match_id,g.is_home DESC",
        params).fetchall()
    if league_ids:
        values = sorted({str(v) for v in league_ids})
        db.execute("DELETE FROM team_game_feature WHERE league_id IN (" + ",".join("?" for _ in values) + ")", values)
    else:
        db.execute("DELETE FROM team_game_feature")
    # Normalize period arrays once; the original JSON remains in match_history.
    match_rows = db.execute(
        "SELECT titan_match_id,league_id,league,periods_home_json,periods_away_json,source_snapshot_id "
        "FROM match_history WHERE status='FINAL' AND tip_at<?" +
        (" AND league_id IN (" + ",".join("?" for _ in sorted({str(v) for v in league_ids})) + ")" if league_ids else ""),
        [cutoff_at] + (sorted({str(v) for v in league_ids}) if league_ids else [])).fetchall()
    for match in match_rows:
        db.execute("INSERT OR REPLACE INTO league VALUES(?,?,?,?,?)",
                   (match["league_id"], match["league"], _regulation_minutes(match["league_id"], match["league"]),
                    None, _stamp()))
        try:
            hp, ap = json.loads(match["periods_home_json"] or "[]"), json.loads(match["periods_away_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            hp, ap = [], []
        if isinstance(hp, list) and isinstance(ap, list):
            for index, (home_points, away_points) in enumerate(zip(hp, ap), 1):
                db.execute("INSERT OR REPLACE INTO period_score VALUES(?,?,?,?,?,?,?)",
                           (match["titan_match_id"], index, home_points, away_points,
                            "REGULATION" if index <= 4 else "OVERTIME", match["source_snapshot_id"], _stamp()))
    by_game = defaultdict(list)
    for row in raw:
        by_game[(row["league_id"], row["season"], row["tip_at"], row["titan_match_id"])].append(row)
    histories = defaultdict(list)
    output = []
    for key in sorted(by_game):
        sides = by_game[key]
        league_id, season, tip_at, _ = key
        team_prior = {}
        all_prior = [item for (lid, _), values in histories.items() if lid == league_id for item in values]
        league_ortg = _mean([x["ortg"] for x in all_prior])
        current_nets = [_mean([x["netrtg"] for x in values[-20:]])
                        for (lid, _), values in histories.items() if lid == league_id]
        low, high = _quantile(current_nets, .25), _quantile(current_nets, .75)
        for row in sides:
            prior = histories[(league_id, row["opponent_titan_team_id"])][-20:]
            team_prior[row["titan_team_id"]] = {
                "opp_netrtg": _mean([x["netrtg"] for x in prior]),
                "opp_ortg": _mean([x["ortg"] for x in prior]),
                "opp_drtg": _mean([x["drtg"] for x in prior]),
            }
        pending = []
        for row in sides:
            reg = _regulation_minutes(league_id, row["league"])
            try:
                periods = json.loads(row["periods_home_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                periods = []
            if not isinstance(periods, list):
                periods = []
            actual = reg + max(0, len(periods) - 4) * 5
            own_poss, opp_poss = row["possessions"], row["opponent_possessions"]
            game_poss = _mean([own_poss, opp_poss])
            # Structural data validation, not a model threshold: a completed
            # team box with zero/near-zero field-goal attempts is a partial
            # source row and cannot yield possessions or ratings.  Preserve
            # the raw fact in team_game_stat but downgrade the derived fields.
            if (row["fga"] is None or row["opponent_fga"] is None or
                    row["fga"] < 20 or row["opponent_fga"] < 20 or
                    game_poss is None or game_poss < 30 or game_poss > 150):
                game_poss = None
            pace = game_poss * reg / actual if game_poss and actual else None
            ortg = _ratio(row["pts"] * 100 if row["pts"] is not None else None, game_poss)
            drtg = _ratio(row["opponent_pts"] * 100 if row["opponent_pts"] is not None else None, game_poss)
            net = ortg - drtg if ortg is not None and drtg is not None else None
            efg = _ratio((row["fgm"] or 0) + .5 * (row["three_pm"] or 0), row["fga"])
            tov_pct = _ratio(row["tov"], game_poss)
            orb_pct = _ratio(row["orb"], (row["orb"] or 0) + (row["opponent_drb"] or 0))
            ftr = _ratio(row["fta"], row["fga"])
            def_efg = _ratio((row["opponent_fgm"] or 0) + .5 * (row["opponent_three_pm"] or 0), row["opponent_fga"])
            def_tov = _ratio(row["opponent_tov"], game_poss)
            def_orb = _ratio(row["opponent_orb"], (row["opponent_orb"] or 0) + (row["drb"] or 0))
            opp_ftr = _ratio(row["opponent_fta"], row["opponent_fga"])
            prior = team_prior[row["titan_team_id"]]
            opp_net = prior["opp_netrtg"]
            bucket = "UNKNOWN"
            if opp_net is not None and low is not None and high is not None:
                bucket = "STRONG" if opp_net >= high else "WEAK" if opp_net <= low else "MEDIUM"
            adj_o = ortg - (prior["opp_drtg"] - league_ortg) if None not in (ortg, prior["opp_drtg"], league_ortg) else ortg
            adj_d = drtg - (prior["opp_ortg"] - league_ortg) if None not in (drtg, prior["opp_ortg"], league_ortg) else drtg
            adj_n = adj_o - adj_d if None not in (adj_o, adj_d) else None
            quarter = _quarter_payload(row, None, bool(row["is_home"]))
            values = {
                "ortg": ortg, "drtg": drtg, "netrtg": net, "regulation_pace": pace,
                "adjusted_ortg": adj_o, "adjusted_drtg": adj_d, "adjusted_netrtg": adj_n,
                "efg_pct": efg, "tov_pct": tov_pct, "orb_pct": orb_pct, "ft_rate": ftr,
            }
            pending.append((row, values))
            output.append((
                row["titan_match_id"], row["titan_team_id"], row["opponent_titan_team_id"],
                league_id, season, row["match_kind"], tip_at, row["is_home"], reg, actual,
                game_poss, pace, ortg, drtg, net, efg, tov_pct, orb_pct, ftr,
                def_efg, def_tov, def_orb, opp_ftr,
                _ratio(row["pf"] * 100 if row["pf"] is not None else None, game_poss),
                _ratio(row["opponent_fta"] * 100 if row["opponent_fta"] is not None else None, game_poss),
                opp_net, bucket, adj_o, adj_d, adj_n,
                json.dumps(quarter, ensure_ascii=False), row["source_snapshot_id"],
                SCHEMA_VERSION, _stamp()))
        # Add the current game only after both sides' pregame opponent states are frozen.
        for row, values in pending:
            histories[(league_id, row["titan_team_id"])].append(values)
    if output:
        db.executemany(
            "INSERT OR REPLACE INTO team_game_feature VALUES(" + ",".join("?" for _ in range(34)) + ")",
            output)
    db.commit()
    return len(output)


def evaluate_source_capabilities(db, evaluated_at=None):
    ensure_feature_schema(db)
    at = _stamp(evaluated_at)
    db.row_factory = sqlite3.Row
    keys = db.execute("SELECT DISTINCT league_id,season FROM team_game_stat ORDER BY league_id,season").fetchall()
    result = []
    for key in keys:
        league_id, season = key["league_id"], key["season"]
        final_games = db.execute(
            "SELECT COUNT(*) FROM match_history WHERE league_id=? AND status='FINAL' "
            "AND titan_match_id IN (SELECT titan_match_id FROM team_game_stat WHERE league_id=? AND season=?)",
            (league_id, league_id, season)).fetchone()[0]
        period_games = db.execute(
            "SELECT COUNT(*) FROM match_history WHERE league_id=? AND status='FINAL' "
            "AND periods_home_json IS NOT NULL AND periods_home_json NOT IN ('null','[]') "
            "AND titan_match_id IN (SELECT titan_match_id FROM team_game_stat WHERE league_id=? AND season=?)",
            (league_id, league_id, season)).fetchone()[0]
        team_games = db.execute(
            "SELECT COUNT(DISTINCT titan_match_id) FROM team_game_feature WHERE league_id=? AND season=? "
            "AND game_possessions IS NOT NULL AND ortg IS NOT NULL AND drtg IS NOT NULL",
            (league_id, season)).fetchone()[0]
        player_games = db.execute(
            "SELECT COUNT(DISTINCT p.titan_match_id) FROM player_game_boxscore p "
            "JOIN team_game_feature f ON f.titan_match_id=p.titan_match_id AND f.titan_team_id=p.titan_team_id "
            "WHERE p.league_id=? AND p.season=? AND f.game_possessions IS NOT NULL",
            (league_id, season)).fetchone()[0]
        period_cov = _ratio(period_games, final_games)
        team_cov = _ratio(team_games, final_games)
        player_cov = _ratio(player_games, team_games)
        if final_games >= 8 and (team_cov or 0) >= .8 and (player_cov or 0) >= .8:
            grade = "A"
        elif final_games >= 8 and (team_cov or 0) >= .8:
            grade = "B"
        elif final_games >= 8 and (period_cov or 0) >= .8:
            grade = "C"
        else:
            grade = "D"
        missing = []
        if grade != "A": missing.append("PLAYER_GAME_BOXSCORE_COVERAGE")
        if grade in ("C", "D"): missing.extend(["TEAM_BOXSCORE_COVERAGE", "POSSESSIONS"])
        if grade == "D": missing.append("PERIOD_SCORE_COVERAGE")
        evidence = {
            "capability_policy": "A=player+team box; B=team box; C=period/team aggregates; D=score only",
            "schedule_history": True, "spread_history": False, "total_history": False,
            "half_score": period_games > 0, "team_info": True, "league_rank": True,
            "team_aggregate_stats": team_games > 0, "player_aggregate_stats": player_games > 0,
            "game_boxscore": team_games > 0, "player_boxscore": player_games > 0,
            "period_scores": period_games > 0,
            "fields": {name: team_games > 0 for name in
                       ("FGA","FGM","3PA","3PM","FTA","FTM","ORB","DRB","AST","STL","BLK","TOV","PF")},
            "player_fields": {"MIN": player_games > 0},
            "market_history_location": "market_history; excluded from independent model",
            "cutoff_safe": True, "market_inputs_used": False}
        db.execute(
            "INSERT OR REPLACE INTO source_capability VALUES(" + ",".join("?" for _ in range(19)) + ")",
            (league_id, season, grade, 1, int((period_cov or 0) > 0), int((team_cov or 0) > 0),
             int((player_cov or 0) > 0), 1, 1, final_games, period_games, team_games, player_games,
             period_cov, team_cov, player_cov, json.dumps(missing, ensure_ascii=False),
             json.dumps(evidence, ensure_ascii=False, sort_keys=True), at))
        result.append({"league_id": league_id, "season": season, "grade": grade,
                       "final_games": final_games, "period_coverage": period_cov,
                       "team_boxscore_coverage": team_cov, "player_boxscore_coverage": player_cov,
                       "missing_fields": missing})
        db.execute("UPDATE league SET source_capability_grade=?,updated_at=? WHERE league_id=?",
                   (grade, at, league_id))
    db.commit()
    return result


def rebuild_player_season_stats(db, cutoff=None):
    ensure_feature_schema(db)
    at = _stamp(cutoff or datetime.now(timezone.utc))
    db.execute("DELETE FROM player_season_stat")
    rows = db.execute(
        "SELECT league_id,season,titan_team_id,titan_player_id,COUNT(*),"
        "SUM(CASE WHEN starter=1 THEN 1 ELSE 0 END),SUM(minutes),SUM(fgm),SUM(fga),"
        "SUM(three_pm),SUM(three_pa),SUM(ftm),SUM(fta),SUM(orb),SUM(drb),SUM(reb),"
        "SUM(ast),SUM(pf),SUM(stl),SUM(tov),SUM(blk),SUM(pts),SUM(plus_minus) "
        "FROM player_game_boxscore WHERE tip_at<? GROUP BY league_id,season,titan_team_id,titan_player_id",
        (at,)).fetchall()
    db.executemany("INSERT INTO player_season_stat VALUES(" + ",".join("?" for _ in range(25)) + ")",
                   [tuple(row) + (at, _stamp()) for row in rows])
    db.commit()
    return len(rows)


def store_market_observations(db_path, event, quotes):
    """Append real market observations to the isolated market domain."""
    db = sqlite3.connect(str(db_path))
    try:
        ensure_feature_schema(db)
        count = 0
        for quote in quotes or []:
            quote_id = str(quote.get("quote_id") or "")
            if not quote_id:
                continue
            payload = {key: quote.get(key) for key in
                       ("quote_id","event_id","source","bookmaker","market_type","period","ot_rule",
                        "line_team1","raw_line","decimal_prices","source_quote_at","received_at","status","raw_path")}
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO market_history VALUES(" + ",".join("?" for _ in range(17)) + ")",
                       (quote_id, event.get("event_id"), quote.get("source"), quote.get("bookmaker"),
                        quote.get("market_type"), quote.get("period"), quote.get("ot_rule"),
                        quote.get("line_team1"), quote.get("raw_line"),
                        json.dumps(quote.get("decimal_prices"), ensure_ascii=False),
                        quote.get("source_quote_at"), quote.get("received_at"), quote.get("status"),
                        quote.get("raw_path"), digest, 0, _stamp()))
            count += 1
        db.commit()
        return count
    finally:
        db.close()


METRICS = ("regulation_pace", "ortg", "drtg", "netrtg", "adjusted_ortg",
           "adjusted_drtg", "adjusted_netrtg", "efg_pct", "tov_pct", "orb_pct",
           "ft_rate", "defensive_efg_pct", "defensive_tov_pct", "defensive_orb_pct",
           "opponent_ft_rate", "pf_per_100", "opponent_fta_per_100")


def _roster_continuity(db, team_id, cutoff):
    end = _iso(cutoff)
    recent_start = (end - timedelta(days=30)).isoformat()
    prior_start = (end - timedelta(days=210)).isoformat()
    recent = db.execute(
        "SELECT titan_player_id,SUM(minutes) minutes FROM player_game_boxscore "
        "WHERE titan_team_id=? AND tip_at>=? AND tip_at<? GROUP BY titan_player_id",
        (team_id, recent_start, end.isoformat())).fetchall()
    prior = db.execute(
        "SELECT titan_player_id,SUM(minutes) minutes FROM player_game_boxscore "
        "WHERE titan_team_id=? AND tip_at>=? AND tip_at<? GROUP BY titan_player_id",
        (team_id, prior_start, recent_start)).fetchall()
    a, b = {r[0]: float(r[1] or 0) for r in recent}, {r[0]: float(r[1] or 0) for r in prior}
    total_a, total_b = sum(a.values()), sum(b.values())
    if total_a <= 0:
        return {"status": "MISSING", "verified": False, "reason": "NO_RECENT_PLAYER_MINUTES"}
    share_a = {k: v / total_a for k, v in a.items()}
    share_b = {k: v / total_b for k, v in b.items()} if total_b else {}
    overlap = sum(share_a.get(k, 0) for k in share_b)
    union = set(share_a) | set(share_b)
    stability = 1 - .5 * sum(abs(share_a.get(k, 0) - share_b.get(k, 0)) for k in union) if share_b else None
    top = sorted(share_a.items(), key=lambda x: x[1], reverse=True)[:10]
    return {"status": "AVAILABLE" if share_b else "CURRENT_ONLY", "verified": bool(share_b),
            "returning_minute_share": overlap if share_b else None,
            "rotation_stability": stability, "recent_player_count": len(a),
            "prior_player_count": len(b), "expected_minutes_source":
            [{"player_id": pid, "recent_30d_minute_share": share} for pid, share in top]}


def build_team_state(db, team_id, league_id, season, match_kind, phase_code, cutoff, recent_limit=20):
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT * FROM team_game_feature WHERE titan_team_id=? AND league_id=? AND match_kind=? "
        "AND tip_at<? AND regulation_pace IS NOT NULL AND adjusted_ortg IS NOT NULL "
        "AND adjusted_drtg IS NOT NULL ORDER BY tip_at DESC LIMIT ?",
        (team_id, str(league_id), match_kind, _stamp(cutoff), int(recent_limit))).fetchall()
    weights = [math.exp(-math.log(2) * max(0, (_iso(cutoff) - _iso(r["tip_at"])).total_seconds()) / 86400 / 60)
               for r in rows]
    total_w = sum(weights)
    ess = total_w * total_w / sum(w*w for w in weights) if weights else 0.0
    metrics = {name: _mean([row[name] for row in rows], weights) for name in METRICS}
    tactical = {}
    for bucket in ("STRONG", "MEDIUM", "WEAK"):
        idx = [i for i, row in enumerate(rows) if row["opponent_strength_bucket"] == bucket]
        tactical[bucket] = {"games": len(idx), **{
            name: _mean([rows[i][name] for i in idx], [weights[i] for i in idx])
            for name in ("regulation_pace", "adjusted_ortg", "adjusted_drtg", "adjusted_netrtg")}}
    sos_values = [row["pregame_opponent_netrtg"] for row in rows]
    sos = {"current": _mean(sos_values, weights),
           "recent_5": _mean(sos_values[:5], weights[:5]),
           "available_games": sum(v is not None for v in sos_values)}
    capability = db.execute(
        "SELECT capability_grade FROM source_capability WHERE league_id=? AND season=?",
        (str(league_id), season)).fetchone()
    roster = _roster_continuity(db, team_id, cutoff)
    source_max = max((row["tip_at"] for row in rows), default=None)
    payload = {"team_id": team_id, "league_id": str(league_id), "season": season,
               "phase_code": phase_code, "cutoff_at": _stamp(cutoff), "games": len(rows),
               "distinct_opponents": len({row["opponent_titan_team_id"] for row in rows}),
               "ess": ess, "metrics": metrics, "tactical_splits": tactical,
               "roster_continuity": roster, "sos": sos, "source_max_tip_at": source_max,
               "market_inputs_used": False}
    feature_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    state_id = hashlib.sha256((team_id + "|" + str(league_id) + "|" + phase_code + "|" + _stamp(cutoff)).encode()).hexdigest()[:32]
    db.execute(
        "INSERT OR REPLACE INTO team_state_feature VALUES(" + ",".join("?" for _ in range(19)) + ")",
        (state_id, team_id, str(league_id), season, phase_code, _stamp(cutoff), len(rows),
         payload["distinct_opponents"], ess, json.dumps(metrics, ensure_ascii=False), "{}",
         json.dumps(tactical, ensure_ascii=False), json.dumps(roster, ensure_ascii=False),
         json.dumps(sos, ensure_ascii=False), capability[0] if capability else "D", source_max,
         0, feature_hash, _stamp()))
    payload.update({"state_id": state_id, "feature_hash": feature_hash,
                    "capability_grade": capability[0] if capability else "D", "style_vector": {}})
    return payload


def build_league_environment(db, league_id, season, match_kind, phase_code, cutoff):
    db.row_factory = sqlite3.Row
    window_start = (_iso(cutoff) - timedelta(days=730)).isoformat()
    rows = db.execute(
        "SELECT f.*,m.periods_home_json,m.periods_away_json FROM team_game_feature f "
        "JOIN match_history m USING(titan_match_id) WHERE f.league_id=? "
        "AND f.match_kind=? AND f.tip_at>=? AND f.tip_at<? AND f.regulation_pace IS NOT NULL "
        "AND f.ortg IS NOT NULL AND f.drtg IS NOT NULL ORDER BY f.tip_at",
        (str(league_id), match_kind, window_start, _stamp(cutoff))).fetchall()
    homes = [row for row in rows if row["is_home"]]
    home_weights = [math.exp(-math.log(2) * max(0, (_iso(cutoff)-_iso(row["tip_at"])).total_seconds()) / 86400 / 180)
                    for row in homes]
    row_weights = [math.exp(-math.log(2) * max(0, (_iso(cutoff)-_iso(row["tip_at"])).total_seconds()) / 86400 / 180)
                   for row in rows]
    margins, totals, ot_points = [], [], []
    for row in homes:
        if None not in (row["ortg"], row["drtg"], row["game_possessions"]):
            margins.append((row["ortg"] - row["drtg"]) * row["game_possessions"] / 100)
            totals.append((row["ortg"] + row["drtg"]) * row["game_possessions"] / 100)
        try:
            hp, ap = json.loads(row["periods_home_json"] or "[]"), json.loads(row["periods_away_json"] or "[]")
            if len(hp) > 4 and len(ap) > 4:
                ot_points.append(sum(hp[4:]) + sum(ap[4:]))
        except (TypeError, json.JSONDecodeError):
            pass
    home_advantage = _mean(margins, home_weights[:len(margins)]) if len(margins) >= 20 else None
    payload = {"league_id": str(league_id), "season": season, "phase_code": phase_code,
               "cutoff_at": _stamp(cutoff), "games": len(homes),
               "season_scope": "CURRENT_AND_PREVIOUS_730D_TIME_DECAY_180D_HALF_LIFE",
               "regulation_minutes": _mean([r["regulation_minutes"] for r in homes], home_weights),
               "pace": _mean([r["regulation_pace"] for r in homes], home_weights),
               "ortg": _mean([r["ortg"] for r in rows], row_weights), "home_advantage": home_advantage,
               "home_advantage_status": "AVAILABLE" if home_advantage is not None else "INSUFFICIENT_VALID_HOME_GAMES",
               "home_advantage_minimum_games": 20,
               "average_total": _mean(totals, home_weights[:len(totals)]), "close_game_count": sum(abs(v) <= 4.5 for v in margins),
               "observed_ot_games": len(ot_points), "observed_ot_points": _mean(ot_points),
               "late_foul_premium": None,
               "late_foul_status": "UNAVAILABLE_NO_PLAY_BY_PLAY_OR_VALIDATED_ESTIMATOR",
               "source_max_tip_at": max((r["tip_at"] for r in rows), default=None),
               "market_inputs_used": False}
    env_id = hashlib.sha256((str(league_id)+"|"+season+"|"+phase_code+"|"+_stamp(cutoff)).encode()).hexdigest()[:32]
    db.execute(
        "INSERT OR REPLACE INTO league_environment VALUES(" + ",".join("?" for _ in range(20)) + ")",
        (env_id, str(league_id), season, phase_code, _stamp(cutoff), payload["games"],
         payload["regulation_minutes"], payload["pace"], payload["ortg"], payload["home_advantage"],
         payload["average_total"], payload["close_game_count"], payload["observed_ot_games"],
         payload["observed_ot_points"], None, payload["late_foul_status"],
         payload["source_max_tip_at"], 0, json.dumps(payload, ensure_ascii=False), _stamp()))
    payload["environment_id"] = env_id
    return payload


def _zscore(value, values):
    clean = [float(v) for v in values if v is not None]
    if value is None or len(clean) < 2:
        return None
    mean = sum(clean) / len(clean)
    sd = math.sqrt(sum((v-mean)**2 for v in clean) / (len(clean)-1))
    return (float(value)-mean)/sd if sd > 0 else 0.0


def _solve_linear_system(matrix, vector):
    """Small pure-Python Gaussian elimination used for auditable OOS fitting."""
    n = len(vector)
    a = [list(map(float, matrix[i])) + [float(vector[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(a[row][col]))
        if abs(a[pivot][col]) < 1e-10:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
        scale = a[col][col]
        a[col] = [value / scale for value in a[col]]
        for row in range(n):
            if row == col:
                continue
            factor = a[row][col]
            if abs(factor) < 1e-12:
                continue
            a[row] = [a[row][j] - factor * a[col][j] for j in range(n + 1)]
    return [a[i][-1] for i in range(n)]


def _fit_efficiency_coefficients(observations):
    """Fit centered PPP coefficients without using any market observation."""
    dimension = 2 + len(EFFICIENCY_BETA_FEATURES)
    gram = [[0.0 for _ in range(dimension)] for _ in range(dimension)]
    rhs = [0.0 for _ in range(dimension)]
    for observation in observations:
        x = [observation["x_offense"], observation["x_defense"]] + [
            observation["features"].get(name, 0.0) for name in EFFICIENCY_BETA_FEATURES]
        y = observation["target_centered"]
        weight = max(0.05, float(observation.get("weight", 1.0)))
        for i in range(dimension):
            rhs[i] += weight * x[i] * y
            for j in range(dimension):
                gram[i][j] += weight * x[i] * x[j]
    # A small numerical ridge keeps sparse international-league samples
    # stable; it is not a shrinkage of the model toward 0.5.
    for i in range(dimension):
        gram[i][i] += 0.01
    coefficients = _solve_linear_system(gram, rhs)
    if coefficients is None:
        return None
    return {"beta_offense": coefficients[0], "beta_defense": coefficients[1],
            "matchup": dict(zip(EFFICIENCY_BETA_FEATURES, coefficients[2:]))}


def _walk_forward_efficiency_betas(db, league_id, match_kind, cutoff, source_rows=None):
    """Learn PPP coefficients using only pre-game states for each observation.

    Every historical game is scored against a state built from games strictly
    before that game's tip.  The resulting observations are then used only for
    the later/current cutoff, so this is a walk-forward/OOS calibration rather
    than a fit on contemporaneous full-season ratings.
    """
    db.row_factory = sqlite3.Row
    if source_rows is None:
        source_rows = db.execute(
            "SELECT f.*,s.pts raw_pts,s.fga raw_fga,s.three_pa raw_three_pa "
            "FROM team_game_feature f JOIN team_game_stat s "
            "ON s.titan_match_id=f.titan_match_id AND s.titan_team_id=f.titan_team_id "
            "WHERE f.match_kind=? AND f.ortg IS NOT NULL AND f.drtg IS NOT NULL "
            "ORDER BY f.tip_at,f.titan_match_id,f.is_home DESC",
            (match_kind,)).fetchall()
    rows = [row for row in source_rows if row["tip_at"] < _stamp(cutoff)]
    grouped = defaultdict(list)
    for row in rows:
        grouped[(str(row["league_id"]), str(row["season"]), row["titan_match_id"])].append(row)
    histories = defaultdict(list)
    league_points = defaultdict(list)
    league_observations = []
    global_observations = []

    def prior_state(team_key, tip_at):
        history = histories.get(team_key, [])[-20:]
        if len(history) < 2:
            return None
        weights = [math.exp(-math.log(2) * max(0, (_iso(tip_at) - _iso(item["tip_at"])).total_seconds()) / 86400 / 60)
                   for item in history]
        return {name: _mean([item[name] for item in history], weights)
                for name in ("adjusted_ortg", "adjusted_drtg", "efg_pct", "tov_pct", "orb_pct", "ft_rate")}, \
               _mean([_ratio(item["raw_three_pa"], item["raw_fga"]) for item in history], weights)

    for (row_league, _season, _match_id), sides in sorted(grouped.items(), key=lambda item: min(r["tip_at"] for r in item[1])):
        if len(sides) != 2:
            continue
        sides = sorted(sides, key=lambda item: int(item["is_home"]), reverse=True)
        tip_at = sides[0]["tip_at"]
        league_mu = _mean(league_points[row_league])
        current_states = [prior_state((row_league, side["titan_team_id"]), tip_at) for side in sides]
        if league_mu is not None and all(state is not None for state in current_states):
            for side_index, side in enumerate(sides):
                own, own_three = current_states[side_index]
                other, other_three = current_states[1 - side_index]
                own_off = own.get("adjusted_ortg") or own.get("ortg")
                other_def = other.get("adjusted_drtg") or other.get("drtg")
                observed = _ratio(side["ortg"], 100.0)
                if None in (own_off, other_def, observed):
                    continue
                sign = 1.0 if side_index == 0 else -1.0
                features = {
                    "delta_efg": sign * ((own.get("efg_pct") or 0.0) - (other.get("efg_pct") or 0.0)),
                    "delta_tov": sign * ((own.get("tov_pct") or 0.0) - (other.get("tov_pct") or 0.0)),
                    "delta_orb": sign * ((own.get("orb_pct") or 0.0) - (other.get("orb_pct") or 0.0)),
                    "delta_ftr": sign * ((own.get("ft_rate") or 0.0) - (other.get("ft_rate") or 0.0)),
                    "delta_3pa": sign * ((own_three or 0.0) - (other_three or 0.0)),
                }
                observation = {
                    "x_offense": float(own_off) / 100.0 - league_mu,
                    "x_defense": float(other_def) / 100.0 - league_mu,
                    "features": features, "target_centered": observed - league_mu,
                    "weight": math.exp(-math.log(2) * max(0, (_iso(_stamp(cutoff)) - _iso(tip_at)).total_seconds()) / 86400 / 180),
                    "tip_at": tip_at,
                }
                global_observations.append(observation)
                if row_league == str(league_id):
                    league_observations.append(observation)
        for side in sides:
            histories[(row_league, side["titan_team_id"])].append(side)
            if side["ortg"] is not None:
                league_points[row_league].append(_ratio(side["ortg"], 100.0))

    if len(league_observations) >= EFFICIENCY_LEAGUE_MIN_OBS:
        source, selected = "LEAGUE_WALK_FORWARD", league_observations
    elif len(global_observations) >= EFFICIENCY_GLOBAL_MIN_OBS:
        source, selected = "GLOBAL_WALK_FORWARD", global_observations
    else:
        source, selected = "BASELINE_PRIOR", []
    fitted = _fit_efficiency_coefficients(selected) if selected else None
    if fitted is None:
        fitted = {"beta_offense": EFFICIENCY_BASELINE_PRIOR[0],
                  "beta_defense": EFFICIENCY_BASELINE_PRIOR[1],
                  "matchup": dict(zip(EFFICIENCY_BETA_FEATURES, EFFICIENCY_BASELINE_PRIOR[2:]))}
    fitted.update({"source": source, "walk_forward_oos": source.endswith("WALK_FORWARD"),
                   "league_observation_count": len(league_observations),
                   "global_observation_count": len(global_observations),
                   "selected_observation_count": len(selected),
                   "cutoff_at": _stamp(cutoff), "market_inputs_used": False,
                   "minimums": {"league": EFFICIENCY_LEAGUE_MIN_OBS, "global": EFFICIENCY_GLOBAL_MIN_OBS}})
    return fitted


def _recent_three_pa_rate(db, team_id, league_id, match_kind, cutoff, recent_limit=20):
    rows = db.execute(
        "SELECT s.three_pa,s.fga FROM team_game_feature f JOIN team_game_stat s "
        "ON s.titan_match_id=f.titan_match_id AND s.titan_team_id=f.titan_team_id "
        "WHERE f.titan_team_id=? AND f.league_id=? AND f.match_kind=? AND f.tip_at<? "
        "ORDER BY f.tip_at DESC LIMIT ?",
        (team_id, str(league_id), match_kind, _stamp(cutoff), int(recent_limit))).fetchall()
    return _mean([_ratio(row[0], row[1]) for row in rows])


def build_matchup(db, event_id, league_id, season, match_kind, phase_code,
                  team1_id, team2_id, cutoff, recent_limit=20,
                  state_cache=None, environment_cache=None,
                  efficiency_beta_cache=None):
    ensure_feature_schema(db)
    cache_key = (str(league_id), season, int(match_kind), phase_code, _stamp(cutoff), int(recent_limit))
    states = state_cache.get(cache_key) if state_cache is not None else None
    if states is None:
        team_ids = [row[0] for row in db.execute(
            "SELECT DISTINCT titan_team_id FROM team_game_feature WHERE league_id=? AND season=? AND match_kind=? AND tip_at<?",
            (str(league_id), season, match_kind, _stamp(cutoff))).fetchall()]
        states = {tid: build_team_state(db, tid, league_id, season, match_kind, phase_code, cutoff, recent_limit)
                  for tid in team_ids}
        if state_cache is not None:
            state_cache[cache_key] = states
    if team1_id not in states or team2_id not in states:
        return None
    style_fields = ("regulation_pace", "adjusted_ortg", "adjusted_drtg", "efg_pct",
                    "tov_pct", "orb_pct", "ft_rate", "pf_per_100")
    for state in states.values():
        state["style_vector"] = {name: _zscore(state["metrics"].get(name),
                                                       [s["metrics"].get(name) for s in states.values()])
                                 for name in style_fields}
        db.execute("UPDATE team_state_feature SET style_vector_json=? WHERE state_id=?",
                   (json.dumps(state["style_vector"], ensure_ascii=False), state["state_id"]))
    a, b = states[team1_id], states[team2_id]
    env_key = (str(league_id), season, int(match_kind), phase_code, _stamp(cutoff))
    env = environment_cache.get(env_key) if environment_cache is not None else None
    if env is None:
        env = build_league_environment(db, league_id, season, match_kind, phase_code, cutoff)
        if environment_cache is not None:
            environment_cache[env_key] = env
    ma, mb = a["metrics"], b["metrics"]
    pace = _mean([ma.get("regulation_pace"), mb.get("regulation_pace")])
    if pace is None:
        return None
    beta_cache = efficiency_beta_cache
    if beta_cache is None and state_cache is not None:
        beta_cache = state_cache.setdefault("__efficiency_beta_cache__", {})
    beta_key = (str(league_id), int(match_kind), _stamp(cutoff))
    betas = beta_cache.get(beta_key) if beta_cache is not None else None
    if betas is None:
        source_rows = None
        if state_cache is not None:
            source_cache = state_cache.setdefault("__efficiency_source_rows__", {})
            source_key = int(match_kind)
            source_rows = source_cache.get(source_key)
            if source_rows is None:
                source_rows = db.execute(
                    "SELECT f.*,s.pts raw_pts,s.fga raw_fga,s.three_pa raw_three_pa "
                    "FROM team_game_feature f JOIN team_game_stat s "
                    "ON s.titan_match_id=f.titan_match_id AND s.titan_team_id=f.titan_team_id "
                    "WHERE f.match_kind=? AND f.ortg IS NOT NULL AND f.drtg IS NOT NULL "
                    "ORDER BY f.tip_at,f.titan_match_id,f.is_home DESC", (match_kind,)).fetchall()
                source_cache[source_key] = source_rows
        betas = _walk_forward_efficiency_betas(db, league_id, match_kind, cutoff, source_rows)
        if beta_cache is not None:
            beta_cache[beta_key] = betas
    three_pa_cache = state_cache.setdefault("__three_pa_rate_cache__", {}) if state_cache is not None else {}
    rate_key = (str(league_id), int(match_kind), _stamp(cutoff), int(recent_limit))
    if rate_key not in three_pa_cache:
        three_pa_cache[rate_key] = {
            tid: _recent_three_pa_rate(db, tid, league_id, match_kind, cutoff, recent_limit)
            for tid in (team1_id, team2_id)
        }
    recent_three = three_pa_cache[rate_key]
    delta_features = {
        "delta_efg": (ma.get("efg_pct") or 0.0) - (mb.get("efg_pct") or 0.0),
        "delta_tov": (ma.get("tov_pct") or 0.0) - (mb.get("tov_pct") or 0.0),
        "delta_orb": (ma.get("orb_pct") or 0.0) - (mb.get("orb_pct") or 0.0),
        "delta_ftr": (ma.get("ft_rate") or 0.0) - (mb.get("ft_rate") or 0.0),
        "delta_3pa": (recent_three.get(team1_id) or 0.0) - (recent_three.get(team2_id) or 0.0),
    }
    mu_ppp = _ratio(env.get("ortg"), 100.0)
    if mu_ppp is None:
        mu_ppp = _mean([_ratio(ma.get("adjusted_ortg"), 100.0), _ratio(mb.get("adjusted_ortg"), 100.0)])
    if mu_ppp is None or None in (ma.get("adjusted_ortg"), ma.get("adjusted_drtg"),
                                  mb.get("adjusted_ortg"), mb.get("adjusted_drtg")):
        return None

    def matchup_adjustment(sign=1.0):
        return sign * sum(float(betas["matchup"].get(name, 0.0)) * delta_features[name]
                          for name in EFFICIENCY_BETA_FEATURES)

    def expected_ppp(offense, defense, sign=1.0):
        return (mu_ppp + float(betas["beta_offense"]) * (float(offense) / 100.0 - mu_ppp) +
                float(betas["beta_defense"]) * (float(defense) / 100.0 - mu_ppp) +
                matchup_adjustment(sign))

    eff1 = expected_ppp(ma["adjusted_ortg"], mb["adjusted_drtg"], 1.0)
    eff2 = expected_ppp(mb["adjusted_ortg"], ma["adjusted_drtg"], -1.0)
    home = float(env.get("home_advantage") or 0)
    score1_b = pace * eff1 + home / 2
    score2_b = pace * eff2 - home / 2
    model_b = {"name": "LEAGUE_AVERAGE_ANCHORED_PPP_WALK_FORWARD", "expected_pace": pace,
               "expected_team1_efficiency": eff1, "expected_team2_efficiency": eff2,
               "league_average_ppp": mu_ppp, "beta_offense": betas["beta_offense"],
               "beta_defense": betas["beta_defense"], "efficiency_beta_source": betas["source"],
               "efficiency_beta_calibration": betas,
               "matchup_features": delta_features,
               "matchup_adjustment_team1": matchup_adjustment(1.0),
               "matchup_adjustment_team2": matchup_adjustment(-1.0),
               "formula": "mu + beta_O*(AdjORtg-mu) + beta_D*(AdjDRtg_opp-mu) + MatchupAdj",
               "expected_team1_score": score1_b, "expected_team2_score": score2_b,
               "expected_margin": score1_b-score2_b, "fair_total": score1_b+score2_b,
               "market_inputs_used": False}
    # Tactical model uses only the team's own pre-cutoff split against the
    # current opponent-strength bucket.  A split needs three games and is
    # transparently shrunk toward the baseline by n/(n+5).
    bucket1 = "STRONG" if (b["style_vector"].get("adjusted_ortg") or 0) >= .5 else \
              "WEAK" if (b["style_vector"].get("adjusted_ortg") or 0) <= -.5 else "MEDIUM"
    bucket2 = "STRONG" if (a["style_vector"].get("adjusted_ortg") or 0) >= .5 else \
              "WEAK" if (a["style_vector"].get("adjusted_ortg") or 0) <= -.5 else "MEDIUM"
    split1, split2 = a["tactical_splits"][bucket1], b["tactical_splits"][bucket2]
    tactical_ready = split1["games"] >= 3 and split2["games"] >= 3
    if tactical_ready:
        w1, w2 = split1["games"]/(split1["games"]+5), split2["games"]/(split2["games"]+5)
        tpace1 = (split1["regulation_pace"] or pace)*w1 + ma["regulation_pace"]*(1-w1)
        tpace2 = (split2["regulation_pace"] or pace)*w2 + mb["regulation_pace"]*(1-w2)
        pace_c = _mean([tpace1, tpace2])
        o1 = (split1["adjusted_ortg"] or ma["adjusted_ortg"])*w1 + ma["adjusted_ortg"]*(1-w1)
        d1 = (split1["adjusted_drtg"] or ma["adjusted_drtg"])*w1 + ma["adjusted_drtg"]*(1-w1)
        o2 = (split2["adjusted_ortg"] or mb["adjusted_ortg"])*w2 + mb["adjusted_ortg"]*(1-w2)
        d2 = (split2["adjusted_drtg"] or mb["adjusted_drtg"])*w2 + mb["adjusted_drtg"]*(1-w2)
        eff1_c = expected_ppp(o1, d2, 1.0)
        eff2_c = expected_ppp(o2, d1, -1.0)
        score1_c = pace_c * eff1_c + home/2
        score2_c = pace_c * eff2_c - home/2
        model_c = {"name": "TACTICAL_MATCHUP", "status": "AVAILABLE", "team1_opponent_bucket": bucket1,
                   "team2_opponent_bucket": bucket2, "expected_pace": pace_c,
                   "expected_team1_efficiency": eff1_c, "expected_team2_efficiency": eff2_c,
                   "efficiency_beta_source": betas["source"], "market_inputs_used": False,
                   "expected_team1_score": score1_c, "expected_team2_score": score2_c,
                   "expected_margin": score1_c-score2_c, "fair_total": score1_c+score2_c,
                   "shrinkage": {"team1": w1, "team2": w2}, "market_inputs_used": False}
        weights = {"model_b": .65, "model_c": .35}
        score1 = score1_b*.65 + score1_c*.35
        score2 = score2_b*.65 + score2_c*.35
    else:
        model_c = {"name": "TACTICAL_MATCHUP", "status": "INSUFFICIENT_TACTICAL_SPLIT",
                   "team1_opponent_bucket": bucket1, "team2_opponent_bucket": bucket2,
                   "minimum_games_per_side": 3, "market_inputs_used": False}
        weights, score1, score2 = {"model_b": 1.0, "model_c": 0.0}, score1_b, score2_b
    ensemble = {"name": "CAPABILITY_WEIGHTED_CHALLENGER", "weights": weights,
                "expected_team1_score": score1, "expected_team2_score": score2,
                "expected_margin": score1-score2, "fair_handicap_team1": -(score1-score2),
                "fair_total": score1+score2, "market_inputs_used": False,
                "capability_grade": max(a["capability_grade"], b["capability_grade"])}
    factors = [
        {"factor": "OPPONENT_ADJUSTED_NET_RATING", "team1": ma.get("adjusted_netrtg"), "team2": mb.get("adjusted_netrtg"),
         "difference": (ma.get("adjusted_netrtg")-mb.get("adjusted_netrtg")) if None not in (ma.get("adjusted_netrtg"),mb.get("adjusted_netrtg")) else None},
        {"factor": "EXPECTED_PACE", "value": pace},
        {"factor": "EFFICIENCY_BETA_SOURCE", "value": betas["source"],
         "league_average_ppp": mu_ppp, "beta_offense": betas["beta_offense"],
         "beta_defense": betas["beta_defense"], "walk_forward_oos": betas["walk_forward_oos"],
         "selected_observation_count": betas["selected_observation_count"]},
        {"factor": "MATCHUP_ADJUSTMENT", "features": delta_features,
         "team1_contribution_ppp": matchup_adjustment(1.0),
         "team2_contribution_ppp": matchup_adjustment(-1.0)},
        {"factor": "HOME_ADVANTAGE", "contribution_points": home},
        {"factor": "EFG", "team1": ma.get("efg_pct"), "team2": mb.get("efg_pct")},
        {"factor": "TURNOVER_RATE", "team1": ma.get("tov_pct"), "team2": mb.get("tov_pct")},
        {"factor": "OFFENSIVE_REBOUND_RATE", "team1": ma.get("orb_pct"), "team2": mb.get("orb_pct")},
        {"factor": "FREE_THROW_RATE", "team1": ma.get("ft_rate"), "team2": mb.get("ft_rate")},
        {"factor": "SCHEDULE_STRENGTH", "team1": a["sos"].get("current"), "team2": b["sos"].get("current")},
        {"factor": "TACTICAL_MATCHUP", "status": model_c["status"],
         "margin_delta": model_c.get("expected_margin", model_b["expected_margin"])-model_b["expected_margin"]},
        {"factor": "ROSTER_CONTINUITY", "team1": a["roster_continuity"].get("rotation_stability"),
         "team2": b["roster_continuity"].get("rotation_stability")},
    ]
    source_tips = [value for value in (a.get("source_max_tip_at"), b.get("source_max_tip_at")) if value]
    payload = {"event_id": event_id, "league_id": str(league_id), "cutoff_at": _stamp(cutoff),
               "team1_titan_id": team1_id, "team2_titan_id": team2_id,
               "team_states": [a, b], "league_environment": env, "model_b": model_b,
               "model_c": model_c, "ensemble": ensemble, "top_factors": factors,
               "source_max_tip_at": max(source_tips) if source_tips else None,
               "market_inputs_used": False, "feature_contract_version": SCHEMA_VERSION}
    feature_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    matchup_id = hashlib.sha256((event_id+"|"+_stamp(cutoff)+"|"+feature_hash).encode()).hexdigest()[:32]
    db.execute("INSERT OR REPLACE INTO matchup_feature VALUES(" + ",".join("?" for _ in range(19)) + ")",
               (matchup_id, event_id, str(league_id), _stamp(cutoff), team1_id, team2_id,
                score1, score2, ensemble["expected_margin"], ensemble["fair_handicap_team1"],
                ensemble["fair_total"], json.dumps(model_b, ensure_ascii=False),
                json.dumps(model_c, ensure_ascii=False), json.dumps(ensemble, ensure_ascii=False),
                json.dumps(factors, ensure_ascii=False), payload["source_max_tip_at"], 0, feature_hash, _stamp()))
    db.commit()
    payload.update({"matchup_id": matchup_id, "feature_hash": feature_hash})
    return payload


def freeze_pregame_snapshot(db_path, event, pricing, cutoff):
    """Append an immutable pregame feature/price snapshot after model freeze."""
    context = dict(pricing.get("titan_foundation_pricing") or {})
    if not context:
        return None
    db = sqlite3.connect(str(db_path))
    try:
        ensure_feature_schema(db)
        ensemble = context.get("ensemble") or {}
        payload = {"event": {k: event.get(k) for k in
                             ("event_id", "league", "team1_id", "team2_id", "team1_name", "team2_name", "tip_at")},
                   "cutoff_at": _stamp(cutoff), "model_version": pricing.get("model_version"),
                   "feature_context": context, "independent_forecast": {
                       "champion_margin": pricing.get("mu_raw"), "champion_total": pricing.get("total_raw"),
                       "challenger_margin": ensemble.get("expected_margin"),
                       "challenger_total": ensemble.get("fair_total")},
                   "market_inputs_used": False, "real_execution_allowed": False}
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload_hash = hashlib.sha256(payload_text.encode()).hexdigest()
        snapshot_id = hashlib.sha256((event["event_id"]+"|"+_stamp(cutoff)+"|"+str(pricing.get("model_version"))).encode()).hexdigest()[:32]
        existing = db.execute("SELECT payload_hash FROM pregame_snapshot WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if existing and existing[0] != payload_hash:
            raise ValueError("IMMUTABLE_PREGAME_SNAPSHOT_CONFLICT")
        db.execute("INSERT OR IGNORE INTO pregame_snapshot VALUES(" + ",".join("?" for _ in range(19)) + ")",
                   (snapshot_id, event["event_id"], _stamp(cutoff), str(pricing.get("model_version")),
                    context.get("league_id"), context.get("team1_titan_id"), context.get("team2_titan_id"),
                    ensemble.get("expected_team1_score"), ensemble.get("expected_team2_score"),
                    ensemble.get("expected_margin"), ensemble.get("fair_handicap_team1"), ensemble.get("fair_total"),
                    context.get("feature_hash") or "", payload_hash, context.get("source_max_tip_at"), 0, 1,
                    payload_text, _stamp()))
        db.commit()
        return snapshot_id
    finally:
        db.close()
