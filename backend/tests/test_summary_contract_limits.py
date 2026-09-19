from app.ai_deepseek import _limit_summary_collections


def test_summary_contract_limits_model_lists_and_mindmap_children():
    payload = {
        "outline": list(range(18)),
        "key_points": list(range(21)),
        "keywords": list(range(23)),
        "mindmap": {"title": "root", "children": [{"title": str(index), "children": []} for index in range(14)]},
    }

    limited = _limit_summary_collections(payload)

    assert len(limited["outline"]) == 16
    assert len(limited["key_points"]) == 20
    assert len(limited["keywords"]) == 20
    assert len(limited["mindmap"]["children"]) == 12
