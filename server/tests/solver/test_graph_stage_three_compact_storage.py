"""Version references preserve atomic recovery and immutable legacy publications."""

from copy import deepcopy

import pytest
from jsonschema import ValidationError

from shuxueshuo_server.graph_lesson.stage_three.events import EventStore, math_step_hash
from shuxueshuo_server.graph_lesson.stage_three.revision_manifest import manifest_ref
from tests.solver.test_graph_stage_three_events import (
    IDENTITY,
    TARGET,
    checkpoint,
    fragment,
)


def compact_fragment(ordinal=1):
    value = fragment(ordinal=ordinal)
    value["contract"] = "graph-math-step/v2"
    value["revisions_ref"] = manifest_ref(value.pop("revisions"))
    value["math_step_sha256"] = math_step_hash(value, IDENTITY["revisions"])
    return value


def test_reference_checkpoint_and_card_reopen_with_the_frozen_manifest(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    cp, card = checkpoint(), compact_fragment()
    cp["driver_state"]["revisions_ref"] = card["revisions_ref"]
    result = store.commit_route(cp, commit_id="compact", math_steps=[card])
    assert "revisions" not in cp and "revisions" not in card
    assert result["checkpoint"]["revisions_ref"] == manifest_ref(IDENTITY["revisions"])
    reopened = EventStore(tmp_path, IDENTITY)
    saved = reopened.checkpoint(TARGET, "discriminant")
    assert saved["contract"] == "graph-stage-three-checkpoint/v2"
    assert saved["driver_state"] == cp["driver_state"]
    assert reopened.snapshot()["math_steps"] == [card]
    assert reopened.commit_route(cp, commit_id="compact", math_steps=[card]) == result
    assert len(reopened.events()) == 1


def test_legacy_checkpoint_and_card_survive_mixed_version_publication(tmp_path):
    store = EventStore(tmp_path, IDENTITY, create=True)
    old = checkpoint()
    old["contract"] = "graph-stage-three-checkpoint/v1"
    old.pop("revisions_ref")
    old["revisions"] = deepcopy(IDENTITY["revisions"])
    legacy_card = fragment()
    store.commit_route(old, commit_id="legacy", math_steps=[legacy_card])
    reopened = EventStore(tmp_path, IDENTITY)
    assert reopened.checkpoint(TARGET, "discriminant")["driver_state"] == old["driver_state"]
    new_card = compact_fragment(2)
    reopened.commit_route(checkpoint(position=2), commit_id="compact", math_steps=[new_card])
    assert reopened.snapshot()["math_steps"] == [legacy_card, new_card]
    assert reopened.events()[0]["payload"]["chunk"] == legacy_card
    # Opening and publishing a new card must not rehash or rewrite old content.
    assert reopened.commit_route(old, commit_id="legacy", math_steps=[legacy_card])["checkpoint"]["contract"] == old["contract"]
    assert len(reopened.events()) == 2


@pytest.mark.parametrize("location", ["checkpoint", "state", "trajectory", "card"])
def test_wrong_manifest_reference_rejects_the_whole_commit(tmp_path, location):
    store = EventStore(tmp_path, IDENTITY, create=True)
    cp, card = checkpoint(), compact_fragment()
    if location == "checkpoint":
        cp["revisions_ref"] = "d" * 64
    elif location == "state":
        cp["driver_state"]["revisions_ref"] = "d" * 64
    elif location == "trajectory":
        cp["driver_state"]["trajectory"] = {"revisions_ref": "d" * 64}
    else:
        card["revisions_ref"] = "d" * 64
        card["math_step_sha256"] = math_step_hash(card)
    with pytest.raises(ValueError, match="identity_mismatch"):
        store.commit_route(cp, commit_id="invalid", math_steps=[card])
    assert store.events() == []
    assert store.checkpoint(TARGET, "discriminant") is None
    assert store.snapshot()["math_steps"] == []


@pytest.mark.parametrize("location", ["checkpoint", "card"])
def test_v2_rejects_an_embedded_manifest_even_when_it_matches(tmp_path, location):
    store = EventStore(tmp_path, IDENTITY, create=True)
    cp, card = checkpoint(), compact_fragment()
    carrier = cp if location == "checkpoint" else card
    carrier["revisions"] = deepcopy(IDENTITY["revisions"])
    with pytest.raises((ValueError, ValidationError)):
        store.commit_route(cp, commit_id="redundant", math_steps=[card])
    assert store.events() == []
