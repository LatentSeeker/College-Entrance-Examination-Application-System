"""把江西省教育考试院官方 PDF《2025年普通高校招生本科投档情况统计表》
解析成本系统要求的 admissions CSV。

为什么有这个脚本（看 CLAUDE.md 第 5 节 + 历史教训）：
  掌上高考已上付费墙，且本机网络屏蔽了 *.gaokao.cn / jxeea.cn（SSL 重置 / 502），
  WebFetch 同样不通——自动抓取彻底走不通。唯一可靠的办法是：用不被墙的途径
  （手机流量 / VPN / 别的电脑）手动下载考试院那个【免费公开】PDF，丢到本地，
  再用这个脚本离线解析。旧的 tools/fetch_admissions.py 依赖免费 API，已失效。

官方源（写死在 Chenwenwen1007/China-query-of-college-admission-score 的配置里，
本脚本据其 load_jiangxi_pdf_scores 的列结构改写）：
  公告页 http://www.jxeea.cn/jxsjyksy/gsgg91/content/content_1946824770752524288.html
  PDF    .../1946824770752524288/6GtVOODt.pdf
  标题《江西省2025年普通高校招生本科投档情况统计表(历史类、物理类、三校生类)》

PDF 列结构（8 列）：
  序号 | 科类 | 院校代号 | 院校名称 | 专业组代号 | 专业组名称 | 投档线 | 最低投档排名

坑点：PDF 上斜向铺了水印「江西省教育考试院」。pdfplumber 抽表时，水印字符会作为
  【独立的 \n 分片】混进单元格，例如 '院\n北京师范大学'、'考\n0007'、'西\n527'。
  清洗策略：按 \n 切片后，丢掉「单字且是水印字」的分片，再拼接——这样既能去水印，
  又不会误伤「西南大学 / 江南大学」这类以水印同字开头的真实校名（它们整体是一个
  多字分片，不会被丢）。数字字段（代号/分数/位次）直接抽 \d 即可，水印是汉字不受影响。

用法：
  conda activate pytorch_nightly
  cd D:\\NewCode\\高考志愿填报系统
  python tools/parse_jxeea_pdf.py            # 解析默认 PDF -> 覆盖主 CSV（自动备份旧的）
  python tools/parse_jxeea_pdf.py 路径.pdf   # 指定 PDF
改完数据后重启 streamlit 才生效（data_loader 有 lru_cache）。
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = ROOT / "data" / "江西投档情况.pdf"
OUT_CSV = ROOT / "data" / "admissions_2025_jiangxi.csv"

CSV_COLUMNS = [
    "院校名称", "专业组", "首选科目", "再选要求",
    "投档最低分", "最低位次", "批次", "城市", "院校层次", "代表专业",
]

# 水印「江西省教育考试院」逐字集合
WM = set("江西省教育考试院")
# 科类 -> 系统的「首选科目」；三校生类不属于普通 3+1+2，跳过
SUBJECT_MAP = {"历史": "历史", "物理": "物理"}


def clean_text_cell(value: object) -> str:
    """去水印的文本清洗：按 \n 切片，丢掉「单字水印」分片后拼接。

    水印字在单元格里几乎总是【前缀/独立】分片（如 '试\\n北京…'）；而真实校名因列宽
    换行，其最后一个字可能单独成片（如 '…东方学\\n院' 里的 '院' 是真的）。所以规则：
    单字水印分片一律丢弃，但若它是【最后一片且前面已有内容】，视作真实换行续字保留。
    """
    parts = [p.strip() for p in str(value or "").replace("\r", "\n").split("\n") if p.strip()]
    kept: list[str] = []
    last = len(parts) - 1
    for i, p in enumerate(parts):
        if len(p) == 1 and p in WM and not (i == last and kept):
            continue
        kept.append(p)
    return "".join(kept)


def digits(value: object) -> str:
    """抽出全部数字并拼接（水印是汉字，天然不受影响）。"""
    return re.sub(r"\D", "", str(value or ""))


def map_subject(cell: object) -> str | None:
    text = clean_text_cell(cell)
    for key, val in SUBJECT_MAP.items():
        if key in text:
            return val
    return None  # 三校生类等 -> 跳过


def make_group_label(code_cell: object, name_cell: object) -> str:
    """专业组标签：『101组』；若专业组名称带括号备注（如(国家专项)）则附上。"""
    code = digits(code_cell)
    name = clean_text_cell(name_cell).replace("（", "(").replace("）", ")")
    note = ""
    m = re.search(r"\(([^)]*)\)", name)
    if m:
        note = f"({m.group(1)})"
    base = f"{code}组" if code else (name or "01组")
    return base + note


def parse_pdf(pdf_path: Path) -> list[dict]:
    rows: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for raw in table[1:]:  # 跳过表头行
                    if not raw or len(raw) < 8:
                        continue
                    subject = map_subject(raw[1])
                    if subject is None:
                        continue
                    school = clean_text_cell(raw[3])
                    score = digits(raw[6])
                    rank = digits(raw[7])
                    if not school or not score:
                        continue
                    rows.append({
                        "院校名称": school,
                        "专业组": make_group_label(raw[4], raw[5]),
                        "首选科目": subject,
                        "再选要求": "不限",          # PDF 无选科信息，默认不限（见文件头说明）
                        "投档最低分": score,
                        "最低位次": rank,             # 官方真值；留空时系统会用一分一段估算
                        "批次": "本科批",
                        "城市": "",
                        "院校层次": "",
                        "代表专业": "",
                    })
    return rows


def dedup(rows: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for r in rows:
        key = (r["院校名称"], r["专业组"], r["首选科目"], r["投档最低分"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main() -> None:
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    if not pdf_path.exists():
        sys.exit(f"找不到 PDF：{pdf_path}")

    print(f"解析 {pdf_path} ...")
    rows = dedup(parse_pdf(pdf_path))
    if not rows:
        sys.exit("没解析出任何行——PDF 表格结构可能变了，请检查列映射。")

    by_subj: dict[str, int] = {}
    for r in rows:
        by_subj[r["首选科目"]] = by_subj.get(r["首选科目"], 0) + 1
    print(f"解析得到 {len(rows)} 条（去重后）：{by_subj}")

    # 备份旧 CSV（旧的手工 30 行带 城市/院校层次/代表专业，别丢）
    if OUT_CSV.exists():
        bak = OUT_CSV.with_suffix(".curated.bak.csv")
        if not bak.exists():
            bak.write_bytes(OUT_CSV.read_bytes())
            print(f"已备份旧 CSV -> {bak.name}")

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"写出 {len(rows)} 条 -> {OUT_CSV}")
    print("提示：重启 streamlit 才生效（data_loader 有 lru_cache）。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
