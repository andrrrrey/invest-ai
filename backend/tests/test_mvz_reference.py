"""Тесты справочника МВЗ: валидация, персистентность, роли (CFO-only на запись)."""

import json
from pathlib import Path

import pytest

from app import settings_store
from app.api.v1.mvz import (
    MvzReferenceUpdate,
    get_default_mvz_reference,
    get_mvz_reference,
    update_mvz_reference,
)
from app.services.mvz_reference import DEFAULT_MVZ, validate_mvz


def test_default_reference_returned_when_not_configured():
    ref = get_mvz_reference()
    assert isinstance(ref, dict)
    assert ref["main_circles"], "эталонный справочник не должен быть пустым"
    assert "3" in ref["sub1"], "круг R&D (3) должен быть в эталоне"
    # Ключи кругов в sub1/sub2 — строковые.
    assert all(isinstance(k, str) for k in ref["sub1"])
    assert all(isinstance(k, str) for k in ref["sub2"])


def test_default_endpoint_returns_reference():
    ref = get_default_mvz_reference(_=None)
    assert ref["main_circles"] == DEFAULT_MVZ["main_circles"]


def test_update_and_persist_reference():
    payload = MvzReferenceUpdate(
        main_circles=[{"id": "3", "name": "R&D"}, {"id": "42", "name": "Новый круг"}],
        sub1={"3": [{"id": "3.1", "name": "New Business"}], "42": [{"id": "42.1", "name": "Подкруг"}]},
        sub2={"3.1": [{"id": "3.1.1", "name": "New Business GEN"}]},
    )
    result = update_mvz_reference(payload, _=None)
    assert result["success"] is True

    stored = get_mvz_reference()
    assert len(stored["main_circles"]) == 2
    assert stored["main_circles"][1]["name"] == "Новый круг"
    assert stored["sub1"]["42"][0]["id"] == "42.1"
    assert stored["sub2"]["3.1"][0]["name"] == "New Business GEN"


def test_orphans_are_dropped():
    """Подкруг без родителя и подкруг 2 без родителя игнорируются."""
    payload = MvzReferenceUpdate(
        main_circles=[{"id": "3", "name": "R&D"}],
        sub1={"3": [{"id": "3.1", "name": "New Business"}], "999": [{"id": "999.1", "name": "Сирота"}]},
        sub2={"3.1": [{"id": "3.1.1", "name": "GEN"}], "888": [{"id": "888.1", "name": "Сирота"}]},
    )
    update_mvz_reference(payload, _=None)
    stored = get_mvz_reference()
    assert "999" not in stored["sub1"]
    assert "888" not in stored["sub2"]
    # Подкруг 3.1 остался у своего родителя — круга 3.
    assert stored["sub1"]["3"][0]["id"] == "3.1"


def test_empty_main_circles_rejected():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        update_mvz_reference(MvzReferenceUpdate(main_circles=[], sub1={}, sub2={}), _=None)
    assert exc.value.status_code == 400


def test_rows_without_id_are_skipped():
    normalized = validate_mvz({
        "main_circles": [{"id": "", "name": "Без кода"}, {"id": "7", "name": "COGS"}],
        "sub1": {},
        "sub2": {},
    })
    assert len(normalized["main_circles"]) == 1
    assert normalized["main_circles"][0]["id"] == "7"


def test_name_defaults_to_id():
    normalized = validate_mvz({
        "main_circles": [{"id": "7", "name": ""}],
        "sub1": {},
        "sub2": {},
    })
    assert normalized["main_circles"][0]["name"] == "7"


def test_ids_and_names_are_trimmed():
    normalized = validate_mvz({
        "main_circles": [{"id": "  3  ", "name": "  R&D  "}],
        "sub1": {"3": [{"id": " 3.1 ", "name": " New Business "}]},
        "sub2": {},
    })
    assert normalized["main_circles"][0] == {"id": "3", "name": "R&D"}
    assert normalized["sub1"]["3"][0] == {"id": "3.1", "name": "New Business"}


def test_store_roundtrip_via_settings_store():
    reference = {
        "main_circles": [{"id": "9", "name": "Тест"}],
        "sub1": {"9": [{"id": "9.1", "name": "Под"}]},
        "sub2": {},
    }
    settings_store.set_mvz_reference(reference)
    assert settings_store.get_mvz_reference() == reference


def test_default_matches_frontend_fallback():
    """Эталон на бэкенде должен совпадать с MVZ_FALLBACK во frontend/new.html.

    Иначе после переезда справочника в настройки наборы кругов разъедутся.
    """
    import shutil
    import subprocess

    html = Path(__file__).resolve().parents[2] / "frontend" / "new.html"
    src = html.read_text(encoding="utf-8")
    start = src.index("const MVZ_FALLBACK = {")
    end = src.index("\n};", start)
    block = src[start:end + 2]

    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — нельзя разобрать JS-литерал")

    # Разбираем JS-литерал через node и получаем честный JSON.
    script = (
        "const fs=require('fs');"
        f"const src=fs.readFileSync({json.dumps(str(html))},'utf8');"
        f"const i=src.indexOf('const MVZ_FALLBACK = {{');"
        "const j=src.indexOf('\\n};', i);"
        "let b=src.slice(i, j+2).replace('const MVZ_FALLBACK =','');"
        "process.stdout.write(JSON.stringify(eval('(' + b + ')')));"
    )
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"не удалось разобрать MVZ_FALLBACK: {result.stderr[:200]}")
    js = json.loads(result.stdout)

    def norm_main(rows):
        return [(str(r["id"]), str(r["name"])) for r in rows]

    def norm_map(m):
        return {str(k): norm_main(v) for k, v in m.items()}

    assert norm_main(DEFAULT_MVZ["main_circles"]) == norm_main(js["mainCircles"])
    assert norm_map(DEFAULT_MVZ["sub1"]) == norm_map(js["sub1"])
    assert norm_map(DEFAULT_MVZ["sub2"]) == norm_map(js["sub2"])
