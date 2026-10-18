"""Testnet access for anchoring: one 0-value self-transaction carrying a Merkle root, and reading it back (invariant 9).

- `Web3Chain` talks to the configured RPC with web3.py. The transaction is `to == from`, `value == 0`, and `data` is
  exactly the 32-byte root: no business data, names, amounts or PII ever leave the server this way.
- `CachedChain` wraps it in the record/replay request cache (namespace `rpc`), so tests and CI replay recorded
  responses and never touch the network. In replay mode nothing can be sent; reads come from recordings only.
- Every path checks the chain ID against the testnet allow-list, including the ID the RPC endpoint reports, so a
  misconfigured mainnet URL is refused before anything is signed.

Errors are raised as `ChainError` with messages written here. Exceptions from web3 are reduced to their class name:
RPC URLs often embed a provider API key, and nothing that could contain it may reach the audit log.
"""

from typing import Protocol

from pydantic import BaseModel

from app.config import ANCHOR_CHAIN_ALLOWLIST
from app.llm.cache import RequestCache

NAMESPACE = "rpc"


class ChainError(RuntimeError):
    """The chain could not be reached or refused the request. The batch stays queued."""


class ChainPending(ChainError):
    """The transaction was sent but not yet mined; confirm it later by hash instead of sending again."""

    def __init__(self, tx_hash: str):
        super().__init__("anchor transaction sent, receipt not yet available")
        self.tx_hash = tx_hash


class AnchorTx(BaseModel):
    tx_hash: str
    chain_id: int
    from_address: str
    block_number: int
    block_timestamp: int  # unix seconds, from the block


class OnchainTx(BaseModel):
    """An anchor transaction as the chain reports it. `block_number` is None while pending."""

    tx_hash: str
    chain_id: int
    from_address: str
    to_address: str | None
    value_wei: int
    data_hex: str  # no 0x prefix, lower case
    block_number: int | None
    block_timestamp: int | None
    succeeded: bool | None


class Chain(Protocol):
    chain_id: int

    @property
    def can_send(self) -> bool: ...

    def send_anchor(self, root_hex: str) -> AnchorTx: ...

    def get_tx(self, tx_hash: str) -> OnchainTx: ...


def ensure_testnet(chain_id: int) -> None:
    """Invariant 9: refuse any chain outside the testnet allow-list (Sepolia, Base Sepolia)."""
    if chain_id not in ANCHOR_CHAIN_ALLOWLIST:
        raise ChainError(f"chain {chain_id} is not an allow-listed testnet {sorted(ANCHOR_CHAIN_ALLOWLIST)}")


def _safe(exc: Exception) -> ChainError:
    return exc if isinstance(exc, ChainError) else ChainError(f"RPC call failed ({exc.__class__.__name__})")


class Web3Chain:
    """Live testnet access. Holds the throwaway anchor key in memory only; it is never logged or returned."""

    def __init__(self, rpc_url: str, private_key: str, chain_id: int, *, timeout_s: float = 30,
                 receipt_timeout_s: float = 180):
        ensure_testnet(chain_id)
        from eth_account import Account
        from web3 import Web3

        self.chain_id = chain_id
        self._w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout_s}))
        self._account = Account.from_key(private_key)
        self._receipt_timeout_s = receipt_timeout_s

    @property
    def can_send(self) -> bool:
        return True

    @property
    def address(self) -> str:
        return self._account.address

    def _check_endpoint(self) -> None:
        actual = int(self._w3.eth.chain_id)
        ensure_testnet(actual)
        if actual != self.chain_id:
            raise ChainError(f"RPC endpoint is on chain {actual}, configured for {self.chain_id}")

    def send_anchor(self, root_hex: str) -> AnchorTx:
        from web3 import Web3
        from web3.exceptions import TimeExhausted

        if len(bytes.fromhex(root_hex)) != 32:
            raise ChainError("anchor data must be exactly one 32-byte root")
        try:
            self._check_endpoint()
            w3, addr = self._w3, self._account.address
            tx = {"from": addr, "to": addr, "value": 0, "data": "0x" + root_hex, "chainId": self.chain_id,
                  "nonce": w3.eth.get_transaction_count(addr, "pending")}
            tx["gas"] = w3.eth.estimate_gas(tx)
            base_fee = int(w3.eth.get_block("latest")["baseFeePerGas"])
            tip = int(w3.eth.max_priority_fee)
            tx.update(type=2, maxPriorityFeePerGas=tip, maxFeePerGas=2 * base_fee + tip)
            del tx["from"]
            sent = w3.eth.send_raw_transaction(self._account.sign_transaction(tx).raw_transaction)
            tx_hash = Web3.to_hex(sent)
        except Exception as exc:
            raise _safe(exc) from None
        try:
            receipt = w3.eth.wait_for_transaction_receipt(sent, timeout=self._receipt_timeout_s)
            if receipt["status"] != 1:
                raise ChainError("anchor transaction failed on chain")
            block = w3.eth.get_block(receipt["blockNumber"])
        except TimeExhausted:
            raise ChainPending(tx_hash) from None
        except Exception as exc:
            if isinstance(exc, ChainError):
                raise
            raise ChainPending(tx_hash) from None
        return AnchorTx(tx_hash=tx_hash, chain_id=self.chain_id, from_address=addr,
                        block_number=int(receipt["blockNumber"]), block_timestamp=int(block["timestamp"]))

    def get_tx(self, tx_hash: str) -> OnchainTx:
        from web3 import Web3
        from web3.exceptions import TransactionNotFound

        try:
            self._check_endpoint()
            tx = self._w3.eth.get_transaction(tx_hash)
            number = tx.get("blockNumber")
            stamp, ok = None, None
            if number is not None:
                stamp = int(self._w3.eth.get_block(number)["timestamp"])
                ok = self._w3.eth.get_transaction_receipt(tx_hash)["status"] == 1
        except TransactionNotFound:
            raise ChainError("transaction not found on chain") from None
        except Exception as exc:
            raise _safe(exc) from None
        return OnchainTx(tx_hash=Web3.to_hex(tx["hash"]), chain_id=int(tx.get("chainId") or self.chain_id),
                         from_address=tx["from"], to_address=tx.get("to"), value_wei=int(tx["value"]),
                         data_hex=Web3.to_hex(tx["input"])[2:].lower(),
                         block_number=None if number is None else int(number), block_timestamp=stamp, succeeded=ok)


class CachedChain:
    """`live` behind the record/replay cache.

    - replay: sends are refused (`can_send` is False unless a live chain is given); reads return recordings only.
    - record: a root already recorded is not sent again; reads go live and mined results are recorded.
    - off: everything goes live; nothing is stored.
    """

    def __init__(self, cache: RequestCache, chain_id: int, live: Chain | None = None):
        ensure_testnet(chain_id)
        if live is not None and live.chain_id != chain_id:
            raise ChainError("live chain and cache disagree on the chain ID")
        self.cache = cache
        self.chain_id = chain_id
        self.live = live if cache.mode != "replay" else None

    @property
    def can_send(self) -> bool:
        return self.live is not None and self.live.can_send

    def _recorded(self, content: dict) -> dict | None:
        return self.cache.get(NAMESPACE, self.cache.key(NAMESPACE, content))

    def _store(self, content: dict, response: dict) -> None:
        self.cache.put(NAMESPACE, self.cache.key(NAMESPACE, content), content, response)

    def send_anchor(self, root_hex: str) -> AnchorTx:
        content = {"op": "send_anchor", "chain_id": self.chain_id, "root": root_hex}
        stored = self._recorded(content)
        if stored is not None:
            return AnchorTx(**stored)
        if self.live is None:
            raise ChainError("no live RPC configured and no recorded anchor for this root")
        tx = self.live.send_anchor(root_hex)
        self._store(content, tx.model_dump())
        if self.cache.mode == "record":
            try:  # record the read-back too, so this anchor can be verified offline (CI)
                self.get_tx(tx.tx_hash)
            except ChainError:
                pass  # the receipt already proved inclusion; verification will read it live later
        return tx

    def get_tx(self, tx_hash: str) -> OnchainTx:
        content = {"op": "get_tx", "chain_id": self.chain_id, "tx_hash": tx_hash.lower()}
        if self.live is None:
            stored = self._recorded(content)
            if stored is None:
                raise ChainError("chain not reachable here (replay mode) and no recorded response for this tx")
            return OnchainTx(**stored)
        tx = self.live.get_tx(tx_hash)
        if tx.block_number is not None:
            self._store(content, tx.model_dump())
        return tx
