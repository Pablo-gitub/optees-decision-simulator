"""Cross-runtime canonicalization parity tests between Python and Node.js."""

import json
import shutil
import subprocess

import pytest

from simulator.domain.canonical import canonicalize_json


def test_node_canonical_parity() -> None:
    node_path = shutil.which("node")
    if not node_path:
        pytest.skip("Node.js is not available on PATH")

    test_objects = [
        {"b": 2, "a": 1, "nested": {"z": 10, "m": 20}},
        {"array": [3, 1, 2], "flag": True, "empty": None, "str": "hello"},
        {"num": 123.456, "zero": 0, "neg": -42},
    ]

    # Node script that implements RFC 8785 canonical key ordering & serialization
    node_script = """
    const readline = require('readline');
    const rl = readline.createInterface({input: process.stdin});
    let inputData = '';
    rl.on('line', line => { inputData += line; });
    rl.on('close', () => {
        const obj = JSON.parse(inputData);
        function canonicalize(val) {
            if (val === null || typeof val !== 'object') {
                return JSON.stringify(val);
            }
            if (Array.isArray(val)) {
                return '[' + val.map(canonicalize).join(',') + ']';
            }
            const keys = Object.keys(val).sort();
            const pairs = keys.map(k => JSON.stringify(k) + ':' + canonicalize(val[k]));
            return '{' + pairs.join(',') + '}';
        }
        process.stdout.write(canonicalize(obj));
    });
    """

    for obj in test_objects:
        py_canonical = canonicalize_json(obj)
        proc = subprocess.run(
            [node_path, "-e", node_script],
            input=json.dumps(obj),
            text=True,
            capture_output=True,
            check=True,
        )
        node_canonical = proc.stdout
        assert py_canonical == node_canonical
