"""【已作废 / DEPRECATED — 请勿使用】

  本脚本依赖掌上高考的免费 API，但该数据已上【付费墙】，且本机网络对
  *.gaokao.cn / jxeea.cn 一律 SSL 重置 / 502，自动抓取彻底走不通。
  正确做法见 CLAUDE.md 第 5 节：手动下载考试院官方免费 PDF，再用
  tools/parse_jxeea_pdf.py 离线解析。此文件仅作历史留存。

================================================================================

抓取江西 2025 全量「院校专业组投档线」-> 生成 data/admissions_2025_jiangxi.csv

数据源：掌上高考 / 中国教育在线（前端 gkcx.eol.cn，后端 api.zjzw.cn）。

================================================================================
                          运行前必读（很重要）
================================================================================
掌上高考的接口有反爬，参数结构 / 签名（signsafe）会不定期变化。所以本脚本把
「真实请求」抽到下面的 CONFIG 区，你需要先用浏览器把当前能用的请求抓出来，填进去：

  1. 浏览器打开掌上高考「2025 江西 院校专业组投档/录取分数线」那个页面，
     让它把表格加载出来、并翻一页（触发真正的数据请求）。
  2. F12 -> Network(网络) -> 过滤 XHR/Fetch。
  3. 找到返回 JSON 表格数据的那个请求（响应里能看到院校名/分数/位次）。
  4. 右键该请求 -> Copy -> Copy as cURL，或者直接看它的：
        - 请求 URL（填到 API_URL）
        - 请求方法 GET / POST（填到 HTTP_METHOD）
        - Query / Body 参数（填到 BASE_PARAMS）
        - 关键请求头：cookie、user-agent、referer（填到 HEADERS）
  5. 注意参数里可能有：
        - page / size（分页，脚本会自动翻页）
        - signsafe（MD5 签名，见 build_signsafe，若接口需要请按实际算法补全）
        - 省份/年份/批次/科类 的 id（填到 BASE_PARAMS）

填好后：
    conda activate pytorch_nightly
    cd D:\NewCode\高考志愿填报系统
    python tools/fetch_admissions.py

脚本特性：
  - 自动翻页直到没有数据；失败自动重试；每页之间礼貌延时，避免被封。
  - 断点续传：抓到的原始数据先落盘到 tools/_raw_admissions.jsonl，
    中途中断再次运行会跳过已抓页码。
  - 字段映射 + 去重，最终输出符合系统要求的 10 列 CSV。
  - 「最低位次」拿不到也没关系：留空即可，系统加载时会用一分一段表自动估算。
================================================================================
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from pathlib import Path

import requests

# ============================== CONFIG（按上面说明填写） ==============================

# 接口地址。下面是掌上高考常见的后端域名，请用你抓到的真实 URL 覆盖。
API_URL = "https://api.zjzw.cn/web/api/"

HTTP_METHOD = "POST"          # 多数 eol 接口是 POST；若你抓到的是 GET 改成 "GET"

# 基础参数（不含分页）。把你从 Network 里看到的参数原样填进来。
# 下面只是“占位示例”，字段名/取值务必以你抓到的真实请求为准！
BASE_PARAMS: dict = {
    "province_id": "36",      # 江西省国标码=36（示例，以实际为准）
    "year": "2025",
    "local_batch_id": "",     # 批次 id（本科批/专科批），以实际为准
    "select_status": "",      # 选科/科类，以实际为准
    "size": "20",             # 每页条数（脚本按此翻页）
    # "signsafe": "...",      # 若接口要求签名，由 build_signsafe() 自动生成
}

# 分页字段名 & 起始页（有的接口从 1 开始，有的从 0）
PAGE_PARAM = "page"
PAGE_START = 1

# 请求头：cookie / user-agent / referer 经常是过反爬的关键，请填你浏览器里的真实值。
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://www.gaokao.cn/",
    "Origin": "https://www.gaokao.cn",
    "Accept": "application/json, text/plain, */*",
    # "Cookie": "把你浏览器里的 Cookie 整段粘到这里",
}

# 是否需要对参数做 MD5 签名（signsafe）。多数 eol 接口需要。
# 若需要，请确认 SIGN_SALT（盐）—— 它藏在站点前端 JS 里，需要你自己从浏览器
# Sources 面板搜 "signsafe" 找到拼接规则。下面给的是“按参数升序拼接+盐”的通用实现，
# 不保证与当前站点一致，请按实际算法调整 build_signsafe()。
USE_SIGNSAFE = False
SIGN_SALT = ""                # 例如某些版本用固定盐，需自行确认

# 重试 / 限速
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0           # 第 n 次失败后等待 RETRY_BACKOFF * n 秒
DELAY_BETWEEN_PAGES = 1.2     # 每页之间延时（秒），避免请求过快被封
REQUEST_TIMEOUT = 20
MAX_PAGES = 1000              # 安全上限，防止死循环

# 输出
ROOT = Path(__file__).resolve().parent.parent
RAW_FILE = Path(__file__).resolve().parent / "_raw_admissions.jsonl"
OUT_CSV = ROOT / "data" / "admissions_2025_jiangxi.csv"

CSV_COLUMNS = [
    "院校名称", "专业组", "首选科目", "再选要求",
    "投档最低分", "最低位次", "批次", "城市", "院校层次", "代表专业",
]

# =============================== 工具函数 ===============================


def build_signsafe(params: dict) -> str:
    """按参数生成 signsafe 签名（占位通用实现，按站点实际算法调整）。"""
    items = sorted((k, str(v)) for k, v in params.items() if k != "signsafe")
    raw = "&".join(f"{k}={v}" for k, v in items) + SIGN_SALT
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def fetch_page(session: requests.Session, page: int) -> dict:
    """抓取单页，返回解析后的 JSON。带重试。"""
    params = dict(BASE_PARAMS)
    params[PAGE_PARAM] = page
    if USE_SIGNSAFE:
        params["signsafe"] = build_signsafe(params)

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if HTTP_METHOD.upper() == "GET":
                resp = session.get(API_URL, params=params, headers=HEADERS,
                                   timeout=REQUEST_TIMEOUT)
            else:
                resp = session.post(API_URL, json=params, headers=HEADERS,
                                    timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = RETRY_BACKOFF * attempt
            print(f"  [第{page}页] 第{attempt}次失败：{e} -> {wait:.0f}s 后重试")
            time.sleep(wait)
    raise RuntimeError(f"第 {page} 页重试 {MAX_RETRIES} 次仍失败：{last_err}")


def extract_rows(payload: dict) -> list[dict]:
    """从接口返回里取出“记录列表”。

    不同接口列表所在路径不同，常见：data.item / data.list / data.numFound 等。
    这里做了几种常见路径的兜底，若都取不到，请 print(payload) 看结构后改这里。
    """
    data = payload.get("data", payload)
    if isinstance(data, dict):
        for key in ("item", "list", "items", "rows", "records", "result"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    if isinstance(data, list):
        return data
    return []


def pick(d: dict, *keys: str, default: str = "") -> str:
    """从记录里按多个可能的字段名取第一个非空值。"""
    for k in keys:
        if k in d and d[k] not in (None, "", "-"):
            return str(d[k]).strip()
    return default


def normalize_level(tags: str) -> str:
    """把院校标签规整成 985/211/双一流 这种层次串。"""
    hits = []
    for tag in ("985", "211", "双一流", "强基", "国重点", "省重点"):
        if tag in tags:
            hits.append(tag)
    return "/".join(hits)


def normalize_requirement(text: str) -> str:
    """再选要求规整为：不限 / 含化学 / 含化学和生物 等。"""
    t = (text or "").replace(" ", "")
    if not t or "不限" in t or "不提" in t:
        return "不限"
    return t


def map_record(rec: dict) -> dict:
    """把单条原始记录映射到系统 CSV 的 10 列。

    ⚠️ 下面用的源字段名（school_name 等）是“常见命名猜测”，请用你抓到的
    真实 JSON 字段名对照修改。先跑一次看 _raw_admissions.jsonl 里的真实字段。
    """
    first_subject = pick(rec, "first_subject", "subject", "sg_name", default="物理")
    # 把“首选物理/物理类”等清洗成 物理 / 历史
    if "历史" in first_subject:
        first_subject = "历史"
    elif "物理" in first_subject:
        first_subject = "物理"

    return {
        "院校名称": pick(rec, "school_name", "name", "college_name"),
        "专业组": pick(rec, "professional_name", "group_name", "sg_name",
                       "zydz_name", "major_group", default="01组"),
        "首选科目": first_subject,
        "再选要求": normalize_requirement(
            pick(rec, "reselect", "subject_require", "sx_yq", default="不限")),
        "投档最低分": pick(rec, "min", "min_score", "score", "tdf", "投档线"),
        "最低位次": pick(rec, "min_section", "rank", "min_rank", "wc", "位次"),
        "批次": pick(rec, "batch_name", "local_batch_name", "batch", default="本科批"),
        "城市": pick(rec, "city_name", "city", "address"),
        "院校层次": normalize_level(
            pick(rec, "level", "tags", "type_name", "school_type")),
        "代表专业": pick(rec, "major_list", "majors", "represent_major"),
    }


def load_done_pages() -> set[int]:
    """读取已抓页码（断点续传）。"""
    done = set()
    if RAW_FILE.exists():
        with RAW_FILE.open(encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["_page"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def append_raw(page: int, rows: list[dict]) -> None:
    with RAW_FILE.open("a", encoding="utf-8") as f:
        for r in rows:
            r = dict(r)
            r["_page"] = page
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def crawl() -> None:
    """主抓取循环：翻页 -> 落盘原始数据。"""
    session = requests.Session()
    done = load_done_pages()
    if done:
        print(f"断点续传：已抓 {len(done)} 页，将跳过这些页码。")

    page = PAGE_START
    empty_streak = 0
    while page < PAGE_START + MAX_PAGES:
        if page in done:
            page += 1
            continue

        print(f"抓取第 {page} 页 ...")
        payload = fetch_page(session, page)
        rows = extract_rows(payload)

        if not rows:
            empty_streak += 1
            print(f"  第 {page} 页无数据（连续 {empty_streak} 页空）。")
            if empty_streak >= 2:
                print("连续空页，判定已到末页，停止。")
                break
        else:
            empty_streak = 0
            append_raw(page, rows)
            print(f"  +{len(rows)} 条")

        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    print("抓取阶段完成。")


def build_csv() -> None:
    """把原始 jsonl 映射 + 去重 -> 写出最终 CSV。"""
    if not RAW_FILE.exists():
        print("没有原始数据，先成功跑一次抓取。")
        return

    seen: set[tuple] = set()
    out_rows: list[dict] = []
    with RAW_FILE.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = map_record(rec)
            if not row["院校名称"] or not row["投档最低分"]:
                continue
            key = (row["院校名称"], row["专业组"], row["首选科目"], row["投档最低分"])
            if key in seen:
                continue
            seen.add(key)
            out_rows.append(row)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"写出 {len(out_rows)} 条 -> {OUT_CSV}")
    print("提示：改完数据后重启 streamlit 才生效（data_loader 有 lru_cache）。")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("crawl", "all"):
        crawl()
    if mode in ("csv", "all"):
        build_csv()


if __name__ == "__main__":
    # Windows 控制台中文输出避免乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
