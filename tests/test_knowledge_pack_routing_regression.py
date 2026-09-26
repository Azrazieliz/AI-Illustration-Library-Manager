import json


def test_array_root_json_is_treated_as_knowledge_pack_payload() -> None:
    raw = json.dumps([
        {
            "id": "char:hero",
            "name": "Hero",
            "categories": ["character"],
            "tags": ["hero"],
        }
    ])

    parsed = json.loads(raw)

    assert isinstance(parsed, list)
    assert parsed[0]["name"] == "Hero"
    assert parsed[0]["categories"] == ["character"]
