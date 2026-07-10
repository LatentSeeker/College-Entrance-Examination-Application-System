"""高考志愿填报系统 —— Streamlit 网页应用（江西 2025 · 新高考3+1+2）。

运行：
    conda activate pytorch_nightly
    streamlit run app.py
"""
from __future__ import annotations

from io import BytesIO

import altair as alt
import pandas as pd
import streamlit as st

import config
from core import data_loader, recommender as rec

st.set_page_config(page_title="高考志愿填报系统", page_icon="🎓", layout="wide")

RESELECT_OPTIONS = ["化学", "生物", "政治", "地理"]
TIER_COLOR = {"冲": "#e8743b", "稳": "#19a979", "保": "#1f77b4"}
TIER_DESC = {
    "冲": "录取线高于你的位次，需要发挥+运气，建议放在志愿表前段",
    "稳": "录取线与你的位次接近，匹配度高，作为志愿表主力",
    "保": "你的位次明显优于录取线，保底相对稳妥，放在志愿表后段",
}


# ---------------- 缓存数据 ----------------
@st.cache_data(show_spinner=False)
def get_batch_lines() -> dict:
    return data_loader.load_batch_lines()


@st.cache_data(show_spinner=False)
def get_cities(subject: str) -> list[str]:
    return data_loader.list_cities(subject)


def score_to_rank(subject: str, score: int) -> int:
    return data_loader.load_rank_converter().score_to_rank(subject, score)


# ---------------- 推荐结果表格渲染 ----------------
DISPLAY_COLS = [
    "院校名称", "专业组", "批次", "投档最低分", "最低位次", "分差",
    "录取概率", "城市", "院校层次", "代表专业", "数据",
]


def to_display(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["数据"] = out["位次估算"].map({True: "位次估算", False: "真实"})
    # 录取概率内部是 0~1 小数；ProgressColumn 的 printf 格式不会自动 ×100，
    # 这里转成 0~100 给显示用（max_value 同步设为 100），否则会全显示成 0%/1%。
    if "录取概率" in out.columns:
        out["录取概率"] = (out["录取概率"] * 100).round().astype(int)
    cols = [c for c in DISPLAY_COLS if c in out.columns]
    return out[cols]


def render_table(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("该档暂无匹配院校（可调整分数/筛选条件，或在『查看全部匹配院校』里看全量参考）。")
        return
    st.dataframe(
        to_display(df),
        hide_index=True,
        use_container_width=True,
        column_config={
            "投档最低分": st.column_config.NumberColumn("投档线", format="%d"),
            "最低位次": st.column_config.NumberColumn("最低位次", format="%d"),
            "分差": st.column_config.NumberColumn("分差", format="%+d", help="你的分数 − 该专业组投档线"),
            "录取概率": st.column_config.ProgressColumn(
                "录取概率(估算)", format="%.0f%%", min_value=0, max_value=100
            ),
            "代表专业": st.column_config.TextColumn(
                "代表专业(院校参考)",
                help="该校的优势/代表学科，仅院校层面参考；并非该专业组实际包含的专业"
                     "（专业组→专业明细需官方招生计划，暂未接入）。",
            ),
        },
    )


# ---------------- 侧边栏：考生信息录入 ----------------
def sidebar_inputs() -> dict | None:
    st.sidebar.header("📝 考生信息")
    st.sidebar.caption(f"省份：{config.PROVINCE}　|　年份：{config.YEAR}　|　模式：新高考 3+1+2")

    subject = st.sidebar.radio("首选科目（3+1+2 中的『1』）", ["物理", "历史"], horizontal=True)
    reselected = st.sidebar.multiselect(
        "再选科目（4 选 2）", RESELECT_OPTIONS, max_selections=2,
        help="新高考3+1+2：在 化学/生物/政治/地理 中选 2 门",
    )

    score = st.sidebar.number_input("高考分数", min_value=150, max_value=750, value=560, step=1)

    # 彩蛋：分数过低时给个「新赛道」入口（玩笑）
    if int(score) < config.RIDER_SCORE_THRESHOLD:
        st.sidebar.error(f"😵 分数低于 {config.RIDER_SCORE_THRESHOLD} 分…要不要了解一下新赛道？")
        st.sidebar.link_button("🛵 美团骑手注册", config.MEITUAN_RIDER_URL,
                               use_container_width=True)

    manual_rank = st.sidebar.checkbox("我知道自己的位次（手动输入）", value=False)
    if manual_rank:
        user_rank = st.sidebar.number_input("全省位次", min_value=1, max_value=300000, value=30000, step=1)
    else:
        user_rank = score_to_rank(subject, int(score))

    obey_adjust = st.sidebar.checkbox(
        "服从专业调剂", value=True,
        help="影响调剂风险评估：不服从且够不上组内专业时，退档风险高。")

    with st.sidebar.expander("🔎 筛选条件（可选）"):
        cities = st.multiselect("城市", get_cities(subject))
        levels = st.multiselect("院校层次", data_loader.list_levels())

    go = st.sidebar.button("🎯 生成志愿推荐", type="primary", use_container_width=True)

    if not go:
        return None
    if len(reselected) != 2:
        st.sidebar.error("请先选择 2 门再选科目。")
        return None
    return {
        "subject": subject,
        "reselected": reselected,
        "score": int(score),
        "user_rank": int(user_rank),
        "cities": cities,
        "levels": levels,
        "obey_adjust": obey_adjust,
    }


# ---------------- 顶部：分数 / 位次 / 批次线对照 ----------------
def render_overview(params: dict) -> None:
    lines = get_batch_lines()["batch_lines"][params["subject"]]
    benke = lines["本科线"]
    tekong = lines["特殊类型招生控制线"]
    score = params["score"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("高考分数", f"{score} 分")
    c2.metric("全省位次", f"{params['user_rank']:,}")
    c3.metric(f"{params['subject']}类本科线", f"{benke} 分", delta=f"{score - benke:+d}")
    c4.metric("特殊类型控制线", f"{tekong} 分", delta=f"{score - tekong:+d}")

    if score >= tekong:
        st.success(f"分数已达到特殊类型招生控制线（{tekong} 分），可关注强基计划/综合评价等。")
    elif score >= benke:
        st.info(f"分数已达到本科线（{benke} 分），低于特控线（{tekong} 分）。")
    else:
        st.warning(f"分数低于本科线（{benke} 分），建议重点关注专科批次（本样本数据以本科批为主）。")


# ---------------- 志愿推荐标签页 ----------------
TIER_PALETTE = {
    "冲刺(偏难)": "#b0b0b0", "冲": "#e8743b", "稳": "#19a979",
    "保": "#1f77b4", "保底(富余)": "#c9c9c9",
}


def render_rank_scatter(df: pd.DataFrame, user_rank: int) -> None:
    """位次散点图：x=院校专业组最低位次, y=录取概率, 按档位上色, 红线=你的位次。"""
    if df.empty:
        return
    with st.expander("📈 位次分布图（看你的位次落点与梯度密度）", expanded=False):
        d = df[["院校名称", "专业组", "投档最低分", "最低位次", "录取概率", "档位"]].copy()
        d["录取概率%"] = (d["录取概率"] * 100).round().astype(int)
        order = ["冲刺(偏难)", "冲", "稳", "保", "保底(富余)"]
        pts = alt.Chart(d).mark_circle(size=45, opacity=0.55).encode(
            x=alt.X("最低位次:Q", title="院校专业组最低位次（越小越靠前）"),
            y=alt.Y("录取概率%:Q", title="录取概率(估算 %)"),
            color=alt.Color("档位:N", scale=alt.Scale(domain=order,
                            range=[TIER_PALETTE[t] for t in order]), title="档位"),
            tooltip=["院校名称", "专业组", "投档最低分", "最低位次", "录取概率%", "档位"],
        )
        rule = alt.Chart(pd.DataFrame({"x": [user_rank]})).mark_rule(
            color="red", strokeDash=[5, 4], size=2).encode(
            x="x:Q", tooltip=alt.value(f"你的位次 ≈ {user_rank}"))
        st.altair_chart(pts + rule, use_container_width=True)
        st.caption("红色虚线是你的位次。点越靠红线左侧=录取线越强（冲），靠右=越稳。")


def render_recommend_tab(params: dict) -> pd.DataFrame:
    df = rec.recommend(
        subject=params["subject"],
        user_rank=params["user_rank"],
        reselected=params["reselected"],
        user_score=params["score"],
        cities=params["cities"],
        levels=params["levels"],
    )
    tiers = rec.split_by_tier(df)
    st.subheader("📋 冲稳保推荐")
    st.warning(
        "⚠️ 仅基于 **2025 单年** 投档位次估算。高校存在『大小年』波动——某校今年恰逢"
        "小年（线偏低）会被高估为更稳，明年可能回弹导致滑档。请把档位当**相对梯度参考**，"
        "并多查近 3 年位次趋势后再定。",
        icon="⚠️",
    )
    render_rank_scatter(df, params["user_rank"])

    for tier in ("冲", "稳", "保"):
        st.markdown(
            f"<h4 style='color:{TIER_COLOR[tier]};margin-bottom:0'>"
            f"【{tier}】<span style='font-size:0.7em;color:#888'> {TIER_DESC[tier]}</span></h4>",
            unsafe_allow_html=True,
        )
        render_table(tiers[tier])
        render_tier_majors(tiers[tier], params["user_rank"], params.get("obey_adjust", True))

    others = df[df["档位"].isin(["冲刺(偏难)", "保底(富余)"])]
    with st.expander(f"📑 查看全部匹配院校（共 {len(df)} 个，含偏难/富余，按录取概率排序）"):
        render_table(df)
        if not others.empty:
            st.caption("『冲刺(偏难)』= 录取线明显高于你的位次，把握较小；"
                       "『保底(富余)』= 你的位次远超录取线，可作绝对保底但可能浪费分数。")
    return df


def render_tier_majors(tier_df: pd.DataFrame, user_rank: int | None,
                       obey: bool = True, cap: int = 12) -> None:
    """在某一档表格下方，折叠展示该档各专业组的『专业级冲稳保』（仅有专业明细的组）。"""
    if tier_df.empty or "专业列表" not in tier_df.columns:
        return
    detail = tier_df[tier_df["专业列表"].apply(lambda x: isinstance(x, list) and len(x) > 0)]
    if detail.empty:
        return
    with st.expander(f"📂 该档 {len(detail)} 个专业组有专业明细 —— 看组内各专业能上哪些（冲/稳/保）"):
        st.caption("投档组最低分=进组门槛(常对应组内最冷专业)；热门专业的专业线更高，需更高位次。")
        for _, g in detail.head(cap).iterrows():
            st.markdown(
                f"**{g['院校名称']} {g['专业组']}** "
                f"<span style='color:#888;font-size:0.85em'>· 投档 {int(g['投档最低分'])} / 位次 {int(g['最低位次'])}</span>",
                unsafe_allow_html=True,
            )
            _major_table(g["专业列表"], user_rank, obey)
        if len(detail) > cap:
            st.caption(f"仅展开前 {cap} 个；其余可在『🔍 院校分数查询』里逐校查看。")


# ---------------- 院校分数查询标签页 ----------------
def _major_table(majors: list, user_rank: int | None, obey: bool = True) -> None:
    """渲染一个专业组的专业级分数线（带冲稳保标注 + 调剂风险，若已填位次）。"""
    mb = rec.major_breakdown(majors, user_rank)
    if mb.empty:
        st.caption("该专业组暂无专业级明细。")
        return
    if "录取概率" in mb.columns:
        mb = mb.copy()
        mb["录取概率"] = (mb["录取概率"] * 100).round().astype("Int64")
    cfg = {
        "最低分": st.column_config.NumberColumn("专业最低分", format="%d"),
        "最低位次": st.column_config.NumberColumn("专业最低位次", format="%d"),
    }
    if "录取概率" in mb.columns:
        cfg["录取概率"] = st.column_config.ProgressColumn(
            "录取概率(估算)", format="%.0f%%", min_value=0, max_value=100)
    st.dataframe(mb, hide_index=True, use_container_width=True, column_config=cfg)
    risk = rec.adjust_risk(majors, user_rank, obey)
    if risk:
        icon = {"低": "🟢", "中": "🟡", "高": "🔴"}[risk["level"]]
        st.caption(f"{icon} 调剂风险：{risk['level']} —— {risk['msg']}")


def render_school_query_tab(params: dict | None) -> None:
    st.subheader("🔍 院校分数查询")
    df = data_loader.load_admissions()
    user_rank = params.get("user_rank") if params else None
    obey = params.get("obey_adjust", True) if params else True
    if user_rank:
        st.caption(f"已按你的位次 ≈ {user_rank} 标注各专业的冲/稳/保。投档组最低分=进组门槛，"
                   "组内热门专业的专业线更高。")
    else:
        st.caption("可直接查询任意院校的专业组与专业级分数线；在左侧填写分数后还会标注冲/稳/保。")

    q = st.text_input("输入院校名称关键词", placeholder="如：南昌大学、北京、师范").strip()
    if not q:
        return
    schools = sorted(s for s in df["院校名称"].dropna().unique() if q in s)
    if not schools:
        st.warning(f"没找到包含『{q}』的院校。")
        return
    school = st.selectbox(f"匹配到 {len(schools)} 所，选择院校：", schools)
    sdf = df[df["院校名称"] == school]
    region = next((r for r in sdf["地区"] if isinstance(r, str) and r), "")
    city = sdf["城市"].dropna().astype(str).replace("", pd.NA).dropna()
    level = sdf["院校层次"].dropna().astype(str).replace("", pd.NA).dropna()
    meta = " · ".join(x for x in [region or (city.iloc[0] if len(city) else ""),
                                  level.iloc[0] if len(level) else ""] if x)
    st.markdown(f"#### {school}　<span style='color:#888;font-size:0.8em'>{meta}</span>",
                unsafe_allow_html=True)

    for first in ("物理", "历史"):
        gdf = sdf[sdf["首选科目"] == first].sort_values("最低位次")
        if gdf.empty:
            continue
        st.markdown(f"##### 首选 {first}（{len(gdf)} 个专业组）")
        st.dataframe(
            gdf[["专业组", "再选要求", "招生类型", "投档最低分", "最低位次", "批次"]],
            hide_index=True, use_container_width=True,
            column_config={
                "投档最低分": st.column_config.NumberColumn("投档线", format="%d"),
                "最低位次": st.column_config.NumberColumn("最低位次", format="%d"),
            },
        )
        for _, g in gdf.iterrows():
            majors = g["专业列表"]
            if isinstance(majors, list) and majors:
                with st.expander(f"📂 {g['专业组']} 专业明细（{len(majors)} 个专业）"):
                    _major_table(majors, user_rank, obey)


# ---------------- 按专业查询/推荐标签页 ----------------
def render_major_search_tab(params: dict | None) -> None:
    st.subheader("🎓 按专业查询 / 推荐")
    mdf = data_loader.load_majors()
    user_rank = params.get("user_rank") if params else None
    subject = params.get("subject") if params else None
    reselected = set(params.get("reselected", [])) if params else set()
    st.caption(f"覆盖 {len(mdf)} 条专业级分数线（仅含有专业明细的专业组，约占全部 1/3）。"
               "填了分数后按你的位次标注冲/稳/保，并按你的科目+选科过滤。")

    kw = st.text_input("输入专业关键词", placeholder="如：计算机、临床医学、法学、金融").strip()
    if not kw:
        return
    sub = mdf[mdf["专业名称"].str.contains(kw, na=False, regex=False)].copy()
    sub = sub[sub["专业最低位次"].notna()]
    if subject:
        sub = sub[sub["首选科目"] == subject]
        sub = sub[sub["再选要求"].apply(lambda r: rec._meets_requirement(r, reselected))]
    if sub.empty:
        st.warning(f"没找到包含『{kw}』的专业（可能其所在专业组无明细，或被你的科目/选科过滤）。")
        return

    cols = ["专业名称", "院校名称", "专业组", "城市", "招生类型", "专业最低分", "专业最低位次"]
    cfg = {
        "专业最低分": st.column_config.NumberColumn("最低分", format="%d"),
        "专业最低位次": st.column_config.NumberColumn("最低位次", format="%d"),
    }
    if user_rank:
        adv = (sub["专业最低位次"] - user_rank) / user_rank
        sub["档位"] = adv.apply(rec._classify)
        sub["录取概率"] = (adv.apply(rec._probability) * 100).round().astype("Int64")
        cols += ["档位", "录取概率"]
        cfg["录取概率"] = st.column_config.ProgressColumn(
            "录取概率(估算)", format="%.0f%%", min_value=0, max_value=100)
    sub = sub.sort_values("专业最低位次")
    st.caption(f"共 {len(sub)} 个匹配专业（按最低位次升序）")
    st.dataframe(sub[cols], hide_index=True, use_container_width=True, column_config=cfg)


# ---------------- 志愿表标签页 ----------------
def _wishlist_excel(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="志愿表")
    return buf.getvalue()


def render_wishlist_tab(params: dict | None) -> None:
    st.subheader("📝 生成志愿表")
    df = st.session_state.get("rec_df")
    if not params or df is None or df.empty:
        st.info("请先在『📋 志愿推荐』里生成推荐，再来这里一键铺志愿表。")
        return

    avail = {t: len(s) for t, s in rec.split_by_tier(df).items()}
    st.caption(f"可用候选：冲 {avail['冲']} / 稳 {avail['稳']} / 保 {avail['保']}　"
               "｜ 江西本科批平行志愿可填 45 个院校专业组（冲在前、保在后形成梯度）。")
    c1, c2, c3 = st.columns(3)
    n_c = c1.number_input("冲", 0, max(avail['冲'], 1), min(12, avail['冲']))
    n_w = c2.number_input("稳", 0, max(avail['稳'], 1), min(18, avail['稳']))
    n_b = c3.number_input("保", 0, max(avail['保'], 1), min(15, avail['保']))

    wish = rec.build_wish_list(df, int(n_c), int(n_w), int(n_b))
    if wish.empty:
        st.warning("候选不足或配额为 0，调整上面的数量。")
        return

    cols = ["序号", "院校名称", "专业组", "批次", "档位", "投档最低分",
            "最低位次", "录取概率", "城市", "院校层次"]
    disp = wish[[c for c in cols if c in wish.columns]].copy()
    disp["录取概率"] = (disp["录取概率"] * 100).round().astype(int).astype(str) + "%"
    st.dataframe(disp, hide_index=True, use_container_width=True,
                 column_config={
                     "投档最低分": st.column_config.NumberColumn("投档线", format="%d"),
                     "最低位次": st.column_config.NumberColumn("最低位次", format="%d"),
                 })
    st.download_button(
        "⬇️ 导出 Excel", data=_wishlist_excel(disp),
        file_name=f"志愿表_{config.PROVINCE}{config.YEAR}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.divider()
    st.markdown("##### 🤖 让 AI 排一份草案（含每条理由）")
    if not config.ENABLE_LLM:
        st.caption("（已在 config.py 关闭大模型）")
    elif st.button("生成 AI 志愿表草案", use_container_width=True):
        from core.llm_advisor import LLMAdvisor, build_wishlist_prompt
        summary = rec.summarize_for_llm(
            params["subject"], params["user_rank"], params["score"],
            params["reselected"], df, max_each=10, obey=params.get("obey_adjust", True))
        prompt = build_wishlist_prompt(summary, int(n_c), int(n_w), int(n_b))
        with st.spinner("AI 排版中（首次加载模型约5秒）..."):
            placeholder = st.empty()
            text = ""
            for piece in LLMAdvisor.instance().stream(
                    prompt, max_tokens=config.LLM_MAX_TOKENS_WISHLIST):
                text += piece
                placeholder.markdown(text)
        st.session_state["wishlist_ai"] = text
    elif st.session_state.get("wishlist_ai"):
        st.markdown(st.session_state["wishlist_ai"])


# ---------------- AI 顾问标签页 ----------------
def render_advisor_tab(params: dict, df: pd.DataFrame) -> None:
    st.subheader("🤖 AI 填报顾问（本地 Qwen3.5-9B）")
    if not config.ENABLE_LLM:
        st.warning("当前已在 config.py 中关闭大模型（ENABLE_LLM=False）。")
        return

    summary = rec.summarize_for_llm(
        params["subject"], params["user_rank"], params["score"],
        params["reselected"], df, obey=params.get("obey_adjust", True),
    )
    st.session_state["advice_context"] = summary

    if st.button("📊 让 AI 分析我的志愿方案", use_container_width=True):
        from core.llm_advisor import LLMAdvisor, build_advice_prompt
        advisor = LLMAdvisor.instance()
        prompt = build_advice_prompt(summary)
        with st.spinner("模型生成中（首次会加载约5GB模型，请稍候）..."):
            placeholder = st.empty()
            text = ""
            for piece in advisor.stream(prompt):
                text += piece
                placeholder.markdown(text)
        st.session_state["last_advice"] = text
    elif st.session_state.get("last_advice"):
        st.markdown(st.session_state["last_advice"])

    st.divider()
    st.markdown("##### 💬 继续追问")
    for msg in st.session_state.get("chat", []):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if q := st.chat_input("例如：临床医学对选科有什么要求？这几所学校哪个就业更好？"):
        from core.llm_advisor import LLMAdvisor
        advisor = LLMAdvisor.instance()
        st.session_state.setdefault("chat", []).append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        # 用推荐结果摘要为对话提供背景
        ctx = st.session_state.get("advice_context", "")
        history = [
            {"role": "user", "content": f"【我的志愿背景】\n{ctx}"},
            {"role": "assistant", "content": "好的，我已了解你的分数、位次和候选院校情况。"},
        ] + st.session_state["chat"][:-1]
        with st.chat_message("assistant"):
            placeholder = st.empty()
            text = ""
            with st.spinner("思考中..."):
                for piece in advisor.stream(q, history=history):
                    text += piece
                    placeholder.markdown(text)
        st.session_state["chat"].append({"role": "assistant", "content": text})


# ---------------- 主流程 ----------------
def main() -> None:
    st.title("🎓 高考志愿填报系统")
    st.caption(
        f"{config.PROVINCE} · {config.YEAR} · 新高考3+1+2　|　"
        "投档线/位次为 2025 年官方真实数据（单年），录取概率为启发式估算，正式填报请以官方信息为准。"
    )

    params = sidebar_inputs()
    if params:
        st.session_state["params"] = params
    params = st.session_state.get("params")

    if params:
        render_overview(params)
        st.divider()

    tab1, tab_wish, tab2, tab3, tab4 = st.tabs(
        ["📋 志愿推荐", "📝 生成志愿表", "🔍 院校分数查询", "🎓 按专业查询", "🤖 AI 填报顾问"])
    with tab1:
        if not params:
            st.info("👈 请在左侧填写首选科目、再选科目和分数，然后点击『生成志愿推荐』。")
            with st.expander("ℹ️ 关于本系统"):
                st.markdown(
                    "- **位次法推荐**：先把分数按一分一段表换算成全省位次，再与各院校专业组"
                    "往年最低录取位次比较，按『冲/稳/保』分档。\n"
                    "- **真实选科过滤**：用真·选科要求过滤院校专业组（物理类已覆盖）。\n"
                    "- **专业级查询**：在『院校分数查询』可看每个专业组里各专业的分数线。\n"
                    "- **AI顾问**：本地 Qwen3.5-9B 模型，结合你的推荐结果给出个性化建议与答疑。"
                )
        else:
            df = render_recommend_tab(params)
            st.session_state["rec_df"] = df
    with tab_wish:
        render_wishlist_tab(params)
    with tab2:
        render_school_query_tab(params)
    with tab3:
        render_major_search_tab(params)
    with tab4:
        df = st.session_state.get("rec_df")
        if not params:
            st.info("请先在左侧填写分数并生成推荐。")
        elif df is None:
            st.info("请先在『志愿推荐』标签页生成推荐。")
        else:
            render_advisor_tab(params, df)


if __name__ == "__main__":
    main()
