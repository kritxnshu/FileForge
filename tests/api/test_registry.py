"""Registry rules: earned support levels, engine availability, feature flags, schemas, detection."""

from __future__ import annotations

import pytest
from conftest import TMP
from fixtures.generate import path

from engine import registry
from engine.detect import detect
from engine.formats import FORMATS


def test_every_operation_is_well_formed():
    ops = registry.all_ops()
    assert ops
    for op in ops:
        assert op.category in dict(registry.CATEGORIES)
        assert op.label and op.description
        schema = op.options.model_json_schema()
        assert schema["type"] == "object"
        for f in (*op.inputs, *op.outputs):
            assert f in FORMATS
        if op.runtime == "server":
            assert op.run is not None, f"{op.id} has no converter"
        if op.support == "experimental":
            assert op.feature_flag, f"{op.id} experimental without a flag"


def test_pair_requires_matrix_and_negative_test():
    op = registry.get("image.convert")
    key = op.key("png", "jpg")
    both = {key: {"status": "passed"}, registry.negative_key(op.id): {"status": "passed"}}
    only_pair = {key: {"status": "passed"}}
    failed = {key: {"status": "failed"}, registry.negative_key(op.id): {"status": "passed"}}

    def adv(v):
        return next(p for p in registry.pair_infos(v) if p.op is op and p.src == "png" and p.dst == "jpg")

    assert adv(both).advertised
    assert not adv(only_pair).advertised and "negative" in adv(only_pair).reason
    assert not adv(failed).advertised and "matrix" in adv(failed).reason


def test_missing_engine_disables_pairs(monkeypatch):
    status = dict(registry.engine_status())
    status["pillow-heif"] = None
    monkeypatch.setattr(registry, "engine_status", lambda: status)
    infos = [p for p in registry.pair_infos() if p.op.id == "image.convert"]
    heic = [p for p in infos if p.src == "heic"]
    assert heic and all(not p.available and "pillow-heif" in p.reason for p in heic)
    assert any(p.available for p in infos if p.src == "png")


def test_feature_flag_hides_experimental(monkeypatch):
    exp = [op for op in registry.all_ops() if op.feature_flag]
    if not exp:
        pytest.skip("no flagged operations registered yet")
    op = exp[0]
    monkeypatch.setenv(op.feature_flag, "false")
    assert all(not p.available for p in registry.pair_infos() if p.op is op)


def test_options_schema_carries_ui_hints():
    s = registry.get("image.convert").options.model_json_schema()["properties"]
    assert s["quality"]["x-widget"] == "slider" and "jpg" in s["quality"]["x-targets"]
    assert s["strip_metadata"]["x-advanced"] is True


# --- detection --------------------------------------------------------------


@pytest.mark.parametrize("name,fmt", [
    ("image.png", "png"), ("image.jpg", "jpg"), ("image.webp", "webp"), ("image.gif", "gif"), ("image.bmp", "bmp"),
    ("image.tiff", "tiff"), ("image.ico", "ico"), ("image.avif", "avif"), ("image.heic", "heic"), ("image.svg", "svg"),
])
def test_detect_by_content(name, fmt):
    d = detect(path(name), "upload", probe_dir=TMP)
    assert d.format == fmt and not d.error


def test_detect_mismatch_warns():
    d = detect(path("png-named.jpg"), "photo.jpg", probe_dir=TMP)
    assert d.format == "png" and d.warnings


def test_detect_rejects_unknown_binary():
    d = detect(path("garbage.bin"), "x.bin", probe_dir=TMP)
    assert d.format is None and d.error


@pytest.mark.parametrize("text,ext,fmt", [
    ('{"a": [1, 2]}', "x.txt", "json"),
    ("<root><a>1</a></root>", "data", "xml"),
    ('<svg xmlns="http://www.w3.org/2000/svg"></svg>', "x", "svg"),
    ("<!doctype html><html><body>hi</body></html>", "x", "html"),
    ("name,qty\napple,3\npear,4\n", "x", "csv"),
    ("name\tqty\napple\t3\npear\t4\n", "x", "tsv"),
    ("title: hi\nitems:\n  - a\n", "conf.yaml", "yaml"),
    ('[tool]\nname = "x"\n', "pyproject.toml", "toml"),
    ("# Heading\n\nSome *text*.", "notes.md", "md"),
    ("just words here", "notes", "txt"),
])
def test_detect_text_formats(tmp_path, text, ext, fmt):
    p = tmp_path / "f"
    p.write_text(text)
    assert detect(p, ext, probe_dir=tmp_path).format == fmt
