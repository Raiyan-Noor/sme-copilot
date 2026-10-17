"""On-chain anchoring of audit hashes (invariant 9).

Publishes only a Merkle root of hashes (audit-log head, newly signed mandates, exported Passports) in a 0-value
self-transaction on an allow-listed EVM testnet (Sepolia 11155111, Base Sepolia 84532). Never business data,
names, amounts or PII. Never blocks core flows: on RPC failure, queue, retry with backoff and log.
"""
