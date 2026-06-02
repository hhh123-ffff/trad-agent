from __future__ import annotations

import re

from .models import ComplianceCheck

BLOCKED_PATTERNS = {
    "buy_sell": r"(买入|卖出|持有|加仓|减仓|清仓|满仓|梭哈|可以买|能不能买|该不该买|能买吗)",
    "target_price": r"(目标价|看到\s*\d+|涨到\s*\d+|跌到\s*\d+)",
    "guarantee": r"(必涨|必跌|稳赚|保证收益|无风险|翻倍)",
    "recommendation": r"(推荐.*股票|荐股|牛股|明牌|抄底|逃顶)",
    "position": r"(仓位|几成仓|多少仓|重仓|轻仓)",
}


def check_text(text: str) -> ComplianceCheck:
    blocked_terms: list[str] = []
    for label, pattern in BLOCKED_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            blocked_terms.append(label)

    allowed = not blocked_terms
    rewritten_guidance = (
        "可以改问：这个标的今天有哪些已证实事件、量价变化和风险提示？"
        if blocked_terms
        else "文本未触发投顾边界，可继续输出事实、引用和风险提示。"
    )
    return ComplianceCheck(text=text, allowed=allowed, blocked_terms=blocked_terms, rewritten_guidance=rewritten_guidance)


def blocked_answer(text: str) -> str:
    return (
        "这个问题涉及买卖、仓位、目标价或收益判断，我不能提供证券投资建议。"
        "可以帮你整理已入库信息：相关股票今天的公告、新闻、量价变化、资金异动和风险点。"
    )


def ensure_compliant_answer(answer: str) -> str:
    result = check_text(answer)
    if result.allowed:
        return answer
    return (
        "合规拦截：原始回答可能包含投顾式表达，已改写为信息整理口径。"
        "请基于来源自行判断风险，产品不提供买卖建议、目标价或仓位建议。"
    )
