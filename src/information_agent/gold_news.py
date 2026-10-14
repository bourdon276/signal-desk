"""Fixed gold and US macro vocabulary shared by discovery and classification."""

import re

US_CONTEXT = r"美国|美國|\b(?:USA|United States|BLS)\b|(?-i:\bUS\b)|(?<!\w)U\.S\.(?!\w)"
INFLATION = (r"消费者物价|消费者价格|消費者物價|核心\s*CPI|"
             r"\b(?:CPI|PPI|PCE|inflation|consumer price index|producer price index)\b|通胀|通膨")
EMPLOYMENT = (r"非农|非農|失业率|失業率|初请失业|初請失業|"
              r"\b(?:payrolls?|unemployment|jobless|JOLTS|employment situation)\b")
GOLD_CONTEXT = r"伦敦金|现货黄金|国际黄金|金价|\b(?:gold|bullion|xau/?usd)\b"


def macro_reason(text: str) -> str | None:
    if re.search(r"美联储|美聯儲|鲍威尔|鮑威爾|\b(?:Federal Reserve|Fed|FOMC|Powell)\b", text, re.I):
        return "美联储政策"
    if re.search(US_CONTEXT, text, re.I):
        if re.search(INFLATION, text, re.I):
            return "美国通胀数据"
        if re.search(EMPLOYMENT, text, re.I):
            return "美国就业数据"
        if re.search(r"\bGDP\b|国内生产总值|零售销售|零售銷售", text, re.I):
            return "美国经济数据"
    if re.search(r"美元指数|美元指數|美债收益率|美債收益率|美国国债|美國國債|"
                 r"\b(?:DXY|dollar index|US Treasury|U\.S\. Treasury|Treasury yields?)\b", text, re.I):
        return "美元与美债"
    return None


def gold_reason(text: str) -> str | None:
    reason = macro_reason(text)
    if reason:
        return reason
    return "黄金市场" if re.search(GOLD_CONTEXT, text, re.I) else None
