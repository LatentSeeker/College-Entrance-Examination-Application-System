# CLAUDE.md — 高考志愿填报系统

> 给后续接手的 Claude / 开发者快速上手用。记录项目目标、运行方式、架构、关键决策与已知坑点。

## 1. 项目是什么

江西省 **2025 年 · 新高考 3+1+2** 的高考志愿填报系统：

1. 考生输入分数/位次 + 首选科目(物理/历史) + 再选科目(4选2)。
2. 用一分一段表把分数换算成全省位次。
3. 按 **位次法** 与各院校专业组往年最低录取位次比较，给出 **冲/稳/保** 推荐。
4. 调用 **本地 Qwen3.5-9B 大模型** 结合推荐结果给出个性化填报方案与对话答疑。

UI 用 **Streamlit**。

## 2. 运行方式（环境是关键，容易踩坑）

```powershell
conda activate pytorch_nightly
cd D:\NewCode\高考志愿填报系统
streamlit run app.py

D:\Anaconda\envs\pytorch_nightly\python.exe -m streamlit run app.py
# 下载 cloudflared.exe 后，先正常起 streamlit，再开隧道
D:\cloudflared\cloudflared-windows-amd64.exe tunnel --url http://localhost:8501
```

- **必须用 conda 环境 `pytorch_nightly`**（Python 3.11）。它已装好所有依赖：
  `llama_cpp_python 0.3.29`(CUDA)、`streamlit 1.58`、`pandas 3.0`、`openpyxl` 等。
  解释器绝对路径：`D:\Anaconda\envs\pytorch_nightly\python.exe`
- **本地模型路径**：`D:\NewCode\Qwen3.5-9B\models\Qwen3.5-9B-Q4_K_S.gguf`（在 `config.py` 配置）。
  ⚠️ 参考脚本 `D:\NewCode\Qwen3.5-9B\chat.py` 里的路径是**错的**(`D:\NewCode\Qwen\models\...`)，别照抄。
- 模型 **懒加载**：只有进入「AI 填报顾问」标签并点分析时才加载。实测 RTX 5060 上 **GPU 加载约 5 秒、生成约 1.5 秒**，正常。
- 无显卡 / 只调界面：把 `config.py` 的 `ENABLE_LLM = False`。

## 3. 代码结构

```
app.py                 Streamlit 主界面（侧边栏录入 + 概览 + 5 tab：志愿推荐/生成志愿表/院校分数查询/按专业查询/AI顾问）
                       含：位次散点图、服从调剂开关+调剂风险、专业级冲稳保展开、985/211层次校正、
                       志愿表生成+Excel导出+AI一键草案、低分彩蛋
config.py              全局配置：数据文件路径、MODEL_PATH、N_GPU_LAYERS、冲稳保区间参数
core/
  data_loader.py       加载数据；合并富JSON；RankConverter 分数<->位次；load_majors() 专业级展开表
  recommender.py       recommend() 冲稳保引擎；major_breakdown() 专业级分档；adjust_risk() 调剂风险；split_by_tier()；summarize_for_llm()
  llm_advisor.py       LLMAdvisor 单例懒加载 llama_cpp；stream()/complete()；历史截断(LLM_MAX_HISTORY_MSGS)；
                       build_advice_prompt()/build_wishlist_prompt()；SYSTEM_PROMPT 是志愿顾问人设（temperature=0.4）
  school_tiers.py      权威 985/211 名单，硬校正院校层次（精确匹配覆盖，见第 4 节）
data/
  batch_lines_2025_jiangxi.json   批次线（本科/特控/专科，物理&历史）
  rank_table_2025_jiangxi.json    一分一段表锚点（离散分数->累计位次）
  admissions_2025_jiangxi.csv     院校专业组录取数据（核心数据集）
requirements.txt
.claude/launch.json    preview 工具用的 streamlit 启动配置（端口 8522）
```

## 4. 关键设计决策

- **位次法**：`advantage = (院校最低位次 − 考生位次) / 考生位次`。
  - `advantage < 0` → 院校录取线比考生强 → 冲；`≈0` → 稳；`>0` → 考生有优势 → 保。
  - 区间在 `config.py`：冲 `[-0.40,0)`、稳 `[0,0.12)`、保 `[0.12,0.50]`；超出区间的院校归入「冲刺(偏难)」「保底(富余)」**不丢弃**（保证稀疏数据下界面不空白）。
  - 录取概率 = **logistic/S 型**：`1/(1+exp(-k*advantage))`，`k=4*PROB_SLOPE`（中心斜率=PROB_SLOPE）。
    比旧的线性 `0.5+slope*advantage` 两端更平滑，深冲档不再被夹平成 1%。**启发式估算，非官方**。
- **分↔位次换算**：只存了若干公开锚点，锚点间线性插值，区间外线性外推（见 `RankConverter`）。
- **缺失位次自动补齐**：CSV 里 `最低位次` 留空的行，加载时用一分一段曲线估算，并打 `位次估算=True` 标记，界面显示「位次估算」。
- **选科过滤**：`再选要求` 取值 `不限`/`含化学`/`含生物`/`含地理`/`含政治`/`含化学和生物`，在
  `recommender._meets_requirement()` 里判定。**真·选科要求来自富 JSON**（见第 5 节），物理类已基本覆盖，
  过滤真正生效；未被 JSON 覆盖的（多为历史类）仍默认 `不限`。
- **专业级冲稳保**：富 JSON 含 `专业列表`（专业级最低分/位次）。`recommender.major_breakdown()` 把一个
  专业组展开成各专业的分档/概率——投档组最低分=进组门槛(组内最冷专业)，热门专业的专业线更高。
  界面在「院校分数查询」tab 展示。

## 5. 数据现状与如何更新（重要）

- **数据已是「全量官方」**：`data/admissions_2025_jiangxi.csv` 现有 **5232 条**院校专业组
  （物理 3582 + 历史 1650，1159 所院校），全部来自江西省教育考试院官方 PDF，
  **`最低位次` 是官方真值**（无估算，`位次估算=False`）。中分段不再稀疏。
- **数据怎么来的（抓取走不通，只能离线解析 PDF）**：
  - 掌上高考已上**付费墙**；本机网络 + harness 的 `WebFetch` 对 `*.gaokao.cn` / `jxeea.cn`
    一律 SSL 重置 / 502，**自动抓取彻底不通**。唯一能通的外网是 **GitHub**。
  - 办法：用**不被墙的途径**（手机流量 / VPN / 别的电脑）手动下载考试院那个**免费公开** PDF
    《2025年普通高校招生本科投档情况统计表(历史类、物理类、三校生类)》，丢到本地，
    再用 `tools/parse_jxeea_pdf.py` **离线解析**成 CSV。
  - 官方源：公告页 `http://www.jxeea.cn/jxsjyksy/gsgg91/content/content_1946824770752524288.html`
  - ⚠️ 旧的 `tools/fetch_admissions.py` 依赖免费 API，**已失效作废**，别再用。
- **重新解析 / 换年份**：把新 PDF 放好后跑
  `python tools/parse_jxeea_pdf.py [PDF路径]`（默认读 `data/江西投档情况.pdf`）。
  脚本会自动去水印「江西省教育考试院」、按 8 列结构映射、去重、备份旧 CSV。
  `data_loader` 有 `@lru_cache`，改数据后**重启 streamlit** 生效。
- **已知数据局限**：官方 PDF 只有投档分/位次，**没有**选科要求 / 城市 / 院校层次 / 代表专业。
  手工整理的旧 30 行（含城市/层次/专业）已备份到 `data/admissions_2025_jiangxi.curated.bak.csv`。
- **补全这 4 个字段**：跑 `tools/enrich_schools.py`（用本地 Qwen 按【院校】粒度生成，带缓存/断点续传）：
  - 城市、院校层次：模型常识可靠。
  - 代表专业：**院校层面**优势学科（参考），**不是**专业组实际包含的专业；真·「专业组→专业」
    明细在官方招生计划里（外网被墙拿不到）。界面列名标作「代表专业(院校参考)」。
  - 再选要求：本是专业组级官方数据，模型几乎无依据、**不可靠**，默认 `不限`，**别拿它做硬过滤**。
  - 缓存 `data/_school_enrich_cache.json` 缺字段会自动重抓（给旧缓存补新字段）。

CSV 列：`院校名称,专业组,首选科目,再选要求,投档最低分,最低位次,批次,城市,院校层次,代表专业`

### 5.1 真实富数据 JSON（含真·选科 / 专业级分数线）

- 文件：`data/高校分数线提取数据_20260624_141910.json`（`config.ADMISSIONS_JSON_FILE`）。
  结构：`[{学校名称,地区,专业组:[{选科要求,招生类型,最低分,最低位次,专业列表:[{专业名称,最低分,最低位次}]}],...}]`。
- 特点：**物理类为主**（约 1685 物理 / 13 历史）、**1711 个专业组**（比官方 PDF 的 5232 少）、
  仅 **31% 专业组带专业明细**、`地区` 字段较脏（含省份/学院前缀）。
- 合并策略（`data_loader.load_admissions()`）：**以官方 PDF(CSV) 为主干**保证全覆盖，
  按 `(院校名称, 专业组代号, 首选科目)` 把 JSON 的 **真·再选要求 + 专业列表 + 招生类型** 叠加上去
  （匹配率约 89%）；JSON 独有的专业组（提前批/专科等约 189 个）追加为新行。
  `城市` 仍用模型补的干净值（JSON 的 `地区` 只在「院校分数查询」里原样展示）。
  合并后约 5405 行，新增列：`专业列表`(list)、`招生类型`、`选科真实`(bool)、`地区`。

## 6. 已知坑点 / 测试经验

- **控制台中文乱码**：跑测试脚本时加 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1`，否则 Windows 控制台 print 中文是乱码（数据本身没问题）。
- **Streamlit 预览测试**：
  - 视口要宽（≥ ~1000px），否则侧边栏自动折叠、控件点不到。用 `preview_resize` 设 1440×900。
  - `preview_click` 的合成点击**有时不触发** Streamlit 的 React 事件；改用 `preview_eval` 执行原生 `element.click()` 更稳。
  - `st.dataframe` 用 canvas 渲染，单元格文字**不在 DOM**里，`innerText` 读不到表格内容，别据此判断表格为空——用 `[data-testid="stDataFrame"]` 计数判断。
- **大模型联网倾向**：即便 SYSTEM_PROMPT 已要求「只能从系统给出的候选院校中推荐、不要编造」，模型仍可能补充记忆里的院校。若要更严格，进一步收紧 `core/llm_advisor.py` 的 `SYSTEM_PROMPT`。

## 7. 验证状态

全流程已在浏览器端到端跑通：表单录入 → 指标/批次线对照 → 冲稳保分档表格 → AI 顾问在 Streamlit 内成功加载模型并流式输出完整填报方案。数据换算结果与一分一段表吻合。

## 8. 可能的后续工作

- ~~接入完整官方投档数据~~ ✅ 已完成（5232 条官方数据，见第 5 节）。
- ~~补齐城市 / 院校层次 / 代表专业~~ ✅ 已用 `tools/enrich_schools.py`（本地模型）补齐（见第 5 节）。
  仍待官方招生计划：真·「专业组→专业」明细、可靠的专业组级选科要求。
- ~~按专业查询/推荐、调剂风险、位次散点图、985/211层次校正、专科兜底~~ ✅ 已完成。
- ~~志愿表生成 + Excel 导出 + AI 一键草案~~ ✅ 已完成（`recommender.build_wish_list()` + 志愿表 tab）。
- 支持其他省份 / 传统文理分科模式（目前硬编码江西 3+1+2）。
- 多年份数据做位次趋势分析（缓解『大小年』，目前仍单年）。
