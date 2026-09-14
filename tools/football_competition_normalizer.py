"""Single competition classification contract for the football pipeline."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class CompetitionInfo:
    competition_raw: str
    competition_canonical: str
    competition_scope: str
    country: str
    region: str
    micro_region: str
    tier: str
    competition_type: str
    senior_eligible: bool
    official_competition: bool
    youth_or_reserve: bool
    friendly: bool
    classification_confidence: str
    classification_reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(competition: str) -> CompetitionInfo:
    raw = str(competition or "").strip()
    text = raw.lower()
    asian_games = any(k in raw for k in ("亚运会", "亚运男足", "亚运女足", "Asian Games"))
    youth = bool(re.search(r"(青年|u\s*[0-9]+|女足青年|预备队|reserve|youth)", raw, re.I)) and not asian_games
    friendly = any(k in text for k in ("友谊", "friendly"))
    if any(k in raw for k in ("欧冠", "欧洲冠军联赛", "UEFA Champions League")):
        return _info(raw, "欧冠", "欧冠独立赛事", "洲际", "欧洲", "欧冠独立赛事", "洲际杯赛", "洲际杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "欧冠别名优先匹配")
    if any(k in raw for k in ("欧联", "欧罗巴", "欧洲联赛", "UEFA Europa League")):
        return _info(raw, "欧联", "欧联独立赛事", "洲际", "欧洲", "欧联独立赛事", "洲际杯赛", "洲际杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "欧联别名优先匹配")
    if any(k in raw for k in ("欧协联", "Conference League")):
        return _info(raw, "欧协联", "欧协联独立赛事", "洲际", "欧洲", "欧协联独立赛事", "洲际杯赛", "洲际杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "欧协联独立赛事")
    if any(k in raw for k in ("亚冠精英", "亚洲冠军联赛精英", "AFC Champions League Elite")):
        return _info(raw, "亚冠精英", "亚冠精英独立赛事", "亚洲", "亚洲", "亚冠精英独立赛事", "洲际杯赛", "洲际杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "亚冠精英独立赛事别名优先匹配")
    if any(k in raw for k in ("亚冠2", "亚冠二级", "亚洲冠军联赛2", "AFC Champions League Two")):
        return _info(raw, "亚冠2", "亚冠2独立赛事", "亚洲", "亚洲", "亚冠2独立赛事", "洲际杯赛", "洲际杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "亚冠2独立赛事别名优先匹配")
    if any(k in raw for k in ("亚冠", "亚洲冠军联赛", "AFC Champions League")):
        return _info(raw, "亚冠", "亚冠独立赛事", "亚洲", "亚洲", "亚冠独立赛事", "洲际杯赛", "洲际杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "亚冠独立赛事别名匹配")
    if any(k in raw for k in ("亚运会", "亚运男足", "亚运女足", "Asian Games")):
        return _info(raw, "亚运会足球", "亚运会足球独立赛事", "亚洲", "亚洲", "亚运会足球独立赛事", "国际正式赛", "国际综合运动会足球", not youth and not friendly, not youth and not friendly, youth, friendly, "高", "亚运会足球独立赛事别名匹配")
    if any(k in raw for k in ("世界杯", "欧洲杯", "美洲杯", "亚洲杯", "世预赛", "欧预赛", "南美解放者杯", "南球杯")):
        return _info(raw, raw, "洲际正式赛", "洲际", "其他", "洲际杯赛", "洲际", "国家队正式赛", not youth and not friendly, not youth and not friendly, youth, friendly, "中", "国际正式赛事")
    if any(k in raw for k in ("杯", "盃", "足总", "国王杯", "联赛杯", "天皇杯", "韩国杯", "巴西杯", "德国杯", "意大利杯", "法国杯", "西班牙国王杯")):
        country, region = _country_region(raw)
        return _info(raw, raw, "国内杯赛", country, region, _micro(region), "杯赛", "杯赛", not youth and not friendly, not youth and not friendly, youth, friendly, "中", "杯赛关键词")
    country, region = _country_region(raw)
    tier = _tier(raw)
    scope = "国内联赛" if tier != "未知" else "unknown"
    official = not youth and not friendly and tier != "未知"
    return _info(raw, raw, scope, country, region, _micro(region), tier, "联赛" if tier != "未知" else "未知分类", official, official, youth, friendly, "中" if tier != "未知" else "低", "国家/地区关键词与级别关键词")


def _info(raw, canonical, scope, country, region, micro, tier, ctype, senior, official, youth, friendly, confidence, reason):
    return CompetitionInfo(raw, canonical, scope, country, region, micro, tier, ctype, senior, official, youth, friendly, confidence, reason)


def _tier(text: str) -> str:
    if any(k in text for k in ("英超", "西甲", "意甲", "德甲", "法甲", "中超", "日职", "韩职", "美职", "巴甲", "阿甲")):
        return "T1"
    if any(k in text for k in ("英冠", "英甲", "西乙", "意乙", "意丙", "德乙", "法乙", "日乙", "韩K2", "美冠", "巴乙", "阿乙")):
        return "T2"
    if any(k in text for k in ("英乙", "西协", "德丙", "法丙", "日丙", "巴丙")):
        return "T3"
    if any(k in text for k in ("超", "甲", "乙", "丙", "联赛", "league")):
        return "T?"
    return "未知"


def _country_region(text: str) -> tuple[str, str]:
    groups = {
        "英国": ("英", "欧洲五大"), "西班牙": ("西", "欧洲五大"), "意大利": ("意", "欧洲五大"), "德国": ("德", "欧洲五大"), "法国": ("法", "欧洲五大"),
        "中国": ("中", "东亚"), "日本": ("日", "东亚"), "韩国": ("韩", "东亚"), "美国": ("美", "北美"), "加拿大": ("加", "北美"),
        "巴西": ("巴西", "南美"), "阿根廷": ("阿根廷", "南美"), "智利": ("智利", "南美"), "厄瓜多尔": ("厄瓜多尔", "南美"), "哥伦比亚": ("哥伦比亚", "南美"),
        "墨西哥": ("墨西哥", "北美"), "沙特": ("沙特", "西亚/中亚"), "卡塔尔": ("卡塔尔", "西亚/中亚"), "阿联酋": ("阿联酋", "西亚/中亚"), "科威特": ("科威特", "西亚/中亚"), "哈萨克斯坦": ("哈萨克斯坦", "西亚/中亚"),
        "荷兰": ("荷兰", "欧洲非五大"), "葡萄牙": ("葡萄牙", "欧洲非五大"), "比利时": ("比利时", "欧洲非五大"), "丹麦": ("丹麦", "欧洲非五大"), "瑞典": ("瑞典", "欧洲非五大"), "挪威": ("挪威", "欧洲非五大"), "捷克": ("捷克", "欧洲非五大"), "俄罗斯": ("俄罗斯", "欧洲非五大"),
    }
    aliases = {"英": ("英国", "欧洲五大"), "西": ("西班牙", "欧洲五大"), "意": ("意大利", "欧洲五大"), "德": ("德国", "欧洲五大"), "法": ("法国", "欧洲五大"), "日": ("日本", "东亚"), "韩": ("韩国", "东亚"), "美": ("美国", "北美")}
    for key, value in {**groups, **aliases}.items():
        if key in text:
            return value
    return "未识别", "其他"


def _micro(region: str) -> str:
    return {"欧洲五大": "欧洲五大系列", "欧洲非五大": "欧洲非五大系列", "北美": "北美系列", "南美": "南美系列", "东亚": "日韩系列", "西亚/中亚": "西亚/中亚系列"}.get(region, "其他系列")


def normalize_dict(competition: str) -> dict:
    return normalize(competition).to_dict()
