from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _profile(path: Path, team: str) -> dict:
    text = _read(path)
    rank = re.search(r"(\d+)(?:st|nd|rd|th) World Rank", text)
    wl = re.search(r">\s*(\d+)\s*<!-- -->/<!-- -->(\d+)\s*</div>", text)
    stage = re.search(r"Current stage</h2>.*?<div[^>]*>\s*([^<]+?)\s*</div>", text, re.S)
    names = re.findall(r'class="_1lpztt0d[^>]*>\s*([^<]+?)\s*</div>', text)
    names = [n.strip() for n in names if n.strip()]
    leaders = []
    for i in range(0, min(len(names), 12), 2):
        leaders.append({"player_name": " ".join(names[i:i + 2]), "role": "leader", "source": "FIBA_OFFICIAL_TEAM_PROFILE"})
    return {
        "team": team,
        "world_rank": int(rank.group(1)) if rank else None,
        "tournament_win_loss": f"{wl.group(1)}/{wl.group(2)}" if wl else None,
        "current_stage": stage.group(1).strip() if stage else None,
        "roster_section_present": 'data-testid="tab-trigger-roster"' in text,
        "leaders": leaders[:3],
        "source": "FIBA_OFFICIAL_TEAM_PROFILE",
        "price_blind": True,
        "source_path": str(path),
    }


def _games(path: Path, cutoff: str, codes: set[str]) -> dict[str, list[dict]]:
    text = _read(path)
    # FIBA embeds the official game feed inside escaped Next/RSC JSON.
    pattern = re.compile(
        r'\\"gameId\\":(\d+).*?\\"teamA\\":\{.*?\\"code\\":\\"([A-Z]+)\\".*?'
        r'\\"officialName\\":\\"([^\\"]+)\\".*?\\"teamB\\":\{.*?'
        r'\\"code\\":\\"([A-Z]+)\\".*?\\"officialName\\":\\"([^\\"]+)\\".*?'
        r'\\"teamAScore\\":(\d+),\\"teamBScore\\":(\d+).*?'
        r'\\"gameDateTimeUTC\\":\\"([^\\"]+)\\"', re.S)
    out = {c: [] for c in codes}
    for m in pattern.finditer(text):
        game_id, a_code, a, b_code, b, a_score, b_score, tip = m.groups()
        if a_code not in codes and b_code not in codes:
            continue
        # Equal-to-cutoff and zero-zero semifinal cards are not completed prior form.
        if tip >= cutoff or (int(a_score) == 0 and int(b_score) == 0):
            continue
        row = {"game_id": game_id, "team_a": a, "team_b": b, "team_a_code": a_code,
               "team_b_code": b_code, "team_a_score": int(a_score), "team_b_score": int(b_score),
               "tip_time_utc": tip, "source": "FIBA_OFFICIAL_EVENT_LANDING"}
        for code in codes:
            if code in (a_code, b_code):
                out[code].append(row)
    return out


def ingest(raw_dir: str | Path, cutoff: str) -> dict:
    raw = Path(raw_dir)
    cutoff_dt = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    spain = _profile(raw / "spain.html", "Spain")
    usa = _profile(raw / "usa.html", "USA")
    roster_text = _read(raw / "roster.html")
    roster_ready = ("/teams/spain#roster" in roster_text and "/teams/usa#roster" in roster_text
                    and "Rosters confirmed ahead of tip-off" in roster_text)
    games = _games(raw / "event_landing.html", cutoff, {"ESP", "USA"})
    recent = {"Spain": games["ESP"][-3:], "USA": games["USA"][-3:]}
    def before_cutoff(value: str) -> bool:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed < cutoff_dt

    return {
        "profiles": {"Spain": spain, "USA": usa},
        "national_prior": {"Spain": spain["world_rank"], "USA": usa["world_rank"]},
        "roster_ready": roster_ready,
        "roster_source": "FIBA_OFFICIAL_CONFIRMED_ROSTER" if roster_ready else None,
        "player_mapping_ready": len(spain["leaders"]) >= 3 and len(usa["leaders"]) >= 3,
        "role_minutes_ready": "DEGRADED_BUT_USABLE",
        "recent_form": recent,
        "recent_form_ready": len(recent["Spain"]) >= 2 and len(recent["USA"]) >= 2,
        "schedule_rest_ready": True,
        "injury_status": "UNKNOWN",
        "cutoff": cutoff,
        "pregame_evidence_only": all(before_cutoff(g["tip_time_utc"])
                                      for rows in recent.values() for g in rows),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(ingest(sys.argv[1], sys.argv[2]), ensure_ascii=False, indent=2))
