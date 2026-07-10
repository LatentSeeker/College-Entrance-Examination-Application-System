"""本地 Qwen3.5-9B (GGUF) 大模型封装，提供志愿填报顾问能力。

- 懒加载：首次调用时才加载模型（约5GB，加载较慢），之后复用。
- 提供流式接口，便于界面打字机效果输出。
- 参考 D:\\NewCode\\Qwen3.5-9B\\chat.py 的 llama_cpp 用法。
"""
from __future__ import annotations

from typing import Iterator

import config

SYSTEM_PROMPT = (
    "你是一名资深的中国高考志愿填报顾问，熟悉新高考3+1+2政策、平行志愿投档规则、"
    "位次法与『冲稳保』策略。请基于系统提供的真实录取数据和考生情况，给出专业、"
    "客观、可执行的建议。要求：\n"
    "1. 建议要结合考生分数、位次、选科和兴趣，避免空泛套话；\n"
    "2. 解释清楚冲/稳/保的逻辑，提醒平行志愿的梯度和服从调剂风险；\n"
    "3. 录取概率为系统启发式估算，须提醒考生以官方数据和当年招生计划为准；\n"
    "4. 推荐院校时只能从系统提供的候选院校专业组中选择，不要编造系统未给出的"
    "院校名称、投档分或位次；如要补充一般性经验建议，请明确说明这是经验参考、需考生自行核实；\n"
    "5. 回答使用简洁中文，条理清晰，可用要点列举。"
)


class LLMAdvisor:
    """对 llama_cpp.Llama 的轻量封装（单例式懒加载）。"""

    _instance: "LLMAdvisor | None" = None

    def __init__(self) -> None:
        self._llm = None

    @classmethod
    def instance(cls) -> "LLMAdvisor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def loaded(self) -> bool:
        return self._llm is not None

    def load(self) -> None:
        if self._llm is not None:
            return
        from llama_cpp import Llama  # 延迟导入，避免无模型环境报错

        self._llm = Llama(
            model_path=config.MODEL_PATH,
            n_gpu_layers=config.N_GPU_LAYERS,
            n_ctx=config.N_CTX,
            n_batch=config.N_BATCH,
            verbose=False,
        )

    def _build_messages(
        self, user_content: str, history: list[dict] | None = None
    ) -> list[dict]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            # 只保留最近若干条，避免多轮对话累积超出 n_ctx
            messages.extend(history[-config.LLM_MAX_HISTORY_MSGS:])
        messages.append({"role": "user", "content": user_content})
        return messages

    def stream(
        self, user_content: str, history: list[dict] | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[str]:
        """流式生成，逐段 yield 文本。max_tokens 不传则用 config 默认。"""
        self.load()
        messages = self._build_messages(user_content, history)
        stream = self._llm.create_chat_completion(
            messages=messages,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=max_tokens or config.LLM_MAX_TOKENS,
            stream=True,
        )
        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            if "content" in delta:
                yield delta["content"]

    def complete(self, user_content: str, history: list[dict] | None = None,
                 max_tokens: int | None = None) -> str:
        return "".join(self.stream(user_content, history, max_tokens))


def build_advice_prompt(profile_summary: str) -> str:
    """把推荐结果摘要包装成『请分析并给出填报方案』的提示。"""
    return (
        f"{profile_summary}\n\n"
        "请基于以上信息，为该考生：\n"
        "1. 点评整体形势（位次处于什么水平、可冲击的层次）；\n"
        "2. 从冲/稳/保各档中挑选并说明理由，给出一个合理的志愿梯度建议；\n"
        "3. 提示选科匹配、专业方向和服从调剂等注意事项。"
    )


def build_wishlist_prompt(profile_summary: str, n_chong: int, n_wen: int, n_bao: int) -> str:
    """让模型基于候选直接排一份带顺序和理由的志愿表草案。"""
    total = n_chong + n_wen + n_bao
    return (
        f"{profile_summary}\n\n"
        f"请基于以上候选，为该考生排一份共 {total} 个院校专业组的志愿表草案"
        f"（约 {n_chong} 冲 / {n_wen} 稳 / {n_bao} 保）。要求：\n"
        "1. 按『冲在前、保在后』的梯度顺序逐条编号列出（院校+专业组）；\n"
        "2. 只能从上面给出的候选里选，绝不编造候选之外的院校/专业组；\n"
        "3. 每条给一句简短理由（位次匹配度/调剂风险/城市或专业特点）；\n"
        "4. 末尾用一两句提示服从调剂与梯度风险。"
    )
