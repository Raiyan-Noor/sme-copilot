"""SHA-256 Merkle tree over anchoring leaves, with a proof per leaf (invariant 9).

Choice: **index-based** (ordered) hashing with RFC 6962-style domain separation, not sorted-pair hashing.

- Leaf:  `H(0x00 || utf8("<kind>:<hash hex>"))`. The kind (`audit_head`, `mandate`, `passport`) is bound into the
  leaf, so a Passport hash cannot be passed off as a mandate, and a leaf can never be confused with an inner node.
- Node:  `H(0x01 || left || right)`, children in leaf order. Order matters, so a proof records each sibling's side.
- Odd count: at any level with an odd number of nodes, the last node is **promoted unchanged** to the next level.
  It is never paired with a copy of itself: duplicating the last node (as Bitcoin does) lets two different leaf
  lists share a root (CVE-2012-2459), which would undermine "this exact batch was anchored".
- One leaf: the root is the leaf hash and its proof is empty. An empty batch has no root and is refused.

A verifier needs only the leaf (kind + hash), the proof (list of `{side, hash}`) and the anchored root, all of which
are in the anchors record; `verify_proof` is the whole algorithm.
"""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LeafKind = Literal["audit_head", "mandate", "passport"]
HEX64 = r"^[0-9a-f]{64}$"

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


class ProofStep(BaseModel):
    """One sibling on the path to the root. `side` is where the sibling sits: hash(left || right)."""

    model_config = ConfigDict(frozen=True)

    side: Literal["left", "right"]
    hash: str = Field(pattern=HEX64)


def leaf_hash(kind: str, value_hex: str) -> str:
    return hashlib.sha256(LEAF_PREFIX + f"{kind}:{value_hex}".encode()).hexdigest()


def node_hash(left_hex: str, right_hex: str) -> str:
    return hashlib.sha256(NODE_PREFIX + bytes.fromhex(left_hex) + bytes.fromhex(right_hex)).hexdigest()


def build(leaf_hashes: list[str]) -> tuple[str, list[list[ProofStep]]]:
    """Merkle root and one proof per leaf (same order as `leaf_hashes`)."""
    if not leaf_hashes:
        raise ValueError("cannot build a Merkle root over zero leaves")
    proofs: list[list[ProofStep]] = [[] for _ in leaf_hashes]
    # positions[i] = index, in the current level, of the node that leaf i has been folded into
    positions = list(range(len(leaf_hashes)))
    level = list(leaf_hashes)
    while len(level) > 1:
        nxt = [node_hash(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])  # odd node promoted unchanged
        for leaf, pos in enumerate(positions):
            sibling = pos ^ 1
            if sibling < len(level):
                side = "left" if sibling < pos else "right"
                proofs[leaf].append(ProofStep(side=side, hash=level[sibling]))
            positions[leaf] = pos // 2
        level = nxt
    return level[0], proofs


def root_from_proof(leaf_hex: str, proof: list[ProofStep]) -> str:
    acc = leaf_hex
    for step in proof:
        acc = node_hash(step.hash, acc) if step.side == "left" else node_hash(acc, step.hash)
    return acc


def verify_proof(leaf_hex: str, proof: list[ProofStep], root_hex: str) -> bool:
    """True if `proof` folds `leaf_hex` up to exactly `root_hex`."""
    return root_from_proof(leaf_hex, proof) == root_hex
