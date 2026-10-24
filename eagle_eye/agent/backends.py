"""Where agent answers come from.

* ``AnthropicBackend`` - the real Messages API through the Anthropic SDK (the verifier runs the tool loop itself).
* ``ReplayBackend``    - recorded decisions keyed by ``"<photo_sha>|<finding_id>"`` (CI, demos without a key).
* ``MockBackend``      - no model: every finding gets UNCLEAR (exercises the loop, never changes a verdict).
* ``ScriptedBackend`` / ``FakeClient`` - scripted responses for tests (same code path as the real backend).
* ``RecordingWrapper`` - appends every real decision to a replay file (``EAGLE_AGENT_RECORD``) to build CI fixtures.
"""
import hashlib
import inspect
import itertools
import json
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace

from agent import config as acfg

REPLAY_SCHEMA = "eagle-eye-agent-replay/1"
_FILE_LOCK = threading.Lock()


class Backend:
    name = "base"
    kind = "llm"            # "llm": the verifier sends Messages API requests; "replay": decisions are looked up

    def create(self, params):
        """Send one Messages API request (dict of messages.create kwargs); returns the message object."""
        raise NotImplementedError

    def list_models(self):
        """Model ids this credential can use, or None when unknown."""
        return None

    def lookup(self, photo_sha, finding_id, crop_sha):
        """Recorded decision dict (replay backends), else None."""
        return None

    def on_decision(self, photo_sha, finding_id, crop_sha, record):
        """Called with every decision obtained from the model (RecordingWrapper writes it down)."""


# ------------------------------------------------------------------ real API
def _accepts(fn, name):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _status(exc):
    return getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)


class AnthropicBackend(Backend):
    """Compatibility adapter for the in-memory test client only.

    Hosted inference is deliberately unavailable in this build, including when credentials are present. Retaining
    the fake-client tool loop lets regression fixtures exercise old transcripts without making network requests.
    """
    name = "anthropic"

    def __init__(self, client=None, fallbacks=None, timeout=None):
        s = acfg.load()
        if not isinstance(client, FakeClient):
            raise RuntimeError("External AI APIs are disabled. Only the in-memory test client is supported.")
        self.client = client
        self.fallbacks = s.fallbacks if fallbacks is None else fallbacks
        self._fallbacks_rejected = False
        self._models = None
        self._models_lock = threading.Lock()

    def create(self, params):
        if self.fallbacks and not self._fallbacks_rejected and params.get("model") in acfg.FALLBACK_MODELS:
            try:
                return self._create_with_fallbacks(params)
            except Exception as e:  # noqa: BLE001 - re-raised unless it is the fallbacks opt-in itself being refused
                if _status(e) != 400 or "fallback" not in str(e).lower():
                    raise
                self._fallbacks_rejected = True               # this account/model refuses the beta: plain requests
        return self.client.messages.create(**params)

    def _create_with_fallbacks(self, params):
        create = self.client.beta.messages.create
        kw = dict(params, betas=[acfg.FALLBACK_BETA])
        if _accepts(create, "fallbacks"):
            kw["fallbacks"] = "default"
        else:                                                  # an SDK older than the parameter: send it raw
            kw["extra_body"] = {**(kw.get("extra_body") or {}), "fallbacks": "default"}
        return create(**kw)

    def list_models(self):
        """Ids from GET /v1/models, fetched once per backend."""
        with self._models_lock:
            if self._models is None:
                page = self.client.models.list(limit=100)
                self._models = [getattr(m, "id", None) or m.get("id") for m in (getattr(page, "data", None) or page)]
            return list(self._models)


# ------------------------------------------------------------------ fake client (tests, mock)
_ids = itertools.count(1)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name, input, id=None):  # noqa: A002 - mirrors the API field name
    return SimpleNamespace(type="tool_use", id=id or f"toolu_fake_{next(_ids)}", name=name, input=input)


def fake_message(content, stop_reason=None, usage=None, model=None, stop_details=None):
    """A Messages API response look-alike (.content, .stop_reason, .stop_details, .usage, .model)."""
    content = list(content)
    if stop_reason is None:
        stop_reason = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
    u = dict(input_tokens=1200, output_tokens=150, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    u.update(usage or {})
    return SimpleNamespace(id=f"msg_fake_{next(_ids)}", type="message", role="assistant", content=content,
                           stop_reason=stop_reason, stop_details=stop_details, usage=SimpleNamespace(**u), model=model)


def refusal_message(category="cyber", explanation="declined by a safety classifier"):
    return fake_message([], stop_reason="refusal",
                        stop_details=SimpleNamespace(type="refusal", category=category, explanation=explanation))


class FakeClient:
    """Stand-in for ``anthropic.Anthropic``: scripted responses, every request recorded in ``requests``.

    ``script`` is a list of responses (or callables params -> response, or exceptions to raise) consumed in order;
    ``handler(params)`` answers instead when given. ``models`` is what models.list() returns (an exception is raised).
    """

    def __init__(self, script=None, handler=None, models=None):
        self.requests = []                 # (endpoint, params) with endpoint "messages" | "beta"
        self._script = list(script or [])
        self._handler = handler
        self._models_ret = models
        self._lock = threading.Lock()
        self.messages = SimpleNamespace(create=lambda **kw: self._respond("messages", kw))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self._respond("beta", kw)))
        self.models = SimpleNamespace(list=self._list_models)

    def _respond(self, endpoint, params):
        params = dict(params, messages=list(params.get("messages") or []))
        with self._lock:
            self.requests.append((endpoint, params))
            if self._handler is None:
                if not self._script:
                    raise RuntimeError("FakeClient: script exhausted")
                item = self._script.pop(0)
        if self._handler is not None:
            item = self._handler(params)
        if callable(item):
            item = item(params)
        if isinstance(item, BaseException):
            raise item
        return item

    def _list_models(self, **_):
        if isinstance(self._models_ret, BaseException):
            raise self._models_ret
        return SimpleNamespace(data=[SimpleNamespace(id=m) for m in (self._models_ret or [])])


class ScriptedBackend(AnthropicBackend):
    """AnthropicBackend over a FakeClient (no network): what the tests drive."""
    name = "scripted"

    def __init__(self, script=None, handler=None, models=None, fallbacks=False):
        super().__init__(client=FakeClient(script, handler, models), fallbacks=fallbacks)


_FID_RX = re.compile(r'finding_id="([^"]+)"')


def _mock_answer(params):
    first = params["messages"][0]["content"]
    texts = " ".join(b.get("text", "") for b in first if isinstance(b, dict) and b.get("type") == "text")
    ids = _FID_RX.findall(texts)
    if not ids:                                           # the per-photo overview
        return fake_message([text_block("mock backend: no overview")], usage={"input_tokens": 0, "output_tokens": 0})
    return fake_message([tool_use_block("record_decision", {
        "finding_id": ids[-1], "verdict": "UNCLEAR", "confidence": 0.0,
        "reason": "mock agent backend: no model was consulted",
        "evidence_boxes": [], "rephoto_hint": "Capture a sharp close-up and verify against the matching drawing"})],
        usage={"input_tokens": 0, "output_tokens": 0}, model="mock")


class MockBackend(AnthropicBackend):
    name = "mock"

    def __init__(self):
        super().__init__(client=FakeClient(handler=_mock_answer, models=["mock"]), fallbacks=False)


# ------------------------------------------------------------------ replay / record
def replay_key(photo_sha, finding_id):
    return f"{photo_sha}|{finding_id}"


def load_replay(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("decisions", data) if isinstance(data, dict) else {}


class ReplayBackend(Backend):
    """Decisions recorded from real runs. An entry with ``crop_sha`` only matches the same evidence crop."""
    name = "replay"
    kind = "replay"

    def __init__(self, path):
        self.path = Path(path)
        self.decisions = load_replay(self.path)

    def lookup(self, photo_sha, finding_id, crop_sha):
        e = self.decisions.get(replay_key(photo_sha, finding_id))
        if not isinstance(e, dict):
            return None
        if e.get("crop_sha") and crop_sha and e["crop_sha"] != crop_sha:
            return {"mismatch": True, "crop_sha": e["crop_sha"]}
        return e


def append_replay(path, photo_sha, finding_id, crop_sha, record):
    """Add one decision to a replay file (created when missing); thread-safe, atomic replace."""
    path = Path(path)
    entry = {k: record.get(k) for k in ("verdict", "confidence", "reason", "evidence_boxes", "rephoto_hint", "model")}
    entry["crop_sha"] = crop_sha
    with _FILE_LOCK:
        data = {"schema": REPLAY_SCHEMA, "decisions": {}}
        if path.exists():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                data["decisions"] = old.get("decisions", {}) if isinstance(old, dict) else {}
            except (OSError, ValueError):
                pass
        data["decisions"][replay_key(photo_sha, finding_id)] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(acfg.redact(json.dumps(data, indent=1, ensure_ascii=False)), encoding="utf-8")
        os.replace(tmp, path)


class RecordingWrapper(Backend):
    """Delegates to a real backend and appends each decision it produces to a replay file."""

    def __init__(self, inner, path):
        self.inner, self.path = inner, Path(path)
        self.name, self.kind = inner.name, inner.kind

    def create(self, params):
        return self.inner.create(params)

    def list_models(self):
        return self.inner.list_models()

    def lookup(self, photo_sha, finding_id, crop_sha):
        return self.inner.lookup(photo_sha, finding_id, crop_sha)

    def on_decision(self, photo_sha, finding_id, crop_sha, record):
        append_replay(self.path, photo_sha, finding_id, crop_sha, record)
        self.inner.on_decision(photo_sha, finding_id, crop_sha, record)


# ------------------------------------------------------------------ selection
def detect(s=None):
    """(backend name | None, reason) from the environment, without creating a client or touching the network."""
    s = s or acfg.load()
    if s.enabled is False:
        return None, "disabled by EAGLE_AGENT_ENABLED=0"
    b = s.backend
    if b == "auto":
        if s.replay:
            b = "replay"
        else:
            return None, "local OCR and geometry; external AI APIs are disabled"
    if b in ("off", "none", "local"):
        return None, "local OCR and geometry; external AI APIs are disabled"
    if b == "anthropic":
        return None, "external AI APIs are disabled, including EAGLE_AGENT_BACKEND=anthropic"
    if b == "replay":
        if not s.replay or not Path(s.replay).is_file():
            return None, f"EAGLE_AGENT_REPLAY file not found: {s.replay or '(unset)'}"
        return "replay", f"recorded decisions from {Path(s.replay).name}"
    if b == "mock":
        return "mock", "mock backend: no model is consulted, every candidate stays UNCLEAR"
    return None, f"unknown EAGLE_AGENT_BACKEND={b!r} (local | replay | mock)"


def is_offline(backend):
    """Allow only known local fixtures, never an arbitrary network-capable injected backend."""
    if isinstance(backend, RecordingWrapper):
        return is_offline(backend.inner)
    return isinstance(backend, ReplayBackend) or isinstance(getattr(backend, "client", None), FakeClient)


_CACHE = {}
_CACHE_LOCK = threading.Lock()


def get_backend(s=None):
    """(Backend | None, reason) for the current environment; instances are reused while the settings are unchanged."""
    s = s or acfg.load()
    name, reason = detect(s)
    if name is None:
        return None, reason
    creds = "|".join(os.environ.get(k, "") for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    key = (name, s.replay, s.record, s.fallbacks, s.timeout, hashlib.sha256(creds.encode()).hexdigest())
    with _CACHE_LOCK:
        if key not in _CACHE:
            try:
                if name == "replay":
                    backend = ReplayBackend(s.replay)
                else:
                    backend = MockBackend()
            except Exception as e:  # noqa: BLE001 - e.g. no credential profile: the agent is simply off
                return None, acfg.redact(f"{name} backend unavailable: {type(e).__name__}: {e}")[:300]
            if s.record and backend.kind == "llm" and name != "mock":
                backend = RecordingWrapper(backend, s.record)
            _CACHE[key] = backend
        return _CACHE[key], reason
