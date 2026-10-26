"""队名匹配：把竞彩中文队名对齐到各数据源的英文名。

匹配策略（按优先级）
--------------------
1. 精确英文缩写匹配：竞彩接口直接给 `homeTeamAbbEnName`（如 SYD），
   与 understat 的 short_title、football-data 的缩写比对
2. 中文别名表：手工维护的常见译名映射
3. 模糊匹配：字符重叠度 + 编辑距离，仅在候选唯一时采信
4. 兜底：返回 None，由调用方决定跳过或标记为低置信度

置信度分级
----------
    exact   英文缩写或全名精确命中
    alias   中文别名表命中
    fuzzy   模糊匹配（需人工复核）
    none    未匹配
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

# 竞彩中文队名 -> 英文名（常用译名，覆盖竞彩主流联赛）
# 键为小写中文名，值为数据源中使用的英文名
CN_TO_EN: dict[str, str] = {
    # 英超
    "阿森纳": "Arsenal", "切尔西": "Chelsea", "利物浦": "Liverpool",
    "曼联": "Man United", "曼城": "Man City", "热刺": "Tottenham",
    "纽卡斯尔": "Newcastle", "阿斯顿维拉": "Aston Villa", "西汉姆": "West Ham",
    "布莱顿": "Brighton", "狼队": "Wolves", "伍尔弗": "Wolves",
    "狼": "Wolves", "富勒姆": "Fulham",
    "水晶宫": "Crystal Palace", "伯恩茅斯": "Bournemouth", "布伦特福德": "Brentford",
    "布伦特": "Brentford",
    "埃弗顿": "Everton", "诺丁汉森林": "Nott'm Forest", "伯恩利": "Burnley",
    "利兹联": "Leeds", "桑德兰": "Sunderland", "西布朗": "West Brom",
    "南安普顿": "Southampton", "莱斯特城": "Leicester", "伊普斯维奇": "Ipswich",
    "赫尔城": "Hull", "考文垂": "Coventry", "斯托克城": "Stoke",
    "诺维奇": "Norwich", "斯旺西": "Swansea", "加的夫城": "Cardiff",
    "沃特福德": "Watford", "米德尔斯堡": "Middlesbrough",
    "谢菲联": "Sheffield United", "谢周三": "Sheffield Weds",
    "普雷斯顿": "Preston", "布莱克本": "Blackburn", "巡游者": "QPR",
    "赫尔": "Hull", "朴茨茅斯": "Portsmouth", "雷丁": "Reading",
    # 德甲
    "拜仁": "Bayern Munich", "多特蒙德": "Dortmund", "勒沃库森": "Leverkusen",
    "莱比锡": "RB Leipzig", "法兰克福": "Ein Frankfurt", "斯图加特": "Stuttgart",
    "弗赖堡": "Freiburg", "霍芬海姆": "Hoffenheim", "沃尔夫斯堡": "Wolfsburg",
    "门兴": "M'Gladbach", "柏林联合": "Union Berlin", "云达不莱梅": "Werder Bremen",
    "奥格斯堡": "Augsburg", "海登海姆": "Heidenheim", "波鸿": "Bochum",
    "科隆": "FC Koln", "汉堡": "Hamburg", "柏林赫塔": "Hertha",
    "杜塞尔多夫": "Fortuna Dusseldorf", "圣保利": "St. Pauli",
    "纽伦堡": "Nurnberg", "科特布斯": "Cottbus", "菲尔特": "Greuther Furth",
    "慕尼黑1860": "Munich 1860", "曼海姆": "Mannheim", "亚琛": "Aachen",
    # 西甲
    "皇马": "Real Madrid", "巴塞罗那": "Barcelona", "巴萨": "Barcelona",
    "马竞": "Ath Madrid", "塞维利亚": "Sevilla", "皇家社会": "Sociedad",
    "毕尔巴鄂": "Ath Bilbao", "瓦伦西亚": "Valencia", "巴伦西亚": "Valencia",
    "比利亚雷亚尔": "Villarreal", "比利亚雷": "Villarreal", "贝蒂斯": "Betis",
    "赫罗纳": "Girona", "奥萨苏纳": "Osasuna", "赫塔菲": "Getafe",
    "塞尔塔": "Celta", "马略卡": "Mallorca", "阿拉维斯": "Alaves",
    "加的斯": "Cadiz", "埃尔切": "Elche", "格拉纳达": "Granada",
    "莱万特": "Levante", "巴拉多利德": "Valladolid", "拉科鲁尼亚": "La Coruna",
    "拉科": "La Coruna", "埃瓦尔": "Eibar", "拉斯帕尔马斯": "Las Palmas",
    "桑坦德": "Santander",
    # 意甲
    "尤文图斯": "Juventus", "国际米兰": "Inter", "AC米兰": "Milan",
    "那不勒斯": "Napoli", "罗马": "Roma", "拉齐奥": "Lazio",
    "亚特兰大": "Atalanta", "博洛尼亚": "Bologna", "佛罗伦萨": "Fiorentina",
    "都灵": "Torino", "乌迪内斯": "Udinese", "萨索洛": "Sassuolo",
    "热那亚": "Genoa", "维罗纳": "Verona", "莱切": "Lecce",
    "卡利亚里": "Cagliari", "帕尔马": "Parma", "威尼斯": "Venezia",
    "科莫": "Como", "弗罗西诺内": "Frosinone", "弗洛西诺": "Frosinone",
    "恩波利": "Empoli",
    "蒙扎": "Monza", "克雷莫纳": "Cremonese", "萨勒尼塔纳": "Salernitana",
    # 法甲
    "巴黎圣日耳曼": "Paris SG", "马赛": "Marseille",
    "里昂": "Lyon", "里尔": "Lille", "摩纳哥": "Monaco",
    "尼斯": "Nice", "雷恩": "Rennes", "朗斯": "Lens",
    "南特": "Nantes", "斯特拉斯堡": "Strasbourg", "斯特拉斯": "Strasbourg",
    "图卢兹": "Toulouse",
    "布雷斯特": "Brest", "蒙彼利埃": "Montpellier", "兰斯": "Reims",
    "勒芒": "Le Mans", "昂热": "Angers", "圣埃蒂安": "St Etienne",
    "梅斯": "Metz", "特鲁瓦": "Troyes", "洛里昂": "Lorient",
    "克莱蒙": "Clermont", "勒阿弗尔": "Le Havre",
    "巴黎FC": "Paris FC",
    # 其他
    "阿贾克斯": "Ajax", "费耶诺德": "Feyenoord", "埃因霍温": "PSV Eindhoven",
    "特温特": "Twente", "乌德勒支": "Utrecht", "海伦芬": "Heerenveen",
    "SBV精英": "Excelsior", "阿尔克马尔": "AZ Alkmaar", "阿尔克马": "AZ Alkmaar",
    "格罗宁根": "Groningen",
    "维迪斯": "Vitesse", "海牙": "ADO Den Haag", "威廉二世": "Willem II",
    "登博思": "Den Bosch", "奥斯": "TOP Oss",
    "本菲卡": "Benfica", "波尔图": "Porto", "里斯本竞技": "Sporting Lisbon",
    "布拉加": "Braga", "吉马良斯": "Vitoria Guimaraes", "法马利康": "Famalicao",
    "拜仁慕尼黑": "Bayern Munich",
    # 竞彩常用简称
    "维拉": "Aston Villa", "莱红牛": "RB Leipzig", "蓝月亮": "Man City",
    "红魔": "Man United", "枪手": "Arsenal", "红军": "Liverpool",
    # 欧冠常见非五大联赛球队（也用于欧战）
    "加拉塔萨": "Galatasaray", "加拉塔萨雷": "Galatasaray",
    "费内巴切": "Fenerbahce", "贝西克塔斯": "Besiktas", "特拉布宗": "Trabzonspor",
    "布鲁日": "Club Brugge", "安德莱赫特": "Anderlecht", "亨克": "Genk",
    "安特卫普": "Royal Antwerp", "圣吉罗斯": "Union SG", "圣吉尔联": "Union SG",
    "凯尔特人": "Celtic", "流浪者": "Rangers",
    "哥本哈根": "FC Copenhagen", "北西兰": "Nordsjaelland", "中日德兰": "Midtjylland",
    "贝尔格莱德红星": "Red Star Belgrade", "红星": "Red Star Belgrade",
    "萨尔茨堡": "Salzburg", "萨尔茨堡红牛": "Salzburg",
    "格拉茨风暴": "Sturm Graz", "奥地利维也纳": "Austria Vienna", "维也纳": "Austria Vienna",
    "顿涅茨克矿工": "Shakhtar Donetsk", "矿工": "Shakhtar Donetsk",
    "基辅迪纳摩": "Dynamo Kyiv", "泽尼特": "Zenit",
    "莫斯科中央陆军": "CSKA Moscow", "中央陆军": "CSKA Moscow",
    "莫斯科斯巴达": "Spartak Moscow", "罗斯托夫": "Rostov", "克拉斯诺达尔": "Krasnodar",
    "奥林匹亚科斯": "Olympiakos", "雅典AEK": "AEK Athens", "AEK雅典": "AEK Athens",
    "萨格勒布迪纳摩": "Dinamo Zagreb", "马里博尔": "Maribor",
    "年轻人": "Young Boys", "巴塞尔": "Basel", "马尔默": "Malmo",
    "博多格林特": "Bodo/Glimt", "博德闪耀": "Bodo/Glimt",
    "卡拉巴赫": "Qarabag", "卢多戈雷茨": "Ludogorets",
    "布拉格斯巴达": "Sparta Prague", "布拉格斯拉维亚": "Slavia Prague",
    "布拉迪斯拉发": "Slovan Bratislava", "帕福斯": "Paphos", "凯拉特": "Kairat",
    "克卢日": "CFR Cluj", "布加勒斯特星": "Steaua Bucharest",
    "阿斯塔纳": "Astana", "特拉维夫马卡比": "Maccabi Tel Aviv",
    "海法马卡比": "Maccabi Haifa", "华沙莱吉亚": "Legia Warsaw", "莱吉亚": "Legia Warsaw",
    "费伦茨瓦罗斯": "Ferencvaros", "巴萨克赛尔": "Istanbul Basaksehir",
    "谢里夫": "Sheriff Tiraspol",
    "里斯本": "Sporting Lisbon", "葡萄牙体育": "Sporting Lisbon",
    "埃因霍温": "PSV Eindhoven", "PSV": "PSV Eindhoven",
    "LASK林茨": "LASK", "LASK": "LASK",
    "维京": "Viking",
    # 欧罗巴/欧协联（竞彩常用简称）
    "格风暴": "Sturm Graz", "萨迪纳摩": "Dinamo Zagreb",
    "波兹南": "Lech Poznan", "奈梅亨": "NEC Nijmegen",
    "克里特": "OFI Crete", "利勒斯特": "Lillestrom",
    "贝西克塔": "Besiktas",
    "苏黎世": "FC Zurich",
    # 挪超（API-Football 名）
    "特罗姆瑟": "Tromso", "罗森博格": "Rosenborg", "莫尔德": "Molde",
    "瓦勒伦加": "Valerenga", "利勒斯特罗姆": "Lillestrom", "布兰": "Brann",
    "海于格松": "Haugesund", "斯托姆加斯特": "Stromsgodset",
    "萨普斯堡": "Sarpsborg 08 FF", "斯塔贝克": "Stabaek",
    "奥德": "ODD Ballklubb", "克里斯蒂安松": "Kristiansund BK",
    "桑德菲杰": "Sandefjord", "哈姆卡姆": "Ham-Kam",
    "奥斯陆KFUM": "KFUM Oslo", "腓特烈斯塔": "Fredrikstad",
    "奥勒松": "Aalesund", "康斯文格": "Kongsvinger", "莫斯": "Moss",
    "耶尔夫": "jerv",
    # 瑞超（API-Football 名）
    "哥德堡": "IFK Goteborg", "盖斯": "Gais", "马尔默": "Malmo FF",
    "索尔纳AIK": "AIK Stockholm", "AIK": "AIK Stockholm",
    "尤尔加登": "Djurgardens IF", "佐加顿斯": "Djurgardens IF",
    "哈马比": "Hammarby FF", "赫根": "BK Hacken", "埃尔夫斯堡": "IF Elfsborg",
    "北雪平": "IFK Norrkoping", "卡尔马": "Kalmar FF", "赫尔辛堡": "Helsingborg",
    "天狼星": "Sirius", "米亚尔比": "Mjallby AIF", "德格福斯": "Degerfors IF",
    "哈尔姆斯塔德": "Halmstad", "布鲁马波卡纳": "IF Brommapojkarna",
    "厄斯特什": "Osters IF", "瓦尔贝里": "Varbergs BoIS FC",
    "韦斯特罗斯": "Vasteras SK FK", "瓦尔纳莫": "IFK Varnamo",
    "松兹瓦尔": "GIF Sundsvall", "兰斯科罗纳": "Landskrona BoIS",
    "乌特斯格滕": "Utsikten",
    # 芬超（API-Football 名）
    "赫尔辛基": "HJK Helsinki", "库奥皮奥": "KuPS", "伊尔维斯": "Ilves",
    "图尔库国际": "Inter Turku", "国际图尔库": "Inter Turku",
    "塞伊奈约基": "SJK", "洪卡": "Honka", "哈卡": "Haka", "拉赫蒂": "Lahti",
    "瓦萨": "VPS", "玛丽港": "Mariehamn", "奥卢": "AC Oulu", "雅罗": "FF Jaro",
    "格尼斯坦": "Gnistan", "HIFK赫尔辛基": "HIFK Helsinki",
    "科特佩": "Kooteepee", "EIF": "EIF",
    # 巴甲（API-Football 名）
    "弗拉门戈": "Flamengo", "米竞技": "Atletico-MG", "米内罗竞技": "Atletico-MG",
    "帕尔梅拉斯": "Palmeiras", "科林蒂安": "Corinthians", "圣保罗": "Sao Paulo",
    "桑托斯": "Santos", "格雷米奥": "Gremio", "巴西国际": "Internacional",
    "博塔弗戈": "Botafogo", "弗鲁米嫩塞": "Fluminense",
    "瓦斯科达伽马": "Vasco DA Gama", "瓦斯科": "Vasco DA Gama",
    "克鲁塞罗": "Cruzeiro", "巴伊亚": "Bahia", "福塔莱萨": "Fortaleza EC",
    "塞阿拉": "Ceara", "巴拉纳竞技": "Atletico Paranaense",
    "戈亚尼恩斯竞技": "Atletico Goianiense", "戈亚斯": "Goias",
    "库亚巴": "Cuiaba", "米内罗美洲": "America Mineiro",
    "科里蒂巴": "Coritiba", "尤文图德": "Juventude", "阿瓦伊": "Avai",
    "克里丘马": "Criciuma", "布拉干蒂诺": "RB Bragantino", "维多利亚": "Vitoria",
}


def _norm(s: str) -> str:
    """标准化：去空格、去点号、小写、全角转半角。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("'", "").replace("'", "").replace("-", " ")
    s = re.sub(r"[.\s]+", "", s)
    return s.lower().strip()


def _similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # SequenceMatcher + 包含关系加成
    base = SequenceMatcher(None, a, b).ratio()
    if a in b or b in a:
        base = max(base, 0.85)
    return base


@dataclass
class TeamMatch:
    """匹配结果。"""
    jc_name: str            # 竞彩中文名
    jc_en: str              # 竞彩给的英文缩写
    matched_name: str | None
    confidence: str         # exact / alias / fuzzy / none
    score: float

    @property
    def ok(self) -> bool:
        return self.matched_name is not None


class TeamMatcher:
    """队名匹配器。"""

    def __init__(self, known_names: list[str] | None = None,
                 fuzzy_threshold: float = 0.72,
                 cache_path: str | Path | None = None):
        self.known = list(dict.fromkeys(known_names or []))
        self.fuzzy_threshold = fuzzy_threshold
        # 预建索引
        self._by_norm = {_norm(n): n for n in self.known}
        # 匹配缓存：key=(cn_name, norm(en_abbr)) -> 规范名。只缓存高置信结果。
        self._cache: dict[str, str] = {}
        self._cache_path = Path(cache_path) if cache_path else None
        if self._cache_path and self._cache_path.exists():
            try:
                self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self._cache = {}

    def add_names(self, names: list[str]) -> None:
        for n in names:
            if n and n not in self.known:
                self.known.append(n)
                self._by_norm[_norm(n)] = n

    def _cache_key(self, cn_name: str, en_abbr: str) -> str:
        return f"{cn_name}\x00{_norm(en_abbr)}"

    def save_cache(self) -> None:
        """把已累积的高置信匹配写回缓存文件（供下次复用）。"""
        if not self._cache_path:
            return
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass

    def match(self, cn_name: str, en_abbr: str = "") -> TeamMatch:
        """匹配单个队名。

        顺序：缓存 -> 英文全名精确 -> 中文别名 -> 英文缩写前缀 -> 模糊。
        中文别名优先于缩写前缀，避免 ``VIK`` 把「维京」错配成
        ``Viktoria Plzen`` 这类前缀误命中。

        exact / alias 命中会写入缓存（fuzzy 不入缓存，避免固化错配）。
        """
        key = self._cache_key(cn_name, en_abbr)
        if key in self._cache:
            return TeamMatch(cn_name, en_abbr, self._cache[key], "cache", 1.0)

        result = self._match_uncached(cn_name, en_abbr)
        if result.ok and result.confidence in ("exact", "alias"):
            self._cache[key] = result.matched_name
        return result

    def _match_uncached(self, cn_name: str, en_abbr: str = "") -> TeamMatch:
        # 1) 英文全名精确命中
        if en_abbr:
            for n in self.known:
                if _norm(n) == _norm(en_abbr):
                    return TeamMatch(cn_name, en_abbr, n, "exact", 1.0)

        # 2) 中文别名表
        if cn_name in CN_TO_EN:
            target = CN_TO_EN[cn_name]
            # 第一遍：精确命中（避免 "Villareal" 这类拼写变体在相似度命中里
            # 抢在 "Villarreal" 之前被选走）
            for n in self.known:
                if _norm(n) == _norm(target):
                    return TeamMatch(cn_name, en_abbr, n, "alias", 0.98)
            # 第二遍：退而求其次的相似命中
            for n in self.known:
                if _similarity(n, target) > 0.92:
                    return TeamMatch(cn_name, en_abbr, n, "alias", 0.9)
            # 别名表有但数据源没有，仍返回（可能是新队）
            return TeamMatch(cn_name, en_abbr, target, "alias", 0.8)

        # 3) 英文缩写前缀（仅在唯一候选时采信）
        if en_abbr:
            cands = [n for n in self.known if _norm(n).startswith(_norm(en_abbr))]
            if len(cands) == 1:
                return TeamMatch(cn_name, en_abbr, cands[0], "exact", 0.95)

        # 4) 模糊匹配
        best, best_score = None, 0.0
        for n in self.known:
            sc = _similarity(n, cn_name)
            if sc > best_score:
                best, best_score = n, sc
        if best_score >= self.fuzzy_threshold:
            return TeamMatch(cn_name, en_abbr, best, "fuzzy", best_score)

        return TeamMatch(cn_name, en_abbr, None, "none", best_score)

    def suggest(self, cn_name: str, en_abbr: str = "", top: int = 3,
                min_score: float = 0.30) -> list[tuple[str, float]]:
        """返回与给定队名最相似的前 top 个候选（用于人工补别名）。

        仅返回相似度 >= min_score 的候选；中文名与英文名几乎无字符重叠，
        通常返回空列表（此时应直接补 CN_TO_EN 别名）。
        """
        scores = [(n, _similarity(n, cn_name)) for n in self.known]
        scores = [(n, s) for n, s in scores if s >= min_score]
        scores.sort(key=lambda x: -x[1])
        return scores[:top]

    def match_frame(self, df: pd.DataFrame,
                    cn_col: str = "home_cn", en_col: str = "home_en",
                    out_col: str = "home_matched") -> pd.DataFrame:
        """批量匹配 DataFrame 中的队名列。"""
        res = [self.match(row[cn_col], row.get(en_col, ""))
               if en_col in df.columns else self.match(row[cn_col], "")
               for _, row in df.iterrows()]
        df = df.copy()
        df[out_col] = [r.matched_name for r in res]
        df[out_col + "_conf"] = [r.confidence for r in res]
        df[out_col + "_score"] = [r.score for r in res]
        return df


def build_known_names_from_data(df: pd.DataFrame,
                                col: str = "home_team") -> list[str]:
    """从历史数据提取全部队名作为候选集。"""
    names = set(df[col].dropna().unique())
    if "away_team" in df.columns:
        names |= set(df["away_team"].dropna().unique())
    return sorted(names)


def default_cache_path() -> Path:
    """队名匹配缓存文件默认路径（data/cache/team_alias.json）。"""
    from src.config import get_settings
    return get_settings().cache_dir / "team_alias.json"


def coverage_report(matches: list, matcher: TeamMatcher) -> dict[str, Any]:
    """统计竞彩场次的队名匹配覆盖率。"""
    from collections import Counter
    stats: Counter = Counter()
    unmatched: list[str] = []
    for m in matches:
        for cn, en in ((m.home_cn, m.home_en), (m.away_cn, m.away_en)):
            r = matcher.match(cn, en)
            stats[r.confidence] += 1
            if not r.ok:
                unmatched.append(f"{cn}({en})")
    total = sum(stats.values())
    return {
        "total_teams": total,
        "exact": stats["exact"], "alias": stats["alias"],
        "fuzzy": stats["fuzzy"], "none": stats["none"],
        "matched": total - stats["none"],
        "coverage": (total - stats["none"]) / total if total else 0.0,
        "unmatched": unmatched,
    }
