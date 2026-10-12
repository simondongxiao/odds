from __future__ import annotations
import re
def parse_score_rows(html):
    # Stable table/text evidence only; markets are not inferred from score rows.
    text=re.sub(r'<[^>]+>',' ',html); text=re.sub(r'\s+',' ',text)
    return [{'source':'leisu','score_feed':True,'raw_context':x[:180]} for x in re.findall(r'2026/\d{2}/\d{2}.{0,140}',text)]
