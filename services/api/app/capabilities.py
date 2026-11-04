"""Builds /api/capabilities from the registry + verification results."""

from __future__ import annotations

import time
from typing import Any

from engine import registry
from engine.formats import FORMATS

from .config import settings

_cache: tuple[float, dict, dict] | None = None


def _slug(op: registry.Operation, src: str, dst: str) -> str:
    if op.cardinality == "transform" or (op.slug and (src == dst or op.cardinality == "many_to_one")):
        base = op.slug or op.id.replace(".", "-")
        return f"{base}-{src}" if len({s for s, _ in op.pairs()}) > 1 else base
    return f"{src}-to-{dst}"


def _hubs(index: dict[tuple[str, str, str], registry.PairInfo]) -> dict[str, Any]:
    """Curated sections (engine/hubs.py), keeping only tools whose operation is advertised right now."""
    from engine.hubs import HUBS

    out: dict[str, Any] = {}
    for hub in HUBS:
        tools = []
        for t in hub.tools:
            pairs = [k for k in index if k[0] == t.op and (t.target is None or k[2] == t.target)
                     and (t.sources is None or k[1] in t.sources)]
            if not pairs:
                continue
            levels = {index[k].level for k in pairs}
            op = registry.get(t.op)
            tools.append({
                "slug": t.slug, "title": t.title, "description": t.description, "icon": t.icon, "group": t.group,
                "op": t.op, "target": t.target or pairs[0][2], "sources": sorted({k[1] for k in pairs}),
                "support": next(lv for lv in ("experimental", "partial", "full") if lv in levels),
                "limitations": list(op.limitations) if op else [], "options": t.options, "special": t.special,
                "cardinality": op.cardinality if op else "transform",
            })
        used = {t["group"] for t in tools}
        out[hub.id] = {
            "title": hub.title, "description": hub.description,
            "groups": [{"id": g, "label": label} for g, label in hub.groups if g in used],
            "tools": tools,
            "not_offered": [{"title": a, "reason": b} for a, b in hub.not_offered],
        }
    return out


def build() -> tuple[dict[str, Any], dict[tuple[str, str, str], registry.PairInfo]]:
    """Returns (public capabilities document, advertised pair index)."""
    global _cache
    if _cache and time.monotonic() - _cache[0] < 30:
        return _cache[1], _cache[2]
    infos = registry.pair_infos()
    index: dict[tuple[str, str, str], registry.PairInfo] = {}
    ops_out = []
    seen_slugs: set[tuple[str, str]] = set()
    for op in registry.all_ops():
        pairs = []
        for p in (i for i in infos if i.op is op):
            if not p.advertised:
                continue
            index[(op.id, p.src, p.dst)] = p
            slug = _slug(op, p.src, p.dst)
            primary = (op.runtime, slug) not in seen_slugs  # /convert/<slug> (server) and /tools/<slug> (client)
            seen_slugs.add((op.runtime, slug))
            pairs.append({
                "source": p.src,
                "target": p.dst,
                "support": p.level,
                "limitations": list(op.limitations) + list(op.pair_limitations.get((p.src, p.dst), ())),
                "slug": slug,
                "primary": primary,
            })
        if not pairs:
            continue
        ops_out.append({
            "id": op.id,
            "category": op.category,
            "label": op.label,
            "description": op.description,
            "cardinality": op.cardinality,
            "runtime": op.runtime,
            "resource_class": op.resource_class,
            "support": op.support,
            "limitations": list(op.limitations),
            "options_schema": op.options.model_json_schema(),
            "min_inputs": op.min_inputs,
            "combine_only": op.combine_only,
            "max_inputs": op.max_inputs,
            "keywords": list(op.keywords),
            "pairs": pairs,
        })
    used = {f for o in ops_out for p in o["pairs"] for f in (p["source"], p["target"])}
    hubs_out = _hubs(index)
    doc = {
        "version": 1,
        "categories": [{"id": c, "label": label} for c, label in registry.CATEGORIES],
        "formats": {fid: {"label": f.label, "family": f.family, "exts": list(f.exts), "mime": f.mime}
                    for fid, f in FORMATS.items() if fid in used},
        "operations": ops_out,
        "hubs": hubs_out,
        "limits": settings().limits_public(),
    }
    _cache = (time.monotonic(), doc, index)
    return doc, index


def hidden_pairs() -> list[dict[str, Any]]:
    return [{"operation": p.op.id, "source": p.src, "target": p.dst, "support": p.level, "reason": p.reason}
            for p in registry.pair_infos() if not p.advertised]


def reset_cache() -> None:
    global _cache
    _cache = None
