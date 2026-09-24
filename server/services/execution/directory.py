"""Standard-library agent directory. Lexical scores are not ownership confidence."""
from __future__ import annotations
import base64
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
from html import unescape
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

BUDGET, LIMIT = 4096, 8
RANKING_VERSION = "field-bm25-v2-frozen"
STOP = set("a an the to for from of on in with and or is it this that please me my our use agent follow up about latest previous again now can you handle task work send draft reply".split())

def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")

def clip(text, size):
    return str(text).encode("utf-8")[:size].decode("utf-8", errors="ignore")

def terms(text):
    return {t for t in re.findall(r"[^\W_]+", str(text).casefold()) if t not in STOP and len(t) > 1}

def phrases(text):
    tokens = [t for t in re.findall(r"[^\W_]+", str(text).casefold()) if t not in STOP and len(t) > 1]
    return set(zip(tokens, tokens[1:]))

# Small domain-general lexical aliases, not project/contact or owner aliases.
ALIASES = {"vendor": "supplier", "agreement": "contract", "renewal": "extension",
           "refund": "reimbursement", "purchase": "procurement", "shipping": "shipment",
           "authorization": "approval", "reservation": "booking"}


def positive_query(text):
    # Only explicit comma-delimited contrast; not general negation understanding.
    return re.sub(r",\s*not\s+[^.!?\n]*(?:[.!?]|$)", " ", text, flags=re.I)


def retrieval_tokens(text):
    """Conservative plural folding for scoring only, never for identity."""
    result = []
    for token in re.findall(r"[^\W_]+", str(text).casefold()):
        if token in STOP or len(token) <= 1:
            continue
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
            token = token[:-1]
        result.append(ALIASES.get(token, token))
    return result

def normalized(text):
    return " ".join(re.findall(r"[^\W_]+", str(text).casefold()))

def contains_name(query, name):
    needle = normalized(name)
    return bool(needle) and f" {needle} " in f" {normalized(query)} "

def reference(name):
    return "ag_" + uuid.uuid5(uuid.NAMESPACE_URL, "openpoke-agent:" + name).hex

def retrieval_query(latest, transcript=""):
    previous = re.findall(r"<user_message\b[^>]*>(.*?)</user_message>", transcript, re.S)
    return clip(latest, 4096) + "\n" + clip("\n".join(unescape(t) for t in previous[-2:]), 1024)

def now():
    return datetime.now(timezone.utc).isoformat()

def entities(text):
    found = re.findall(r"[\w.+-]+@[\w.-]+|\b[A-Z][\w-]*(?: [A-Z][\w-]*)*", text)
    return list(dict.fromkeys(clip(s, 80) for s in found))[:16]

def metadata(name, instructions="", timestamp=None):
    return {"ref": reference(name), "name": name, "purpose": clip(instructions, 240),
            "entities": entities(name + " " + instructions),
            "recent_instructions": [clip(instructions, 600)] if instructions else [],
            "created_at": timestamp, "last_used_at": timestamp}

class AgentDirectory:
    def __init__(self, path: Path, history_loader=None):
        self._roster_path = Path(path)
        self._history_loader = history_loader or self._legacy_history
        self.records, self.recent_refs = [], []
        self.load()

    @contextmanager
    def _locked(self):
        self._roster_path.parent.mkdir(parents=True, exist_ok=True)
        with self._roster_path.with_suffix(".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _legacy_history(self, name):
        # Same slug as ExecutionAgentLogStore; identities and files stay unchanged.
        slug = re.sub("-+", "-", "".join(c.lower() if c.isalnum() else "-" for c in name.strip()).strip("-")) or "agent"
        if len(slug.encode()) > 220:
            slug = "long-name-" + hashlib.sha256(name.encode()).hexdigest()
        try:
            text = (self._roster_path.parent / (slug + ".log")).read_text()
        except OSError:
            return []
        return [unescape(s).replace("\\n", "\n") for s in re.findall(r"<agent_request\b[^>]*>(.*?)</agent_request>", text, re.S)]

    def _read(self):
        if not self._roster_path.exists():
            self.records, self.recent_refs = [], []
            return
        raw = self._roster_path.read_bytes()
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                if not all(isinstance(n, str) and n.strip() for n in data):
                    raise ValueError("Invalid legacy agent names")
                self.records = []
                for name in dict.fromkeys(data):
                    history = self._history_loader(name)
                    r = metadata(name, history[0] if history else "")
                    r["recent_instructions"] = [clip(s, 600) for s in history[-3:]]
                    r["entities"] = entities(name + " " + " ".join(history[-3:]))
                    self.records.append(r)
                self.recent_refs = []
                backup = self._roster_path.with_suffix(".legacy.bak")
                if not backup.exists():
                    with backup.open("xb") as h:
                        h.write(raw)
                self._write()
                return
            if not isinstance(data, dict) or data.get("version") != 2:
                raise ValueError("Unsupported directory version")
            records = data["agents"]
            if not isinstance(records, list):
                raise ValueError("Invalid agent records")
            names, refs = set(), set()
            for r in records:
                if not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"].strip():
                    raise ValueError("Invalid agent identity")
                if r.get("ref") != reference(r["name"]) or r["name"] in names or r["ref"] in refs:
                    raise ValueError("Duplicate or invalid agent identity")
                if not isinstance(r.get("purpose"), str) or not all(isinstance(r.get(k), list) and all(isinstance(v, str) for v in r[k]) for k in ("entities", "recent_instructions")):
                    raise ValueError("Invalid metadata")
                if any(r.get(k) is not None and not isinstance(r[k], str) for k in ("created_at", "last_used_at")):
                    raise ValueError("Invalid timestamp")
                names.add(r["name"]); refs.add(r["ref"])
            self.records = records
            recent = data.get("recent_refs", [])
            if not isinstance(recent, list) or not all(isinstance(r, str) for r in recent):
                raise ValueError("Invalid recent references")
            self.recent_refs = [r for r in recent if r in refs][-3:]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Malformed directory; original file preserved") from exc

    def _write(self):
        fd, path = tempfile.mkstemp(prefix=".roster-", dir=self._roster_path.parent)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(encoded({"version": 2, "agents": self.records, "recent_refs": self.recent_refs}))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(path, self._roster_path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def load(self):
        with self._locked():
            self._read()

    def get_agents(self):
        return [r["name"] for r in self.records]

    def resolve(self, agent_name=None, agent_ref=None):
        self.load()
        by_name = next((r for r in self.records if r["name"] == agent_name), None)
        by_ref = next((r for r in self.records if r["ref"] == agent_ref), None)
        if agent_ref and not by_ref:
            raise ValueError("Unknown agent reference; search again")
        if agent_name is not None and agent_ref and (not by_name or by_name["ref"] != by_ref["ref"]):
            raise ValueError("Conflicting agent name and reference")
        return deepcopy(by_ref or by_name)

    def create_or_reuse(self, name, purpose="", instructions=""):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Agent name must be nonempty")
        with self._locked():
            self._read()
            existing = next((r for r in self.records if r["name"] == name), None)
            if existing:
                return deepcopy(existing), False
            r = metadata(name, instructions or purpose, now())
            self.records.append(r)
            self._write()
            return deepcopy(r), True

    def add_agent(self, agent_name):
        self.create_or_reuse(agent_name)

    def mark_used(self, ref, instructions):
        with self._locked():
            self._read()
            r = next((r for r in self.records if r["ref"] == ref), None)
            if r is None:
                raise ValueError("Agent no longer exists")
            r["last_used_at"] = now()
            if not r["purpose"]:
                r["purpose"] = clip(instructions, 240)
            r["recent_instructions"] = (r["recent_instructions"] + [clip(instructions, 600)])[-3:]
            r["entities"] = entities(r["name"] + " " + r["purpose"] + " " + " ".join(r["recent_instructions"]))
            self.recent_refs = ([v for v in self.recent_refs if v != ref] + [ref])[-3:]
            self._write()

    def clear(self):
        with self._locked():
            self.records, self.recent_refs = [], []
            self._write()

    def rank(self, query, enriched=True, pinned=()):
        # One normalized token stream per field; duplicated metadata does not
        # become multiple independent votes for the same responsibility.
        documents = []
        for r in self.records:
            fields = {"name": Counter(retrieval_tokens(r["name"]))}
            if enriched:
                responsibility = Counter()
                for text in [r["purpose"], *r["recent_instructions"]]:
                    responsibility |= Counter(retrieval_tokens(text))
                fields["responsibility"] = responsibility
            documents.append(fields)
        if not documents:
            return []
        weights = {"name": 1.0, "responsibility": 2.0}
        averages = {field: sum(sum(d.get(field, {}).values()) for d in documents) / len(documents)
                    for field in weights}
        # Production retrieval_query separates latest request from older user
        # context with a newline. Context still contributes, but at half weight.
        query = positive_query(query)
        latest, _, context = query.partition("\n")
        q = {t: 0.5 for t in retrieval_tokens(context)}
        q.update({t: 1.0 for t in retrieval_tokens(latest)})
        unions = [set().union(*(set(c) for c in d.values())) for d in documents]
        idf = {t: math.log(1 + (len(documents) - sum(t in d for d in unions) + 0.5) /
                           (sum(t in d for d in unions) + 0.5)) for t in q}
        rows = []
        for r, fields in zip(self.records, documents):
            score, why = 0.0, []
            # Saturate once per query term, after field normalization. The
            # strongest field supplies evidence; copying history into a name
            # must not multiply the same match's contribution.
            for t in q:
                evidence = []
                for field, counts in fields.items():
                    length = sum(counts.values())
                    norm = min(1.5, 0.5 + 0.5 * length / (averages[field] or 1))
                    evidence.append(weights[field] * counts.get(t, 0) / norm)
                tf = max(evidence, default=0)
                score += q[t] * idf[t] * tf * 2.2 / (tf + 1.2)
            for field, counts in fields.items():
                matches = sorted(set(q) & counts.keys())
                if matches:
                    why.append(field + ": " + ", ".join(matches[:4]))
            exact = r["ref"] in query or contains_name(query, r["name"])
            pin = r["ref"] in pinned
            if exact:
                why.insert(0, "explicit name/reference")
            if pin:
                why.insert(0, "recent delegation")
            rows.append((exact, pin, round(score, 4), r["last_used_at"] or "", r, why))
        rows.sort(key=lambda x: x[4]["ref"])
        rows.sort(key=lambda x: x[:4], reverse=True)
        return rows

    def _page(self, rows, offset, signature, envelope=""):
        payload = {"candidates": [], "next_cursor": None, "notice": "Partial directory. Use search_agents for other owners. Dispatch by ref; display names may be shortened."}
        def cursor(n):
            return base64.urlsafe_b64encode(encoded([signature, n]).encode()).decode()
        consumed = 0
        for _, _, score, _, r, why in rows[offset:offset+LIMIT]:
            item = {"ref": r["ref"], "name": clip(r["name"], 100), "purpose": clip(r["purpose"], 140), "last_used_at": clip(r["last_used_at"], 40) if r["last_used_at"] else None, "score": score, "match": clip("; ".join(why) or "directory listing", 140)}
            payload["candidates"].append(item)
            payload["next_cursor"] = cursor(offset+consumed+1) if offset+consumed+1 < len(rows) else None
            if len(encoded(payload).encode()) + len(envelope.encode()) > BUDGET:
                payload["candidates"].pop()
                break
            consumed += 1
        payload["next_cursor"] = cursor(offset+consumed) if offset+consumed < len(rows) else None
        return payload

    def search(self, query, cursor=None, enriched=True):
        self.load()
        if not isinstance(query, str) or len(query.encode()) > 8192:
            raise ValueError("Search query must be text of at most 8192 bytes")
        rows = self.rank(query, enriched)
        if query.strip():
            rows = [r for r in rows if r[0] or r[2] > 0]
        signature = hashlib.sha256(encoded([query, enriched, self.records]).encode()).hexdigest()[:16]
        offset = 0
        if cursor:
            try:
                sig, offset = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
                if sig != signature or type(offset) is not int or not 0 <= offset < len(rows):
                    raise ValueError()
            except Exception as exc:
                raise ValueError("Invalid or stale cursor; restart search") from exc
        return self._page(rows, offset, signature)

    def shortlist(self, latest, transcript="", enriched=True):
        self.load()
        rows = self.rank(retrieval_query(latest, transcript), enriched, self.recent_refs)
        latest = positive_query(latest)
        explicit = {r["ref"] for r in self.records if r["ref"] in latest or contains_name(latest, r["name"])}
        rows.sort(key=lambda row: row[4]["ref"] in explicit, reverse=True)
        page = self._page(rows, 0, "shortlist", "<active_agents>\n\n</active_agents>")
        page["next_cursor"] = None
        return "<active_agents>\n" + encoded(page) + "\n</active_agents>"
