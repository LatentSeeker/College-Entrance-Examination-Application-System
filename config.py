"""全局配置。"""
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

# ============ 数据文件 ============
PROVINCE = "江西"
YEAR = 2025
BATCH_LINES_FILE = DATA_DIR / "batch_lines_2025_jiangxi.json"
RANK_TABLE_FILE = DATA_DIR / "rank_table_2025_jiangxi.json"
ADMISSIONS_FILE = DATA_DIR / "admissions_2025_jiangxi.csv"
# 真实富数据（含真·选科要求 / 专业级分数线 / 地区）；用于覆盖 CSV 的对应专业组并补充明细。
# 见 CLAUDE.md 第 5 节：物理类为主、约 1711 个专业组、31% 带专业明细，与官方 PDF 合并使用。
ADMISSIONS_JSON_FILE = DATA_DIR / "高校分数线提取数据_20260624_141910.json"

# ============ 本地大模型 ============
# Qwen3.5-9B GGUF 本地模型路径
MODEL_PATH = r"D:\NewCode\Qwen3.5-9B\models\Qwen3.5-9B-Q4_K_S.gguf"
N_GPU_LAYERS = -1      # -1=尽量全部放GPU；显存不足(OOM)时改成具体层数如 24
N_CTX = 8192           # 上下文长度；显存紧张可改 4096
N_BATCH = 256
LLM_TEMPERATURE = 0.4   # 偏事实建议，调低更稳（原 0.7 容易发散/编造）
LLM_MAX_TOKENS = 2048   # 默认输出上限（原 1024 太小，长建议会被掐断）
LLM_MAX_TOKENS_WISHLIST = 4096   # 志愿表草案要列 ~45 条，需更大额度（n_ctx=8192 容得下）
LLM_MAX_HISTORY_MSGS = 10   # 多轮对话最多保留最近 N 条历史，防止超出 n_ctx

# 是否启用大模型（设为 False 时界面仍可用，仅AI顾问不可用，便于无显卡环境调试）
ENABLE_LLM = True

# ============ 彩蛋：低分提示 ============
# 分数低于此阈值时，侧边栏出现「美团骑手注册」入口（玩笑功能）。
RIDER_SCORE_THRESHOLD = 251
# ⚠️ 占位 URL，换成你想要的确切美团骑手注册页面。
MEITUAN_RIDER_URL = "https://peisong.meituan.com/rider"

# ============ 冲稳保推荐参数 ============
# 以“位次优势” advantage = (院校最低位次 - 考生位次) / 考生位次 划分档位。
# advantage < 0 表示考生位次弱于院校往年录取线（需要冲）。
RUSH_RANGE = (-0.40, 0.00)    # 冲：考生位次比院校录取线差 0~40%（放宽下限，可冲更高的院校）
STABLE_RANGE = (0.00, 0.12)   # 稳：考生位次与录取线持平、略有优势
SAFE_RANGE = (0.12, 0.50)     # 保：考生位次明显优于录取线
PROB_SLOPE = 1.6              # 录取概率估算斜率
