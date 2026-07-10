"""冲稳保志愿推荐引擎（新高考 3+1+2，位次法）。

核心思路（位次法）：
- 把考生分数换算成全省位次 R；每个院校专业组有往年最低录取位次 S。
- 位次优势 advantage = (S - R) / R：
    advantage > 0  -> 考生排名优于院校录取线 -> 偏『保』
    advantage = 0  -> 与录取线持平         -> 偏『稳』
    advantage < 0  -> 考生排名弱于录取线     -> 偏『冲』
- 录取概率为启发式估算：p = clip(0.5 + slope * advantage, 0.01, 0.99)，仅供参考。
"""
from __future__ import annotations

import math
from typing import Iterable, Literal

import pandas as pd

import config
from core import data_loader

Subject = Literal["物理", "历史"]
Tier = Literal["冲", "稳", "保"]

# 再选科目要求 -> 判定函数
def _meets_requirement(req: str, reselected: set[str]) -> bool:
    req = (req or "").strip()
    if req in ("", "不限"):
        return True
    if req == "含化学":
        return "化学" in reselected
    if req == "含化学和生物":
        return {"化学", "生物"}.issubset(reselected)
    # 兜底：形如 “含化学/含地理” 解析为需要其中之一
    if req.startswith("含"):
        needed = [s for s in ("化学", "生物", "政治", "地理") if s in req]
        return any(s in reselected for s in needed)
    return True


def _classify(advantage: float) -> str:
    """返回档位标签；超出冲稳保区间的院校归入『参考』，不丢弃。"""
    if advantage < config.RUSH_RANGE[0]:
        return "冲刺(偏难)"
    if config.RUSH_RANGE[0] <= advantage < config.RUSH_RANGE[1]:
        return "冲"
    if config.STABLE_RANGE[0] <= advantage < config.STABLE_RANGE[1]:
        return "稳"
    if config.SAFE_RANGE[0] <= advantage <= config.SAFE_RANGE[1]:
        return "保"
    return "保底(富余)"


def _probability(advantage: float) -> float:
    """录取概率（启发式）：logistic / S 型曲线。

    旧版是直线 0.5 + slope*advantage，advantage 稍微偏负就被夹到 1%、偏正就到 99%，
    深冲档全挤在 1% 没有区分度。改用 logistic 后：中心 advantage=0 仍是 0.5，
    两端平滑收敛，不会被夹平。为保持手感，让中心斜率恰好等于 config.PROB_SLOPE
    （logistic 中心斜率 = k/4，故取 k = 4*PROB_SLOPE）。
    """
    k = 4.0 * config.PROB_SLOPE
    p = 1.0 / (1.0 + math.exp(-k * advantage))
    return round(min(0.99, max(0.01, p)), 2)


def recommend(
    subject: Subject,
    user_rank: int,
    reselected: Iterable[str],
    user_score: int | None = None,
    cities: Iterable[str] | None = None,
    levels: Iterable[str] | None = None,
) -> pd.DataFrame:
    """返回带『档位/录取概率』标注的推荐表（已按冲->稳->保、概率升序排列）。"""
    reselected = set(reselected or [])
    cities = set(cities) if cities else None
    levels = set(levels) if levels else None

    df = data_loader.load_admissions()
    df = df[df["首选科目"] == subject].copy()

    # 选科要求过滤
    df = df[df["再选要求"].apply(lambda r: _meets_requirement(r, reselected))]

    # 城市 / 层次过滤
    if cities:
        df = df[df["城市"].isin(cities)]
    if levels:
        df = df[df["院校层次"].apply(
            lambda c: bool(levels & {p.strip() for p in str(c).split("/")})
        )]

    if df.empty:
        return df.assign(位次优势=[], 录取概率=[], 分差=[], 档位=[])

    df["位次优势"] = (df["最低位次"] - user_rank) / user_rank
    df["录取概率"] = df["位次优势"].apply(_probability)
    if user_score is not None:
        df["分差"] = user_score - df["投档最低分"]
    else:
        df["分差"] = pd.NA
    df["档位"] = df["位次优势"].apply(_classify)

    tier_order = {"冲刺(偏难)": 0, "冲": 1, "稳": 2, "保": 3, "保底(富余)": 4}
    df["_t"] = df["档位"].map(tier_order)
    df = df.sort_values(["_t", "录取概率"], ascending=[True, True]).drop(columns="_t")
    return df.reset_index(drop=True)


def major_breakdown(majors: list, user_rank: int | None) -> pd.DataFrame:
    """把一个专业组的『专业列表』展开成带分档/概率的表（按最低位次升序）。

    用真实专业级分数线回答『以我的位次，这个组里能上哪些专业』：
    投档组最低分对应组内最冷门专业，热门专业的专业线高得多。
    """
    rows = []
    for m in majors or []:
        rk = m.get("最低位次")
        rk = int(rk) if rk not in (None, "", 0) else None
        row = {
            "专业名称": m.get("专业名称", ""),
            "最低分": m.get("最低分"),
            "最低位次": rk,
        }
        if user_rank and rk:
            adv = (rk - user_rank) / user_rank
            row["档位"] = _classify(adv)
            row["录取概率"] = _probability(adv)
        rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty and "最低位次" in df:
        df = df.sort_values("最低位次", na_position="last").reset_index(drop=True)
    return df


def adjust_risk(majors: list, user_rank: int | None, obey: bool = True) -> dict | None:
    """估算『专业调剂风险』：进组后能不能录到组内已知专业。

    返回 {level, reachable, total, msg}；无专业明细或无位次时返回 None。
    位次越小越好：考生位次 <= 专业最低位次 即够得上该专业。
    """
    valid = [m for m in (majors or []) if m.get("最低位次")]
    if not valid or not user_rank:
        return None
    total = len(valid)
    reachable = sum(1 for m in valid if int(m["最低位次"]) >= user_rank)
    ratio = reachable / total
    level = "高" if reachable == 0 else ("低" if ratio >= 0.6 else "中")
    if obey:
        if reachable == 0:
            msg = "你的位次只够进组，已知专业都够不上 → 服从调剂大概率被分到组内更冷门专业。"
        elif level == "低":
            msg = f"组内 {total} 个已知专业你能上 {reachable} 个，调剂风险低。"
        else:
            msg = f"组内 {total} 个已知专业你只够上 {reachable} 个，可能被调剂到其余专业。"
    else:
        if reachable == 0:
            msg = "⚠️ 不服从调剂且够不上任何已知专业 → 退档风险很高（退档后本批次无法再投）。"
        else:
            msg = f"不服从调剂：只在能上的 {reachable}/{total} 个专业里有效，其余可能退档，需谨慎。"
    return {"level": level, "reachable": reachable, "total": total, "msg": msg}


def split_by_tier(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """按档位拆分推荐结果，方便分区展示。"""
    return {tier: df[df["档位"] == tier].reset_index(drop=True) for tier in ("冲", "稳", "保")}


def build_wish_list(df: pd.DataFrame, n_chong: int, n_wen: int, n_bao: int) -> pd.DataFrame:
    """从推荐结果按冲稳保配额拼一张有序志愿表（每档取该档内把握最大的若干，
    再整体按最低位次降序排——好学校/高门槛在前，保底在后，形成梯度）。"""
    tiers = split_by_tier(df)
    counts = {"冲": n_chong, "稳": n_wen, "保": n_bao}
    parts = [tiers[t].sort_values("录取概率", ascending=False).head(counts[t])
             for t in ("冲", "稳", "保")]
    wish = pd.concat(parts) if parts else df.head(0)
    if wish.empty:
        return wish
    wish = wish.sort_values("最低位次").reset_index(drop=True)
    wish.insert(0, "序号", range(1, len(wish) + 1))
    return wish


def summarize_for_llm(
    subject: Subject,
    user_rank: int,
    user_score: int,
    reselected: Iterable[str],
    df: pd.DataFrame,
    max_each: int = 6,
    obey: bool = True,
) -> str:
    """把推荐结果压缩成给大模型的文本上下文。"""
    lines = [
        f"考生情况：{config.PROVINCE} {config.YEAR}年新高考；首选科目={subject}；"
        f"再选科目={'+'.join(reselected) or '未填'}；高考分数={user_score}；全省位次≈{user_rank}；"
        f"{'服从' if obey else '不服从'}专业调剂。",
        "系统按冲稳保给出的候选院校专业组（投档分/最低位次为2025年真实数据，概率为启发式估算）：",
    ]
    tiers = split_by_tier(df)
    for tier in ("冲", "稳", "保"):
        sub = tiers[tier].head(max_each)
        if sub.empty:
            lines.append(f"【{tier}】（无）")
            continue
        items = []
        for _, r in sub.iterrows():
            est = "(位次估算)" if r.get("位次估算") else ""
            majors_raw = r.get("代表专业")
            majors = "" if pd.isna(majors_raw) else str(majors_raw).strip()
            major_part = f" 院校代表专业(参考):{majors}" if majors else ""
            risk = adjust_risk(r.get("专业列表"), user_rank, obey)
            risk_part = f" 调剂风险:{risk['level']}" if risk else ""
            items.append(
                f"{r['院校名称']}{r['专业组']}[{r['城市']}/{r['院校层次']}] "
                f"投档{int(r['投档最低分'])}分/位次{int(r['最低位次'])}{est} "
                f"录取概率≈{int(r['录取概率']*100)}%{major_part}{risk_part}"
            )
        lines.append(f"【{tier}】" + "；".join(items))
    return "\n".join(lines)
