"""有限的公司身份候选；不提供行情/财务数据，不自动改写原字幕。"""

# 身份与代码于2026-10-01核对公司官方页面。扩充时需附来源；不能只靠发音匹配。
CATALOG = (
    {'name': '中国民航信息网络', 'code': '00696', 'market': '香港',
     'aliases': ('中国民航信息网络', '中国航信', '航信'), 'asr_candidates': ('韩信', '行信', '航线'),
     'description': '航空旅游业信息技术解决方案供应商，不能称为航空公司或机场经营公司',
     'source_url': 'https://www.travelskyir.com/c/index.php'},
    {'name': '保利物业', 'code': '06049', 'market': '香港',
     'aliases': ('保利物业',), 'asr_candidates': ('宝利维', '保利维'),
     'description': '物业服务公司，与保利发展不是同一上市主体',
     'source_url': 'https://www.polywuye.com/City/index'},
    {'name': '海吉亚医疗', 'code': '06078', 'market': '香港',
     'aliases': ('海吉亚医疗', '海吉亚'), 'asr_candidates': ('海基',),
     'description': '医疗服务公司',
     'source_url': 'https://www.hygeia-global.com/hygeia.html'},
)


def entity_candidates(text):
    result = []
    for company in CATALOG:
        exact = [term for term in company['aliases'] if term in text]
        fuzzy = [term for term in company['asr_candidates'] if term in text]
        if exact or fuzzy:
            result.append({k: v for k, v in company.items() if k not in ('aliases', 'asr_candidates')} |
                          {'matched_terms': exact + fuzzy,
                           'status': 'explicit_name' if exact else 'candidate',
                           'checked_at': '2026-10-01'})
    return result
