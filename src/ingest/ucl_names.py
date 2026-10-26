"""欧冠（openfootball）队名归一化。

openfootball 用的是官方全名（含国家标签），例如::

    FC Bayern München (GER)
    Real Madrid CF (ESP)
    Manchester City FC (ENG)

本模块把它们统一成本项目已有的短名：

- 五大联赛球队 -> football-data 镜像里的名字（如 ``Bayern Munich``、``Real Madrid``），
  这样 ``src/jingcai/team_names.py`` 里的中文别名可以直接复用；
- 非五大联赛球队 -> 规范英文短名（如 ``Galatasaray``、``Feyenoord``）。
"""
from __future__ import annotations

import re

# 去掉结尾的国家标签，如 " (GER)"
_TAG_RE = re.compile(r"^(?P<name>.*?)\s*\([A-Z]{3}\)\s*$")


def strip_country(name: str) -> str:
    """``FC Bayern München (GER)`` -> ``FC Bayern München``。"""
    m = _TAG_RE.match((name or "").strip())
    return (m.group("name") if m else (name or "")).strip()


# openfootball 全名 -> 项目统一短名
RAW_TO_CANONICAL: dict[str, str] = {
    # ---- 五大联赛（与 football-data 镜像一致）----
    "FC Barcelona": "Barcelona",
    "Real Madrid": "Real Madrid",
    "Real Madrid CF": "Real Madrid",
    "Bayern München": "Bayern Munich",
    "FC Bayern München": "Bayern Munich",
    "Borussia Dortmund": "Dortmund",
    "Manchester City": "Man City",
    "Manchester City FC": "Man City",
    "Chelsea FC": "Chelsea",
    "Paris Saint-Germain": "Paris SG",
    "Paris Saint-Germain FC": "Paris SG",
    "Juventus": "Juventus",
    "Juventus FC": "Juventus",
    "Atlético Madrid": "Ath Madrid",
    "Club Atlético de Madrid": "Ath Madrid",
    "Liverpool FC": "Liverpool",
    "Arsenal FC": "Arsenal",
    "SSC Napoli": "Napoli",
    "Manchester United": "Man United",
    "Manchester United FC": "Man United",
    "AC Milan": "Milan",
    "RB Leipzig": "RB Leipzig",
    "Bayer Leverkusen": "Leverkusen",
    "Bayer 04 Leverkusen": "Leverkusen",
    "Sevilla FC": "Sevilla",
    "Inter": "Inter",
    "FC Internazionale Milano": "Inter",
    "Tottenham Hotspur": "Tottenham",
    "Tottenham Hotspur FC": "Tottenham",
    "Olympique Lyonnais": "Lyon",
    "Lille OSC": "Lille",
    "Valencia CF": "Valencia",
    "AS Monaco": "Monaco",
    "AS Monaco FC": "Monaco",
    "AS Roma": "Roma",
    "Olympique Marseille": "Marseille",
    "Olympique de Marseille": "Marseille",
    "Villarreal CF": "Villarreal",
    "Atalanta": "Atalanta",
    "Atalanta BC": "Atalanta",
    "Bor. Mönchengladbach": "M'gladbach",
    "VfL Wolfsburg": "Wolfsburg",
    "Eintracht Frankfurt": "Ein Frankfurt",
    "Athletic Club": "Ath Bilbao",
    "Aston Villa FC": "Aston Villa",
    "Málaga CF": "Malaga",
    "Leicester City": "Leicester",
    "Stade Brestois 29": "Brest",
    "Real Sociedad de Fútbol": "Sociedad",
    "Real Sociedad": "Sociedad",
    "Lazio Roma": "Lazio",
    "SS Lazio": "Lazio",
    "VfB Stuttgart": "Stuttgart",
    "Bologna FC 1909": "Bologna",
    "Girona FC": "Girona",
    "Montpellier HSC": "Montpellier",
    "1899 Hoffenheim": "Hoffenheim",
    "Stade Rennais": "Rennes",
    "1. FC Union Berlin": "Union Berlin",
    "Racing Club de Lens": "Lens",
    "FC Schalke 04": "Schalke 04",
    "Newcastle United FC": "Newcastle",
    "Real Betis": "Betis",
    "Celta Vigo": "Celta",
    "Real Valladolid": "Valladolid",
    "Deportivo La Coruna": "La Coruna",
    "Deportivo La Coruña": "La Coruna",
    "Saint-Etienne": "St Etienne",
    "AS Saint-Etienne": "St Etienne",
    "1. FC Köln": "FC Koln",

    # ---- 其他欧洲俱乐部（规范短名）----
    "FC Porto": "Porto",
    "SL Benfica": "Benfica",
    "Sport Lisboa e Benfica": "Benfica",
    "Shakhtar Donetsk": "Shakhtar Donetsk",
    "FK Shakhtar Donetsk": "Shakhtar Donetsk",
    "AFC Ajax": "Ajax",
    "Club Brugge KV": "Club Brugge",
    "Zenit St. Petersburg": "Zenit",
    "Olympiakos Piraeus": "Olympiakos",
    "PAE Olympiakos SFP": "Olympiakos",
    "Celtic FC": "Celtic",
    "CSKA Moskva": "CSKA Moscow",
    "Galatasaray": "Galatasaray",
    "Galatasaray SK": "Galatasaray",
    "FC Basel 1893": "Basel",
    "Dinamo Zagreb": "Dinamo Zagreb",
    "GNK Dinamo Zagreb": "Dinamo Zagreb",
    "FC København": "FC Copenhagen",
    "Dinamo Kiev": "Dynamo Kyiv",
    "Sporting CP": "Sporting Lisbon",
    "Sporting Clube de Portugal": "Sporting Lisbon",
    "PSV": "PSV Eindhoven",
    "PSV Eindhoven": "PSV Eindhoven",
    "BSC Young Boys": "Young Boys",
    "RB Salzburg": "Salzburg",
    "FC Red Bull Salzburg": "Salzburg",
    "Viktoria Plzeň": "Viktoria Plzen",
    "BATE Borisov": "BATE Borisov",
    "RSC Anderlecht": "Anderlecht",
    "APOEL Nikosia": "APOEL",
    "Beşiktaş": "Besiktas",
    "Malmö FF": "Malmo",
    "Lokomotiv Moskva": "Lokomotiv Moscow",
    "Feyenoord Rotterdam": "Feyenoord",
    "Feyenoord": "Feyenoord",
    "FK Crvena Zvezda": "Red Star Belgrade",
    "Crvena Zvezda": "Red Star Belgrade",
    "KRC Genk": "Genk",
    "Spartak Moskva": "Spartak Moscow",
    "PFC Ludogorets Razgrad": "Ludogorets",
    "NK Maribor": "Maribor",
    "FK Bodø/Glimt": "Bodo/Glimt",
    "Qarabağ Ağdam FK": "Qarabag",
    "Qarabağ FK": "Qarabag",
    "KAA Gent": "Gent",
    "AC Sparta Praha": "Sparta Prague",
    "ŠK Slovan Bratislava": "Slovan Bratislava",
    "SK Sturm Graz": "Sturm Graz",
    "Royale Union Saint-Gilloise": "Union SG",
    "SK Slavia Praha": "Slavia Prague",
    "Slavia Praha": "Slavia Prague",
    "Paphos FC": "Paphos",
    "FK Kairat": "Kairat",
    "Trabzonspor": "Trabzonspor",
    "Oţelul Galaţi": "Otelul Galati",
    "FC Nordsjælland": "Nordsjaelland",
    "Sporting Braga": "Braga",
    "Sporting Clube de Braga": "Braga",
    "CFR Cluj": "CFR Cluj",
    "FC Steaua Bucureşti": "Steaua Bucharest",
    "Austria Wien": "Austria Vienna",
    "FK Astana": "Astana",
    "Maccabi Tel Aviv": "Maccabi Tel Aviv",
    "FK Rostov": "Rostov",
    "Legia Warszawa": "Legia Warsaw",
    "AEK Athen": "AEK Athens",
    "FC Midtjylland": "Midtjylland",
    "FK Krasnodar": "Krasnodar",
    "Ferencvárosi TC": "Ferencvaros",
    "İstanbul Başakşehir": "Istanbul Basaksehir",
    "FC Sheriff": "Sheriff Tiraspol",
    "Rangers FC": "Rangers",
    "Maccabi Haifa": "Maccabi Haifa",
    "Royal Antwerp FC": "Royal Antwerp",

    # ---- 欧罗巴 / 欧协联（openfootball el/conf 的原始写法）----
    # 与五大联赛/欧冠同一队但写法不同 -> 合并（防身份分裂）
    "West Ham United": "West Ham",
    "SC Freiburg": "Freiburg",
    "FC Nantes": "Nantes",
    "Brighton & Hove Albion": "Brighton",
    "RC Lens": "Lens",
    "OGC Nice": "Nice",
    "Toulouse FC": "Toulouse",
    "ACF Fiorentina": "Fiorentina",
    "1. FC Heidenheim 1846": "Heidenheim",
    "FC Twente": "Twente",
    "Union Saint-Gilloise": "Union SG",
    # 变音符号 -> ASCII 规范名（中文别名按 ASCII 对齐）
    "Fenerbahçe": "Fenerbahce",
    "Lech Poznań": "Lech Poznan",
    "Vitória Guimarães": "Vitoria Guimaraes",
    "BK Häcken": "Hacken",
    "Breiðablik": "Breidablik",
    "Brøndby IF": "Brondby",
    "Djurgårdens IF": "Djurgarden",
    "FK Mladá Boleslav": "Mlada Boleslav",
    "FK Čukarički": "Cukaricki",
    "FK Žalgiris": "Zalgiris",
    "Jagiellonia Białystok": "Jagiellonia Bialystok",
    "KÍ Klaksvík": "KI Klaksvik",
    "NŠ Mura": "NS Mura",
    "Raków Częstochowa": "Rakow Czestochowa",
    "TSC Bačka Topola": "TSC Backa Topola",
    "Víkingur Reykjavík": "Vikingur Reykjavik",
    "1. FC Slovácko": "Slovacko",
    # 规范短名
    "PAOK Saloniki": "PAOK",
    "Heart of Midlothian": "Hearts",
    "Aberdeen FC": "Aberdeen",
    "Hapoel Be'er Sheva": "Hapoel Beer Sheva",
    "Omonia Nikosia": "Omonia Nicosia",
    "Anorthosis Famagusta": "Anorthosis",
    "FC St. Gallen": "St Gallen",
    "Servette FC": "Servette",
    "The New Saints": "The New Saints",
    "FC Zürich": "FC Zurich",
}


def normalize_team(name: str) -> str:
    """把 openfootball 队名转成项目统一短名；未收录时返回去掉国家标签的原名。"""
    raw = strip_country(name)
    return RAW_TO_CANONICAL.get(raw, raw)
