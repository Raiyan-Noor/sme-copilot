"""Merkle root and proof generation and verification (invariant 9), including odd leaf counts."""

import hashlib

import pytest

from app.anchoring.merkle import ProofStep, build, leaf_hash, node_hash, root_from_proof, verify_proof


def leaves(n: int) -> list[str]:
    return [leaf_hash("mandate", hashlib.sha256(str(i).encode()).hexdigest()) for i in range(n)]


def test_leaf_and_node_hashes_are_domain_separated():
    value = "ab" * 32
    assert leaf_hash("passport", value) == hashlib.sha256(b"\x00" + f"passport:{value}".encode()).hexdigest()
    assert leaf_hash("passport", value) != leaf_hash("mandate", value)  # the kind is bound into the leaf
    left, right = "11" * 32, "22" * 32
    assert node_hash(left, right) == hashlib.sha256(b"\x01" + bytes.fromhex(left + right)).hexdigest()
    assert node_hash(left, right) != node_hash(right, left)  # index-based: order matters


def test_three_leaves_by_hand():
    a, b, c = leaves(3)
    root, proofs = build([a, b, c])
    assert root == node_hash(node_hash(a, b), c)  # odd last leaf promoted unchanged
    assert proofs[0] == [ProofStep(side="right", hash=b), ProofStep(side="right", hash=c)]
    assert proofs[1] == [ProofStep(side="left", hash=a), ProofStep(side="right", hash=c)]
    assert proofs[2] == [ProofStep(side="left", hash=node_hash(a, b))]


def test_single_leaf_is_its_own_root_with_an_empty_proof():
    (a,) = leaves(1)
    root, proofs = build([a])
    assert root == a and proofs == [[]]
    assert verify_proof(a, [], root)


def test_empty_batch_is_refused():
    with pytest.raises(ValueError):
        build([])


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8, 9, 13, 16, 17])
def test_every_proof_verifies_for_even_and_odd_counts(n):
    ls = leaves(n)
    root, proofs = build(ls)
    assert len(proofs) == n
    for leaf, proof in zip(ls, proofs):
        assert verify_proof(leaf, proof, root)
        assert len(proof) <= (n - 1).bit_length()


@pytest.mark.parametrize("n", [2, 3, 5, 8])
def test_a_proof_does_not_verify_a_different_leaf_or_root(n):
    ls = leaves(n)
    root, proofs = build(ls)
    other = leaf_hash("mandate", "ff" * 32)
    assert not verify_proof(other, proofs[0], root)
    assert not verify_proof(ls[0], proofs[0], "00" * 32)
    if n > 1:
        assert not verify_proof(ls[0], proofs[1], root)
        flipped = [ProofStep(side="left" if s.side == "right" else "right", hash=s.hash) for s in proofs[0]]
        assert not verify_proof(ls[0], flipped, root)


def test_odd_leaf_is_not_duplicated():
    """Duplicating the last node would give [a, b, c] and [a, b, c, c] the same root (CVE-2012-2459)."""
    a, b, c = leaves(3)
    assert build([a, b, c])[0] != build([a, b, c, c])[0]
    assert build([a, b, c])[0] != node_hash(node_hash(a, b), node_hash(c, c))


def test_changing_one_leaf_changes_the_root():
    ls = leaves(5)
    root = build(ls)[0]
    for i in range(5):
        changed = list(ls)
        changed[i] = leaf_hash("mandate", "ee" * 32)
        assert build(changed)[0] != root
        assert root_from_proof(changed[i], build(ls)[1][i]) != root
