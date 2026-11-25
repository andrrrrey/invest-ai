"""Тесты разбора и нормализации Risk Score (проблема с сырым JSON в интерфейсе).

Регрессия: при неудачном ``json.loads`` ответ модели целиком попадал в поле
``commentary``, и в блоке «Общий уровень риска» пользователь видел сырой JSON
вместо текста.
"""

from app.services.ai_service import (
    _loads_lenient,
    _normalize_risk_score,
    _safe_commentary,
)


def test_strict_json_is_parsed():
    data = _loads_lenient('{"overall_risk": "умеренный"}')
    assert data == {"overall_risk": "умеренный"}


def test_json_with_trailing_comma():
    data = _loads_lenient('{"a": 1, "b": 2,}')
    assert data == {"a": 1, "b": 2}


def test_json_with_unquoted_keys_and_python_literals():
    data = _loads_lenient("{a: 1, b: None, c: True, d: False}")
    assert data == {"a": 1, "b": None, "c": True, "d": False}


def test_json_with_single_quotes():
    data = _loads_lenient("{'a': 'x', 'b': 'y'}")
    assert data == {"a": "x", "b": "y"}


def test_truncated_json_is_recovered():
    text = '{"overall_risk": "высокий", "risk_scores": {"execution_risk": 4'
    data = _loads_lenient(text)
    assert data is not None
    assert data["overall_risk"] == "высокий"


def test_json_with_trailing_prose():
    data = _loads_lenient('{"a": 1}\n\nВот и результат анализа.')
    assert data == {"a": 1}


def test_apostrophe_inside_value_is_not_corrupted():
    """Апостроф внутри значения не должен ломать разбор."""
    data = _loads_lenient('{"commentary": "Компания O\'Brien риск", "x": 1,}')
    assert data == {"commentary": "Компания O'Brien риск", "x": 1}


def test_garbage_returns_none():
    assert _loads_lenient("совсем не JSON") is None
    assert _loads_lenient("") is None
    assert _loads_lenient("[1, 2, 3]") is None  # не объект


def test_safe_commentary_never_returns_raw_json():
    raw = '{"overall_risk": "умеренный", "risk_scores": {"execution_risk": 3}}'
    text = _safe_commentary(raw)
    assert not text.strip().startswith("{")
    assert "overall_risk" not in text


def test_safe_commentary_fallback_for_empty():
    assert _safe_commentary("") == "AI недоступен"


def test_safe_commentary_truncates_long_text():
    text = _safe_commentary("а" * 1000)
    assert len(text) <= 301


def test_normalize_fills_missing_scores():
    out = _normalize_risk_score({"overall_risk": "высокий"})
    assert out["risk_scores"] == {
        "execution_risk": 3,
        "market_risk": 3,
        "financial_risk": 3,
        "strategic_risk": 3,
    }
    assert out["risk_reasons"] == []
    assert out["controls"] == []
    assert out["stage_gate_recommendations"] == []


def test_normalize_maps_level_aliases():
    assert _normalize_risk_score({"overall_risk": "средний"})["overall_risk"] == "умеренный"
    assert _normalize_risk_score({"overall_risk": "Moderate"})["overall_risk"] == "умеренный"
    assert _normalize_risk_score({"overall_risk": "HIGH"})["overall_risk"] == "высокий"
    assert _normalize_risk_score({"overall_risk": "что-то"})["overall_risk"] == "умеренный"


def test_normalize_clamps_scores():
    out = _normalize_risk_score({
        "risk_scores": {
            "execution_risk": 0,
            "market_risk": 9,
            "financial_risk": "3",
            "strategic_risk": None,
        }
    })
    assert out["risk_scores"]["execution_risk"] == 1
    assert out["risk_scores"]["market_risk"] == 5
    assert out["risk_scores"]["financial_risk"] == 3
    assert out["risk_scores"]["strategic_risk"] == 3


def test_normalize_wraps_string_lists():
    out = _normalize_risk_score({"risk_reasons": "Одна причина", "controls": None})
    assert out["risk_reasons"] == ["Одна причина"]
    assert out["controls"] == []


def test_normalize_invalid_route_falls_back():
    assert _normalize_risk_score({"recommended_route": "manual_review"})["recommended_route"] == "efficiency_play"
    assert _normalize_risk_score({"recommended_route": "fast_track"})["recommended_route"] == "fast_track"


def test_normalize_strips_json_from_commentary():
    out = _normalize_risk_score({
        "overall_risk": "низкий",
        "commentary": '{"overall_risk": "низкий"}',
    })
    assert not out["commentary"].strip().startswith("{")


def test_normalize_keeps_normal_commentary():
    out = _normalize_risk_score({"commentary": "Риски в пределах нормы."})
    assert out["commentary"] == "Риски в пределах нормы."


def test_regression_raw_json_never_reaches_commentary():
    """Регрессия из скриншота: в блоке «Общий уровень риска» показывался сырой
    JSON вместо текста. Такой текст не должен доходить до пользователя."""
    raw = '{"overall_risk": "умеренный", "risk_scores": {"execution_risk": 3}}'
    out = _normalize_risk_score(_loads_lenient(raw) or {})
    assert out["commentary"]
    assert not out["commentary"].strip().startswith("{")
    assert "risk_scores" not in out["commentary"]


def test_regression_truncated_response_still_yields_scores():
    """Обрезанный ответ модели не должен превращаться в сырой JSON в UI."""
    raw = '{"overall_risk": "умеренный", "risk_scores": {"execution_risk": 3, "market_risk": 2'
    parsed = _loads_lenient(raw)
    assert parsed is not None
    out = _normalize_risk_score(parsed)
    assert out["overall_risk"] == "умеренный"
    assert out["risk_scores"]["execution_risk"] == 3
    assert out["risk_scores"]["market_risk"] == 2
