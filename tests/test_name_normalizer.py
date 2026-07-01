import json
from unittest.mock import MagicMock

from mykg.name_normalizer import (
    apply_normalization_map,
    build_alias_index,
    build_name_inventory,
    build_normalization_file,
    run_name_normalization,
    validate_normalization_output,
)

# ---------------------------------------------------------------------------
# build_name_inventory
# ---------------------------------------------------------------------------


def test_build_name_inventory_groups_by_type():
    raw = {
        "file1.md": {
            "nodes": [
                {"type": "Person", "attributes": {"name": {"value": "Alice", "confidence": 0.9}}},
                {"type": "Person", "attributes": {"name": {"value": "Bob", "confidence": 0.9}}},
                {"type": "Org", "attributes": {"name": {"value": "Acme", "confidence": 0.9}}},
            ],
            "edges": [],
        },
        "file2.md": {
            "nodes": [
                {
                    "type": "Person",
                    "attributes": {"name": {"value": "Alice Smith", "confidence": 0.9}},
                },
                {"type": "Person", "attributes": {"name": {"value": "Alice", "confidence": 0.9}}},
            ],
            "edges": [],
        },
    }
    inv = build_name_inventory(raw)
    assert set(inv["Person"]) == {"Alice", "Bob", "Alice Smith"}
    assert inv["Org"] == ["Acme"]


def test_build_name_inventory_skips_null_names():
    raw = {
        "f.md": {
            "nodes": [
                {"type": "Person", "attributes": {"name": {"value": None, "confidence": 0.0}}},
                {"type": "Person", "attributes": {"name": {"value": "Bob", "confidence": 0.9}}},
            ],
            "edges": [],
        }
    }
    inv = build_name_inventory(raw)
    assert inv["Person"] == ["Bob"]


def test_build_name_inventory_scalar_name():
    raw = {
        "f.md": {
            "nodes": [{"type": "Person", "attributes": {"name": "Alice"}}],
            "edges": [],
        }
    }
    inv = build_name_inventory(raw)
    assert inv["Person"] == ["Alice"]


# ---------------------------------------------------------------------------
# validate_normalization_output
# ---------------------------------------------------------------------------


def _inventory():
    return {"Person": ["Alice Smith", "Alice", "A. Smith", "Bob Johnson", "Bob"]}


def test_validate_accepts_valid_map():
    llm_out = {"Person": {"Alice": "Alice Smith", "A. Smith": "Alice Smith", "Bob": "Bob Johnson"}}
    clean, errors = validate_normalization_output(llm_out, _inventory())
    assert clean == {
        "Person": {"Alice": "Alice Smith", "A. Smith": "Alice Smith", "Bob": "Bob Johnson"}
    }
    assert errors == []


def test_validate_drops_unknown_canonical():
    llm_out = {"Person": {"Alice": "Alice UNKNOWN"}}
    clean, errors = validate_normalization_output(llm_out, _inventory())
    assert "Person" not in clean
    assert any("not in inventory" in e for e in errors)


def test_validate_drops_identity_mapping():
    llm_out = {"Person": {"Alice Smith": "Alice Smith"}}
    clean, errors = validate_normalization_output(llm_out, _inventory())
    assert "Person" not in clean  # identity silently dropped
    assert errors == []


def test_validate_drops_cycle():
    llm_out = {"Person": {"Alice": "Alice Smith", "Alice Smith": "Alice"}}
    clean, errors = validate_normalization_output(llm_out, _inventory())
    # One or both cycle members dropped
    assert any("cycle" in e for e in errors)
    if "Person" in clean:
        assert "Alice Smith" not in clean["Person"] or "Alice" not in clean["Person"]


def test_validate_non_string_entry_dropped():
    llm_out = {"Person": {123: "Alice Smith"}}
    clean, errors = validate_normalization_output(llm_out, _inventory())
    assert "Person" not in clean
    assert errors


def test_validate_non_dict_type_entry_dropped():
    llm_out = {"Person": ["Alice", "Alice Smith"]}
    clean, errors = validate_normalization_output(llm_out, _inventory())
    assert "Person" not in clean
    assert errors


# ---------------------------------------------------------------------------
# apply_normalization_map
# ---------------------------------------------------------------------------


def test_apply_normalization_map_rewrites_name():
    raw = {
        "f.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                },
            ],
            "edges": [],
        }
    }
    norm_map = {"Person": {"Alice": "Alice Smith"}}
    result = apply_normalization_map(raw, norm_map)
    assert result["f.md"]["nodes"][0]["attributes"]["name"]["value"] == "Alice Smith"


def test_apply_normalization_map_case_insensitive():
    raw = {
        "f.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "attributes": {"name": {"value": "alice", "confidence": 0.9}},
                },
            ],
            "edges": [],
        }
    }
    norm_map = {"Person": {"Alice": "Alice Smith"}}
    result = apply_normalization_map(raw, norm_map)
    assert result["f.md"]["nodes"][0]["attributes"]["name"]["value"] == "Alice Smith"


def test_apply_normalization_map_does_not_mutate_input():
    raw = {
        "f.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                },
            ],
            "edges": [],
        }
    }
    norm_map = {"Person": {"Alice": "Alice Smith"}}
    apply_normalization_map(raw, norm_map)
    assert raw["f.md"]["nodes"][0]["attributes"]["name"]["value"] == "Alice"


def test_apply_normalization_map_leaves_node_id_untouched():
    raw = {
        "f.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                },
            ],
            "edges": [],
        }
    }
    norm_map = {"Person": {"Alice": "Alice Smith"}}
    result = apply_normalization_map(raw, norm_map)
    assert result["f.md"]["nodes"][0]["id"] == "person-alice"


# ---------------------------------------------------------------------------
# build_alias_index
# ---------------------------------------------------------------------------


def test_build_alias_index_inverts_correctly():
    norm_map = {"Person": {"Alice": "Alice Smith", "A. Smith": "Alice Smith", "Bob": "Bob Johnson"}}
    idx = build_alias_index(norm_map)
    assert sorted(idx["Person"]["Alice Smith"]) == ["A. Smith", "Alice"]
    assert idx["Person"]["Bob Johnson"] == ["Bob"]


def test_build_alias_index_empty_map():
    assert build_alias_index({}) == {}


# ---------------------------------------------------------------------------
# run_name_normalization
# ---------------------------------------------------------------------------


def test_run_name_normalization_returns_validated_map():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"Person": {"Alice": "Alice Smith"}})
    inventory = {"Person": ["Alice Smith", "Alice", "Bob"]}
    norm_map, errors = run_name_normalization(inventory, adapter)
    assert norm_map == {"Person": {"Alice": "Alice Smith"}}
    assert errors == []


def test_run_name_normalization_json_parse_error():
    adapter = MagicMock()
    adapter.complete.return_value = "not json"
    inventory = {"Person": ["Alice Smith", "Alice"]}
    norm_map, errors = run_name_normalization(inventory, adapter)
    assert norm_map == {}
    assert any("JSON parse error" in e for e in errors)


def test_run_name_normalization_skips_single_name_types():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({})
    inventory = {"Person": ["Alice"]}  # only 1 name — skip
    run_name_normalization(inventory, adapter)
    adapter.complete.assert_not_called()


def test_run_name_normalization_sends_capped_inventory():
    """LLM receives no more names than NORMALIZE_NAMES_MAX_PER_TYPE per type."""
    import mykg.config as cfg

    cap = cfg.NORMALIZE_NAMES_MAX_PER_TYPE
    # Build inventory with more names than the cap
    names = [f"Name{i}" for i in range(cap + 5)]
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({})
    inventory = {"Person": names}
    run_name_normalization(inventory, adapter)
    called_user = json.loads(adapter.complete.call_args[0][1])
    assert len(called_user["Person"]) == cap


# ---------------------------------------------------------------------------
# build_normalization_file
# ---------------------------------------------------------------------------


def test_build_normalization_file_structure():
    norm_map = {"Person": {"Alice": "Alice Smith"}}
    inventory = {"Person": ["Alice Smith", "Alice"]}
    out = build_normalization_file(norm_map, inventory)
    assert "metadata" in out
    assert "mappings" in out
    assert out["mappings"] == norm_map
    assert out["metadata"]["aliases_mapped"] == 1
    assert out["metadata"]["input_name_count_by_type"] == {"Person": 2}


# ---------------------------------------------------------------------------
# run_name_normalization — batching
# ---------------------------------------------------------------------------


def test_single_batch_when_inventory_fits():
    """Small inventory fits in one batch → adapter called exactly once."""
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"Person": {"Alice": "Alice Smith"}})
    inventory = {"Person": ["Alice Smith", "Alice", "Bob"]}
    norm_map, errors = run_name_normalization(inventory, adapter)
    adapter.complete.assert_called_once()
    assert norm_map == {"Person": {"Alice": "Alice Smith"}}
    assert errors == []


def test_batching_splits_on_budget(monkeypatch):
    """When batch_token_target is tiny, each type gets its own batch."""
    import mykg.config as cfg
    monkeypatch.setattr(cfg, "NORMALIZE_NAMES_BATCH_TOKEN_TARGET", 1)  # force one type per batch

    calls = []
    def fake_complete(system, user):
        payload = json.loads(user)
        calls.append(list(payload.keys()))
        return json.dumps({})  # empty result is fine for split test

    adapter = MagicMock()
    adapter.complete.side_effect = fake_complete

    inventory = {
        "Person": ["Alice Smith", "Alice"],
        "Organization": ["Acme Corp", "ACME"],
        "Technology": ["Python", "python"],
    }
    run_name_normalization(inventory, adapter)
    # Each type must be in its own call
    assert adapter.complete.call_count == 3
    type_sets = [set(c) for c in calls]
    assert {"Person"} in type_sets
    assert {"Organization"} in type_sets
    assert {"Technology"} in type_sets


def test_multi_batch_results_merge(monkeypatch):
    """Results from multiple batches are merged into one map."""
    import mykg.config as cfg
    monkeypatch.setattr(cfg, "NORMALIZE_NAMES_BATCH_TOKEN_TARGET", 1)

    responses = [
        json.dumps({"Person": {"Alice": "Alice Smith"}}),
        json.dumps({"Organization": {"ACME": "Acme Corp"}}),
    ]
    adapter = MagicMock()
    adapter.complete.side_effect = responses

    inventory = {
        "Person": ["Alice Smith", "Alice"],
        "Organization": ["Acme Corp", "ACME"],
    }
    norm_map, errors = run_name_normalization(inventory, adapter)
    assert norm_map == {
        "Person": {"Alice": "Alice Smith"},
        "Organization": {"ACME": "Acme Corp"},
    }
    assert errors == []


def test_json_parse_error_in_one_batch_continues(monkeypatch):
    """A JSON parse error in one batch is recorded but other batches still run."""
    import mykg.config as cfg
    monkeypatch.setattr(cfg, "NORMALIZE_NAMES_BATCH_TOKEN_TARGET", 1)

    adapter = MagicMock()
    adapter.complete.side_effect = [
        "not json",  # first batch fails
        json.dumps({"Organization": {"ACME": "Acme Corp"}}),  # second batch succeeds
    ]
    inventory = {
        "Person": ["Alice Smith", "Alice"],
        "Organization": ["Acme Corp", "ACME"],
    }
    norm_map, errors = run_name_normalization(inventory, adapter)
    assert any("JSON parse error" in e for e in errors)
    assert "Organization" in norm_map  # second batch still contributed
