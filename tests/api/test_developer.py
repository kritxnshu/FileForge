"""Server-side data conversion: matrix with independent parsers + XXE / alias-bomb negatives."""

from __future__ import annotations

import csv
import json
import tomllib

import pytest
import yaml
from conftest import convert, pairs_of
from defusedxml import ElementTree as DET

from engine.converters.developer.data import xml_to_obj

SAMPLE = {"config": {"name": "Ünïcode app", "version": 3, "enabled": True, "ratio": 0.5, "tags": ["a", "b"],
                     "owner": {"id": 7}}}
RECORDS = [{"name": "Apple", "qty": "3"}, {"name": "=HYPERLINK(1)", "qty": "12"}]


def write(tmp_path, fmt: str, obj) -> object:
    p = tmp_path / f"in.{fmt}"
    if fmt == "json":
        p.write_text(json.dumps(obj))
    elif fmt == "yaml":
        p.write_text(yaml.safe_dump(obj, allow_unicode=True))
    elif fmt == "toml":
        import tomli_w

        p.write_text(tomli_w.dumps(obj))
    elif fmt == "xml":
        p.write_text('<?xml version="1.0"?><config><name>Ünïcode app</name><version>3</version><enabled>true</enabled>'
                     "<ratio>0.5</ratio><tags>a</tags><tags>b</tags><owner><id>7</id></owner></config>")
    elif fmt in ("csv", "tsv"):
        d = "\t" if fmt == "tsv" else ","
        p.write_text(f"name{d}qty\nApple{d}3\n=HYPERLINK(1){d}12\n")
    return p


def read(path, fmt):
    text = path.read_text(encoding="utf-8")
    if fmt == "json":
        return json.loads(text)
    if fmt == "yaml":
        return yaml.safe_load(text)
    if fmt == "toml":
        return tomllib.loads(text)
    if fmt == "xml":
        DET.fromstring(text.encode())  # independent, hardened parse
        return xml_to_obj(text)
    return list(csv.DictReader(text.splitlines(), delimiter="\t" if fmt == "tsv" else ","))


def strs(v):
    if isinstance(v, dict):
        return {k: strs(x) for k, x in v.items()}
    if isinstance(v, list):
        return [strs(x) for x in v]
    return str(v).lower() if isinstance(v, bool) else str(v)


@pytest.mark.parametrize("src,dst", pairs_of("data.convert"))
def test_data_convert_matrix(tmp_path, src, dst):
    tabular = src in ("csv", "tsv") or dst in ("csv", "tsv")
    inp = write(tmp_path, src, RECORDS if src == "json" and tabular else SAMPLE)
    r = convert("data.convert", inp, dst, formats=[src])
    assert r.ok, r.error
    got = read(r.out, dst)
    if dst in ("csv", "tsv"):
        assert got[0] == {"name": "Apple", "qty": "3"}
        assert got[1]["name"] == "'=HYPERLINK(1)"  # formula injection neutralized
    elif src in ("csv", "tsv"):
        assert got == RECORDS or got == {"items": RECORDS} or strs(got) == strs({"root": {"item": RECORDS}})
    elif "xml" in (src, dst):
        assert strs(got) == strs(SAMPLE)
    else:
        assert got == SAMPLE


@pytest.mark.verifies("data.convert:json->xml")
def test_json_to_xml_mapping(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"root": {"@id": "1", "#text": "hi", "child": [{"@k": "v"}, "x"]}}))
    r = convert("data.convert", p, "xml", formats=["json"])
    root = DET.fromstring(r.out.read_bytes())
    assert root.tag == "root" and root.get("id") == "1" and root.text.strip() == "hi"
    assert [c.get("k") for c in root.findall("child")] == ["v", None]


@pytest.mark.verifies("neg:data.convert")
def test_xxe_blocked(tmp_path):
    from test_security import Canary

    c = Canary()
    try:
        p = tmp_path / "x.xml"
        p.write_text(f'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">'
                     f'<!ENTITY h SYSTEM "{c.url}/xxe">]><r>&e;&h;</r>')
        r = convert("data.convert", p, "json", formats=["xml"])
        assert not r.ok and r.error["code"] == "unsafe_input"
        assert c.hits == []
    finally:
        c.close()


@pytest.mark.verifies("neg:data.convert")
def test_billion_laughs_xml_blocked(tmp_path):
    ents = "".join(f'<!ENTITY l{i} "{"&l" + str(i - 1) + ";" * 1 if i else "lol"}{("&l" + str(i - 1) + ";") * 9 if i else "lol" * 9}">' for i in range(10))
    p = tmp_path / "b.xml"
    p.write_text(f'<?xml version="1.0"?><!DOCTYPE lolz [{ents}]><lolz>&l9;</lolz>')
    r = convert("data.convert", p, "json", formats=["xml"])
    assert not r.ok and r.error["code"] == "unsafe_input"


@pytest.mark.verifies("neg:data.convert")
def test_yaml_alias_bomb_blocked(tmp_path):
    lines = ['a: &a ["lol","lol","lol","lol","lol","lol","lol","lol","lol"]']
    prev = "a"
    for name in "bcdefghi":
        lines.append(f"{name}: &{name} [" + ",".join([f"*{prev}"] * 9) + "]")
        prev = name
    p = tmp_path / "bomb.yaml"
    p.write_text("\n".join(lines))
    r = convert("data.convert", p, "json", formats=["yaml"], timeout=30)
    assert not r.ok and r.error["code"] == "too_large"


@pytest.mark.verifies("neg:data.convert")
def test_invalid_json_reports_position(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"a": 1,\n "b": }')
    r = convert("data.convert", p, "yaml", formats=["json"])
    assert not r.ok and "line 2, column 7" in r.error["message"]


@pytest.mark.parametrize("src,dst", pairs_of("data.csv_to_sql"))
def test_csv_to_sql(tmp_path, src, dst):
    import sqlite3

    d = "\t" if src == "tsv" else ","
    p = tmp_path / f"t.{src}"
    p.write_text(f"id{d}name{d}price\n1{d}O'Brien{d}1.5\n2{d}{d}3\n")
    r = convert("data.csv_to_sql", p, "sql", {"table": "people", "dialect": "sqlite"}, formats=[src])
    assert r.ok, r.error
    db = sqlite3.connect(":memory:")
    db.executescript(r.out.read_text())  # independent check: a real database accepts it
    assert db.execute("select id, name, price from people order by id").fetchall() == [(1, "O'Brien", 1.5), (2, None, 3)]


@pytest.mark.verifies("neg:data.csv_to_sql")
def test_csv_to_sql_rejects_injection_in_table_name():
    from engine.registry import get

    with pytest.raises(ValueError):
        get("data.csv_to_sql").options.model_validate({"table": "x; DROP TABLE y"})
