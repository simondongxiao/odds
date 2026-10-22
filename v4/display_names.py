"""Canonical Chinese display names for football source labels.

The provider feed may leave the Chinese columns blank and put an English
label in the nested market object.  This module is display-only: it does not
change odds, model inputs, frozen decisions, scores, or settlement fields.
The original provider labels are retained in ``*_en`` fields when a record is
normalised.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


TEAM_ALIASES: dict[str, str] = {
    # Japan
    "fc tokyo": "FC东京",
    "kashiwa reysol": "柏太阳神",
    "kyoto": "京都不死鸟",
    "kyoto sanga": "京都不死鸟",
    "kashima antlers": "鹿岛鹿角",
    "okayama": "冈山绿雉",
    "fagiano okayama": "冈山绿雉",
    "mito": "水户蜀葵",
    "mito hollyhock": "水户蜀葵",
    "shimizu s-pulse": "清水鼓动",
    "machida": "町田泽维亚",
    "machida zelvia": "町田泽维亚",
    "yokohama f. marinos": "横滨水手",
    "yokohama marinos": "横滨水手",
    "verdy": "东京绿茵",
    "tokyo verdy": "东京绿茵",
    "montedio yamagata": "山形山神",
    "yamagata": "山形山神",
    "hokkaido consadole sapporo": "札幌冈萨多",
    "consadole sapporo": "札幌冈萨多",
    "v-varen nagasaki": "长崎成功丸",
    "sanfrecce hiroshima": "广岛三箭",
    "urawa reds": "浦和红钻",
    "urawa red diamonds": "浦和红钻",
    "chiba": "千叶市原",
    "jef united chiba": "千叶市原",
    "kofu": "甲府风林",
    "ventforet kofu": "甲府风林",
    "yokohama fc": "横滨FC",
    "iwata": "磐田喜悦",
    "jubilo iwata": "磐田喜悦",
    "oita trinita": "大分三神",
    "omiya ardija": "大宫松鼠",
    "toyama": "富山胜利",
    "kataller toyama": "富山胜利",
    "tegevajaro miyazaki": "宫崎棒牛鸟",
    "blaublitz": "秋田蓝色闪电",
    "blaublitz akita": "秋田蓝色闪电",
    "tokushima": "德岛漩涡",
    "tokushima vortis": "德岛漩涡",
    "vanraure": "八户云罗里",
    "vanraure hachinohe": "八户云罗里",
    "nagano": "长野帕塞罗",
    "nagano parceiro": "长野帕塞罗",
    "ryukyu": "琉球FC",
    "tochigi sc": "枥木SC",
    "reilac shiga": "滋贺湖王",
    "kamatamare": "赞岐釜玉海",
    "kamatamare sanuki": "赞岐釜玉海",
    "kanazawa": "金泽萨维根",
    "zweigen kanazawa": "金泽萨维根",
    "kumamoto": "熊本深红",
    "roasso kumamoto": "熊本深红",
    "gainare tottori": "鸟取飞翔",
    "kusatsu": "群马草津温泉",
    "thespakusatsu gunma": "群马草津温泉",
    "lion city": "狮城水手",
    "lion city sailors": "狮城水手",
    "tampines": "淡滨尼流浪",
    "tampines rovers": "淡滨尼流浪",
    # Existing common aliases
    "kawasaki frontale": "川崎前锋",
    "nagoya grampus": "名古屋鲸八",
    "avispa fukuoka": "福冈黄蜂",
    "cerezo osaka": "大阪樱花",
    "gamba osaka": "大阪钢巴",
    "vissel kobe": "神户胜利船",
    "albirex niigata": "新潟天鹅",
    "sagan tosu": "鸟栖砂岩",
    "shonan bellmare": "湘南海洋",
    "sabah baku": "萨巴赫",
    "slavia prague": "布拉格斯拉维亚",
    "reading": "雷丁",
    "chelsea u21": "切尔西U21",
    "gillingham": "吉林汉姆",
    "brighton u21": "布莱顿U21",
    "cheltenham": "切尔滕汉姆",
    "tottenham u21": "热刺U21",
    "oldham": "奥尔德姆",
    "leeds u21": "利兹联U21",
    "millwall": "米尔沃尔",
    "swansea": "斯旺西",
    "cardiff": "卡迪夫城",
    "watford": "沃特福德",
    "wrexham": "雷克瑟姆",
    "west brom": "西布朗",
    "wolves": "狼队",
    "arsenal": "阿森纳",
    "lille": "里尔",
    "inter": "国际米兰",
    "club brugge": "布鲁日",
}

LEAGUE_ALIASES: dict[str, str] = {
    "be:j1-league": "日职联",
    "be:j2-league": "日职乙",
    "be:j3-league": "日职丙",
    "be:j-league-cup": "日联杯",
    "be:premier-league": "英超",
    "be:championship": "英冠",
    "be:champions-league": "欧冠",
    "be:europa-league": "欧联",
    "be:world-cup-women": "女足世界杯",
    "be:efl-trophy": "英锦赛",
    "be:usa-mls": "美职业",
    "be:major-league-soccer": "美职业",
    "usa:mls": "美职业",
    "major league soccer": "美职业",
    "j1-league": "日职联",
    "j2-league": "日职乙",
    "j3-league": "日职丙",
    "be:liga-mx": "墨西联",
    "be:laliga": "西甲",
    "be:caf-champions-league": "非洲冠军联赛",
    "be:reserve-league": "阿根廷预备联赛",
    "be:copa-do-brasil-u20": "巴西U20杯",
    "be:prva-liga-rs": "波黑甲",
    "be:afc-challenge-league": "亚足联挑战联赛",
    "be:cyprus-cup": "塞浦路斯杯",
    "be:copa-chile": "智利杯",
    "be:irish-league-cup": "北爱联杯",
    "be:women-s-league-cup": "英女联杯",
    "be:uefa-youth-league": "欧青联",
    "be:liga-nacional": "危地马拉联",
    "be:veikkausliiga": "芬超",
}


def _load_project_aliases() -> None:
    candidates = (
        Path(r"D:\codex\football_repo_main\data\github_football\team_aliases.json"),
        Path(r"D:\codex\github_publish\odds\data\github_football\team_aliases.json"),
        Path(r"D:\codex\football_publish_20261021_073900\data\github_football\team_aliases.json"),
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for key, value in (payload.get("teams") or {}).items():
            TEAM_ALIASES.setdefault(str(key).strip().casefold(), str(value).strip())
        for key, value in (payload.get("leagues") or {}).items():
            LEAGUE_ALIASES.setdefault(str(key).strip().casefold(), str(value).strip())
        break


_load_project_aliases()


def _clean(value: Any) -> str:
    return re.sub(r"<[^>]*>", "", str(value or "")).strip()


def localize_team(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    return TEAM_ALIASES.get(text.casefold(), text)


def localize_league(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    return LEAGUE_ALIASES.get(text.casefold(), text)


def localize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Normalise every user-facing identity field, including nested market."""
    market = record.get("market") if isinstance(record.get("market"), dict) else {}
    home_raw = market.get("home_team") or record.get("home_team") or ""
    away_raw = market.get("away_team") or record.get("away_team") or ""
    home = localize_team(home_raw)
    away = localize_team(away_raw)
    if home_raw and home_raw != home:
        record.setdefault("home_team_en", _clean(home_raw))
    if away_raw and away_raw != away:
        record.setdefault("away_team_en", _clean(away_raw))
    record["home_team"] = home
    record["away_team"] = away
    record["match"] = f"{home} vs {away}" if home and away else _clean(record.get("match"))
    record["competition"] = localize_league(record.get("competition") or market.get("competition"))
    record["selected_team"] = localize_team(record.get("selected_team"))
    record["candidate_team"] = localize_team(record.get("candidate_team"))
    for key in ("giving_team", "receiving_team"):
        if record.get(key):
            record[key] = localize_team(record[key])
    for key in ("home_team", "away_team", "giving_team", "receiving_team", "selected_team", "candidate_team"):
        if market.get(key):
            market[key] = localize_team(market[key])
    market["competition"] = localize_league(market.get("competition") or record.get("competition"))
    record["market"] = market
    return record
