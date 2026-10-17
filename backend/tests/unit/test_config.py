"""Settings: testnet-only anchoring (invariant 9) and secrets kept out of reprs."""

import pytest
from pydantic import ValidationError

from tests.helpers import make_settings


@pytest.mark.parametrize("chain_id", [11155111, 84532])
def test_testnet_chain_ids_accepted(chain_id):
    assert make_settings(anchor_chain_id=chain_id).anchor_chain_id == chain_id


@pytest.mark.parametrize("chain_id", [1, 8453, 137, 10])
def test_mainnet_chain_ids_refused(chain_id):
    with pytest.raises(ValidationError):
        make_settings(anchor_chain_id=chain_id)


def test_secrets_not_in_repr():
    s = make_settings(anchor_private_key="0xdeadbeef", openai_api_key="sk-secret")
    assert "deadbeef" not in repr(s)
    assert "sk-secret" not in repr(s)


def test_origins_split():
    assert make_settings(allowed_origins="http://a, http://b ,").origins == ["http://a", "http://b"]
