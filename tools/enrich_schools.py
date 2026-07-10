"""用【本地 Qwen3.5-9B 模型】为院校补全 城市 / 院校层次 / 再选要求 / 代表专业 四个字段。

为什么需要：官方投档 PDF 只有投档分/位次，没有城市、院校层次（985/211/双一流）、
选科要求——导致侧边栏的城市/层次筛选是空的（见 CLAUDE.md 第 5 节局限）。这些是
稳定属性，可由本地大模型凭常识补出，无需联网（外网高考站点也都被墙）。

⚠️ 重要：本脚本【只调用本地模型】(llama_cpp + config.MODEL_PATH)，不走任何在线 API。

字段可靠性（务必知悉）：
  - 城市、院校层次：模型常识可靠，按【院校】粒度生成（1159 所，远少于 5232 行）。
  - 再选要求：本是【专业组】级官方数据，而本表的专业组只有「101组」这种代号、无专业
    信息，模型几乎无依据，生成结果【不可靠】。脚本会约束取值并默认「不限」，但强烈
    建议：要么别用它做硬过滤，要么后续接入官方招生计划数据再覆盖。
  - 代表专业：是【院校层面】的优势/代表学科（模型常识，较可靠），**不是**某个专业组
    实际包含的专业。真正的「专业组→专业」明细在官方招生计划里（本机外网被墙拿不到）。
    所以界面/AI 里它只能作为「院校代表专业(参考)」，不能当作该组的录取专业清单。

特性：
  - 按【唯一院校名】去重后逐校询问，结果缓存到 data/_school_enrich_cache.json；
    中途中断再次运行会跳过已完成的院校（断点续传）。
  - 取值规整：院校层次只保留 {985,211,双一流,普通本科,专科}；再选要求只允许
    {不限,含化学,含化学和生物}；非法值回落到安全默认。
  - apply 阶段把缓存写回 CSV 的对应列（先自动备份 CSV）。

用法：
  conda activate pytorch_nightly
  cd D:\\NewCode\\高考志愿填报系统
  python tools/enrich_schools.py            # 先补缓存(调模型) 再写回 CSV
  python tools/enrich_schools.py cache      # 只补缓存（可先人工检查 _school_enrich_cache.json）
  python tools/enrich_schools.py apply       # 只把现有缓存写回 CSV
改完数据后重启 streamlit 才生效（data_loader 有 lru_cache）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

# 允许从 tools/ 目录直接运行：把项目根目录加入 import 路径，否则找不到 config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

CACHE_FILE = config.DATA_DIR / "_school_enrich_cache.json"
CSV_FILE = config.ADMISSIONS_FILE

VALID_LEVELS = ["985", "211", "双一流", "普通本科", "专科"]
VALID_REQS = {"不限", "含化学", "含化学和生物"}
# 缓存条目必须包含的字段；缺任一项视为未完成，会被重新询问（便于给旧缓存补新字段）
REQUIRED_KEYS = ("城市", "院校层次", "再选要求", "代表专业")

SYS_PROMPT = (
    "你是中国高校基础信息库。用户给出一个高校名称，你只输出一个 JSON 对象，"
    "不要任何解释、前后缀或 markdown。字段：\n"
    '  "城市": 该校主校区所在地级市（只写市名，如 "北京"、"南昌"、"上海"；'
    "若名称含『(XX校区)』则填该校区所在市）。\n"
    '  "院校层次": 从 ["985","211","双一流","普通本科","专科"] 中选若干，用"/"连接，'
    "按 985/211/双一流 顺序；985 高校通常也是 211 和双一流；只是双一流非 985/211 的填"
    '"双一流"；普通本科填 "普通本科"；高职专科填 "专科"。\n'
    '  "再选要求": 该校多数专业的再选科目要求，从 ["不限","含化学","含化学和生物"] 中选，'
    "拿不准就填 \"不限\"。\n"
    '  "代表专业": 该校最有代表性/最强的 2-4 个本科专业或优势学科，用顿号分隔；'
    "这是【院校层面】的优势学科，不是某个专业组的具体专业，拿不准就留空字符串。\n"
    '示例：输入「北京邮电大学」输出 '
    '{"城市":"北京","院校层次":"211/双一流","再选要求":"不限","代表专业":"通信工程、计算机科学与技术、电子信息工程"}'
)


def load_model():
    from llama_cpp import Llama  # 延迟导入

    print(f"加载本地模型：{config.MODEL_PATH}")
    return Llama(
        model_path=config.MODEL_PATH,
        n_gpu_layers=config.N_GPU_LAYERS,
        n_ctx=config.N_CTX,
        n_batch=config.N_BATCH,
        verbose=False,
    )


def parse_json_obj(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def normalize_level(value: str) -> str:
    text = str(value or "")
    hits = [lv for lv in VALID_LEVELS if lv in text]
    # 985 默认补 211/双一流；211 默认补双一流（符合常识，便于层次筛选）
    if "985" in hits:
        for lv in ("211", "双一流"):
            if lv not in hits:
                hits.append(lv)
    elif "211" in hits and "双一流" not in hits:
        hits.append("双一流")
    if not hits:
        return "普通本科"
    if "专科" in hits and len(hits) > 1:  # 专科与本科层次互斥，专科优先剔除噪声
        hits = ["专科"]
    return "/".join([lv for lv in VALID_LEVELS if lv in hits])


def normalize_city(value: str) -> str:
    city = str(value or "").strip().splitlines()[0] if value else ""
    city = city.strip().strip("。.,，")
    if city.endswith("市"):
        city = city[:-1]
    return city


def normalize_req(value: str) -> str:
    v = str(value or "").strip()
    return v if v in VALID_REQS else "不限"


def normalize_majors(value: str) -> str:
    """代表专业规整：统一分隔符为顿号，最多取 4 个。"""
    text = str(value or "")
    for sep in ("，", ",", "/", ";", "；", " ", "、"):
        text = text.replace(sep, "、")
    parts = [p.strip() for p in text.split("、") if p.strip()]
    return "、".join(parts[:4])


def ask_school(llm, school: str) -> dict:
    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": school},
        ],
        temperature=0.1,
        max_tokens=200,
    )
    obj = parse_json_obj(resp["choices"][0]["message"]["content"])
    return {
        "城市": normalize_city(obj.get("城市", "")),
        "院校层次": normalize_level(obj.get("院校层次", "")),
        "再选要求": normalize_req(obj.get("再选要求", "")),
        "代表专业": normalize_majors(obj.get("代表专业", "")),
    }


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def build_cache() -> dict:
    df = pd.read_csv(CSV_FILE)
    schools = sorted(df["院校名称"].dropna().unique().tolist())
    cache = load_cache()
    # 缺任一必需字段都算未完成（旧缓存补新字段时会自动重抓这些校）
    def done(s: str) -> bool:
        e = cache.get(s)
        return isinstance(e, dict) and all(k in e for k in REQUIRED_KEYS)

    todo = [s for s in schools if not done(s)]
    print(f"院校总数 {len(schools)}，已完整缓存 {len(schools) - len(todo)}，待处理 {len(todo)}")
    if not todo:
        return cache

    llm = load_model()
    t0 = time.time()
    for i, school in enumerate(todo, 1):
        try:
            cache[school] = ask_school(llm, school)
        except Exception as e:  # noqa: BLE001
            print(f"  [{school}] 失败：{e} -> 暂填默认")
            cache[school] = {"城市": "", "院校层次": "普通本科", "再选要求": "不限"}
        if i % 20 == 0 or i == len(todo):
            save_cache(cache)
            rate = i / (time.time() - t0)
            eta = (len(todo) - i) / rate if rate else 0
            print(f"  {i}/{len(todo)}  {school} -> {cache[school]}  (~{eta/60:.1f} 分钟剩余)")
    save_cache(cache)
    print(f"缓存完成 -> {CACHE_FILE}")
    return cache


def apply_cache() -> None:
    cache = load_cache()
    if not cache:
        sys.exit("缓存为空，先运行 `python tools/enrich_schools.py cache`。")
    df = pd.read_csv(CSV_FILE)

    bak = CSV_FILE.with_suffix(".pre_enrich.bak.csv")
    if not bak.exists():
        bak.write_bytes(CSV_FILE.read_bytes())
        print(f"已备份 CSV -> {bak.name}")

    def get(school, key, default=""):
        return cache.get(str(school), {}).get(key, default)

    df["城市"] = df["院校名称"].map(lambda s: get(s, "城市"))
    df["院校层次"] = df["院校名称"].map(lambda s: get(s, "院校层次", "普通本科"))
    df["再选要求"] = df["院校名称"].map(lambda s: get(s, "再选要求", "不限"))
    df["代表专业"] = df["院校名称"].map(lambda s: get(s, "代表专业"))

    df.to_csv(CSV_FILE, index=False, encoding="utf-8")
    filled = (df["城市"].astype(str).str.len() > 0).sum()
    print(f"已写回 {len(df)} 行；城市非空 {filled} 行 -> {CSV_FILE}")
    print("提示：重启 streamlit 才生效（data_loader 有 lru_cache）。")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("cache", "all"):
        build_cache()
    if mode in ("apply", "all"):
        apply_cache()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
