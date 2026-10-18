/**
 * The owner's Ed25519 signing key, kept in this browser (invariant 6).
 *
 * The key pair is generated with tweetnacl on first use and stored in IndexedDB. Only the public key ever leaves
 * the browser: it is enrolled with the server (trust on first use per business), and the server verifies detached
 * signatures over the exact canonical `message` it handed out ({action, args_hash, nonce, expiry}). The secret key
 * is never sent, logged or put in localStorage. Clearing this site's data loses the key; a business that already
 * enrolled another key then refuses this browser, by design.
 */
import nacl from "tweetnacl";

import { api, ApiError } from "@/lib/api";

const DB_NAME = "owner-signing";
const STORE = "keys";
const KEY_ID = "owner";

type StoredKey = { publicKey: Uint8Array; secretKey: Uint8Array };

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("This browser cannot store a signing key (no IndexedDB)."));
      return;
    }
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("Could not open the key store."));
  });
}

function tx<T>(db: IDBDatabase, mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    const req = run(db.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("Key store request failed."));
  });
}

let cached: Promise<StoredKey> | null = null;

/** The key pair for this browser, generated and stored on first run. */
function loadKey(): Promise<StoredKey> {
  cached ??= (async () => {
    const db = await openDb();
    const found = await tx<StoredKey | undefined>(db, "readonly", (s) => s.get(KEY_ID));
    if (found?.publicKey && found?.secretKey) return found;
    const pair = nacl.sign.keyPair();
    const key = { publicKey: pair.publicKey, secretKey: pair.secretKey };
    await tx(db, "readwrite", (s) => s.put(key, KEY_ID));
    return key;
  })();
  cached.catch(() => {
    cached = null;
  });
  return cached;
}

const hex = (bytes: Uint8Array) => Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

export async function ownerPublicKey(): Promise<string> {
  return hex((await loadKey()).publicKey);
}

const enrolled = new Set<string>();

/**
 * Enroll this browser's public key for a business (idempotent on the server). A 409 means another key is already
 * the owner's: this browser cannot sign for that business.
 */
export async function ensureEnrolled(businessId: string): Promise<string> {
  const publicKey = await ownerPublicKey();
  if (enrolled.has(`${businessId}:${publicKey}`)) return publicKey;
  try {
    await api.enrollOwnerKey(businessId, { public_key: publicKey });
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      throw new Error("A different signing key is already enrolled for this business, so this browser cannot sign.");
    }
    throw e;
  }
  enrolled.add(`${businessId}:${publicKey}`);
  return publicKey;
}

/** Sign the server's canonical message bytes (UTF-8) with the key in this browser; returns the hex signature. */
export async function signMessage(message: string): Promise<{ signature: string; publicKey: string }> {
  const key = await loadKey();
  const signature = nacl.sign.detached(new TextEncoder().encode(message), key.secretKey);
  return { signature: hex(signature), publicKey: hex(key.publicKey) };
}
