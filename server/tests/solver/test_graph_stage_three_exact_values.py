"""Algebraic extrema survive checkpoints without evaluating expression text."""

import json

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)
from shuxueshuo_server.graph_lesson.stage_three.verification import _set_mismatch


@pytest.mark.parametrize("degree", [3, 5])
def test_algebraic_root_endpoint_round_trips_through_json(degree):
    a = sp.Symbol("a")
    root = sp.CRootOf(a**degree-a-1, 0)
    original = sp.Interval(root, sp.oo)
    decoded = decode_value(json.loads(json.dumps(encode_value(original))))
    assert _set_mismatch(original, decoded) is None
    assert sp.minpoly(decoded.start, a) == sp.minpoly(root, a)


@pytest.mark.parametrize("payload", [
    {"coefficients": [], "index": 0},
    {"coefficients": [1, 0, -1], "index": 0},
    {"coefficients": [{"$math": "Integer", "value": "1"}, {"$math": "Integer", "value": "0"}], "index": True},
    {"coefficients": [{"$math": "Integer", "value": "1"}, {"$math": "Integer", "value": "0"}], "index": 1},
    {"coefficients": [{"$math": "Integer", "value": "0"}, {"$math": "Integer", "value": "1"}], "index": 0},
])
def test_algebraic_root_decoder_rejects_invalid_polynomial_or_index(payload):
    with pytest.raises(ValueError, match="checkpoint.invalid_algebraic"):
        decode_value({"$math": "CRootOf", **payload})


def test_algebraic_root_decoder_never_accepts_expression_source():
    with pytest.raises(ValueError, match="unknown_math_type"):
        decode_value({"$math": "CRootOf", "index": 0, "coefficients": [
            {"$math": "sympify", "args": ["__import__('os')"]},
            {"$math": "Integer", "value": "1"},
        ]})
