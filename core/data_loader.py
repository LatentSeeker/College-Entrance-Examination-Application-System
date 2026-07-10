"""数据加载与『分数 <-> 位次』换算。

设计要点：
- 录取数据(投档分)为江西省2025年公开真实数据；部分院校缺失的最低位次，
  通过一分一段表锚点做分段线性插值/外推得到，并标记为『估算』。
- 一分一段表只取了若干公开锚点，分数之间用线性插值，曲线之外做线性外推。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import pandas as pd

import config

Subject = Literal["物理", "历史"]


@dataclass
class RankConverter:
    """基于一分一段锚点做 分数<->位次 双向换算。"""

    anchors: dict[str, list[tuple[float, float]]]

    def __post_init__(self) -> None:
        # 锚点按分数降序排列，确保位次随分数下降而单调递增
        self._by_subject: dict[str, list[tuple[float, float]]] = {}
        for subj, pts in self.anchors.items():
            self._by_subject[subj] = sorted(
                ((float(s), float(r)) for s, r in pts), key=lambda x: -x[0]
            )

    def score_to_rank(self, subject: Subject, score: float) -> int:
        """分数 -> 位次（向上取整为整数名次）。"""
        pts = self._by_subject[subject]
        # pts 按分数从高到低；找到 score 所在区间做线性插值
        if score >= pts[0][0]:
            # 高于最高锚点：用最高两点的斜率外推
            (s1, r1), (s2, r2) = pts[0], pts[1]
            rank = self._linterp(score, s1, r1, s2, r2)
            return max(1, round(rank))
        if score <= pts[-1][0]:
            (s1, r1), (s2, r2) = pts[-2], pts[-1]
            rank = self._linterp(score, s1, r1, s2, r2)
            return max(1, round(rank))
        for (s_hi, r_hi), (s_lo, r_lo) in zip(pts, pts[1:]):
            if s_lo <= score <= s_hi:
                rank = self._linterp(score, s_hi, r_hi, s_lo, r_lo)
                return max(1, round(rank))
        return max(1, round(pts[-1][1]))

    def rank_to_score(self, subject: Subject, rank: float) -> int:
        """位次 -> 分数（用于把估算位次反查参考分数等场景）。"""
        pts = self._by_subject[subject]
        if rank <= pts[0][1]:
            (s1, r1), (s2, r2) = pts[0], pts[1]
            score = self._linterp(rank, r1, s1, r2, s2)
            return round(score)
        if rank >= pts[-1][1]:
            (s1, r1), (s2, r2) = pts[-2], pts[-1]
            score = self._linterp(rank, r1, s1, r2, s2)
            return round(score)
        for (s_hi, r_hi), (s_lo, r_lo) in zip(pts, pts[1:]):
            if r_hi <= rank <= r_lo:
                score = self._linterp(rank, r_hi, s_hi, r_lo, s_lo)
                return round(score)
        return round(pts[-1][0])

    @staticmethod
    def _linterp(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
        if x1 == x2:
            return y1
        return y1 + (y2 - y1) * (x - x1) / (x2 - x1)


@lru_cache(maxsize=1)
def load_batch_lines() -> dict:
    with open(config.BATCH_LINES_FILE, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def load_rank_converter() -> RankConverter:
    with open(config.RANK_TABLE_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return RankConverter(anchors=data["anchors"])


def _grp_code(s: object) -> str:
    """从专业组标签里取数字代号：'501组'/'专业组（501）' -> '501'。"""
    m = re.search(r"(\d+)", str(s))
    return m.group(1) if m else ""


def _parse_first_subject(selsci: str) -> str:
    return "历史" if "历史" in (selsci or "") else "物理"


def _parse_reselect(selsci: str) -> str:
    """真实选科串 -> 系统判定值：不限/含化学/含生物/含地理/含政治/含化学和生物。"""
    m = re.search(r"再选(.*)", selsci or "")
    t = (m.group(1) if m else "").strip()
    if not t or "不限" in t:
        return "不限"
    has_chem, has_bio = "化学" in t, "生物" in t
    if has_chem and has_bio:
        return "含化学和生物"
    if has_chem:
        return "含化学"
    if has_bio:
        return "含生物"
    if "地理" in t:
        return "含地理"
    if "政治" in t:
        return "含政治"
    return "不限"


@lru_cache(maxsize=1)
def _load_json_groups() -> tuple[dict, list]:
    """解析真实富 JSON：返回 (按(院校,代号,首选)索引的富信息, 全部专业组记录)。"""
    path = config.ADMISSIONS_JSON_FILE
    if not path.exists():
        return {}, []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    index: dict[tuple, dict] = {}
    records: list[dict] = []
    for sch in data:
        name = str(sch.get("学校名称", "")).strip()
        region = str(sch.get("地区", "")).strip()
        for g in sch.get("专业组", []):
            selsci = g.get("选科要求", "")
            first = _parse_first_subject(selsci)
            code = _grp_code(g.get("专业组名称", ""))
            if not name or not code:
                continue
            majors = g.get("专业列表", []) or []
            info = {
                "再选要求": _parse_reselect(selsci),
                "专业列表": majors,
                "招生类型": str(g.get("招生类型", "")).strip(),
                "地区": region,
            }
            index[(name, code, first)] = info
            records.append({
                "院校名称": name, "code": code, "首选科目": first,
                "专业组名称": str(g.get("专业组名称", "")).strip(),
                "录取批次": str(g.get("录取批次", "本科批")).strip(),
                "最低分": g.get("最低分"), "最低位次": g.get("最低位次"), **info,
            })
    return index, records


@lru_cache(maxsize=1)
def load_admissions() -> pd.DataFrame:
    """加载院校专业组录取数据：以官方 PDF (CSV) 为主，叠加真实 JSON 的
    真·选科要求 / 专业级明细，并补入 JSON 独有的专业组；缺失位次用一分一段表估算补齐。"""
    df = pd.read_csv(config.ADMISSIONS_FILE, encoding="utf-8")
    df["投档最低分"] = pd.to_numeric(df["投档最低分"], errors="coerce")
    df["最低位次"] = pd.to_numeric(df["最低位次"], errors="coerce")

    # ---- 合并真实 JSON ----
    index, records = _load_json_groups()
    keys = list(zip(df["院校名称"], df["专业组"].map(_grp_code), df["首选科目"]))
    df["再选要求"] = [index[k]["再选要求"] if k in index else r
                      for k, r in zip(keys, df["再选要求"])]
    df["专业列表"] = [index[k]["专业列表"] if k in index else [] for k in keys]
    df["招生类型"] = [index[k]["招生类型"] if k in index else "" for k in keys]
    df["选科真实"] = [k in index for k in keys]
    df["地区"] = [index[k]["地区"] if k in index else "" for k in keys]

    # 补入 JSON 独有（PDF 没有）的专业组：提前批/专科等
    csv_keys = set(keys)
    seen, extra = set(csv_keys), []
    for rec in records:
        k = (rec["院校名称"], rec["code"], rec["首选科目"])
        if k in seen or rec["最低分"] is None:
            continue
        seen.add(k)
        extra.append({
            "院校名称": rec["院校名称"], "专业组": rec["专业组名称"],
            "首选科目": rec["首选科目"], "再选要求": rec["再选要求"],
            "投档最低分": rec["最低分"], "最低位次": rec["最低位次"],
            "批次": rec["录取批次"], "城市": "", "院校层次": "", "代表专业": "",
            "专业列表": rec["专业列表"], "招生类型": rec["招生类型"],
            "选科真实": True, "地区": rec["地区"],
        })
    if extra:
        df = pd.concat([df, pd.DataFrame(extra)], ignore_index=True)
        df["投档最低分"] = pd.to_numeric(df["投档最低分"], errors="coerce")
        df["最低位次"] = pd.to_numeric(df["最低位次"], errors="coerce")

    conv = load_rank_converter()

    def fill_rank(row: pd.Series) -> pd.Series:
        if pd.isna(row["最低位次"]):
            est = conv.score_to_rank(row["首选科目"], row["投档最低分"])
            row["最低位次"] = int(est)
            row["位次估算"] = True
        else:
            row["最低位次"] = int(row["最低位次"])
            row["位次估算"] = False
        return row

    df = df.apply(fill_rank, axis=1)
    df["最低位次"] = df["最低位次"].astype(int)

    # 用权威 985/211 名单硬校正院校层次（修掉模型偶发的错判，精确匹配才覆盖）
    from core.school_tiers import tier_for
    df["院校层次"] = [tier_for(n, c) for n, c in zip(df["院校名称"], df["院校层次"].fillna(""))]

    return df.sort_values(["首选科目", "最低位次"]).reset_index(drop=True)


@lru_cache(maxsize=1)
def load_majors() -> pd.DataFrame:
    """把所有专业组的『专业列表』展开成专业级表（用于按专业查询/推荐）。"""
    df = load_admissions()
    rows: list[dict] = []
    for r in df.itertuples(index=False):
        majors = getattr(r, "专业列表", None)
        if not isinstance(majors, list):
            continue
        for m in majors:
            rk = m.get("最低位次")
            rows.append({
                "专业名称": m.get("专业名称", ""),
                "院校名称": r.院校名称, "专业组": r.专业组,
                "首选科目": r.首选科目, "再选要求": r.再选要求,
                "城市": r.城市, "招生类型": getattr(r, "招生类型", ""), "批次": r.批次,
                "专业最低分": m.get("最低分"),
                "专业最低位次": int(rk) if rk not in (None, "", 0) else None,
            })
    return pd.DataFrame(rows)


def list_cities(subject: Subject | None = None) -> list[str]:
    df = load_admissions()
    if subject:
        df = df[df["首选科目"] == subject]
    return sorted(df["城市"].dropna().unique().tolist())


def list_levels() -> list[str]:
    df = load_admissions()
    levels: set[str] = set()
    for cell in df["院校层次"].dropna():
        levels.update(part.strip() for part in str(cell).split("/"))
    return sorted(levels)
