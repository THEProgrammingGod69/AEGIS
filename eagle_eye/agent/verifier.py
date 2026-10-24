"""Claude vision verifier: an independent second opinion on the deterministic candidates of one photo (spec section 7).

Per photo: optional overview call (downscaled photo + expected tags + candidate list -> short notes), then one
tool-use conversation per candidate, in parallel. Every request on a photo starts with the same cached prefix (tools +
system prompt + per-photo context + downscaled photo), so the per-finding calls read it from the prompt cache. The agent
answers only through record_decision; anything else (no answer, invalid answer twice, refusal, budget, API error)
becomes UNCLEAR, which the consensus stage turns into REVIEW, never into FAIL.

Decisions are cached under DATA/cache/agent by (photo sha, finding id, evidence-crop sha + question) so reruns are free
and reproducible; the transcript (text, image hashes, usage, latency - never image bytes or keys) goes to
<run_dir>/agent_transcript.jsonl.
"""
import base64
import datetime
import hashlib
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from agent import backends, prompts, tools
from agent import config as acfg
from agent.schema import Decision, unclear

SEND = ("CANDIDATE_FAULT", "UNCERTAIN")
TRANSCRIPT = "agent_transcript.jsonl"
_STATUS_RANK = {("CANDIDATE_FAULT", "strong"): 0, ("CANDIDATE_FAULT", "weak"): 1, ("CANDIDATE_FAULT", None): 1}


# ------------------------------------------------------------------ public API
def status():
    """{"enabled", "backend", "model", "fast_model", "reason", ...} from the environment (no network call)."""
    s = acfg.load()
    name, reason = backends.detect(s)
    return {"enabled": name is not None, "backend": name, "model": s.model, "fast_model": s.fast_model,
            "reason": reason, "max_calls": s.max_calls, "fallbacks": s.fallbacks,
            "replay": s.replay if name == "replay" else None, "record": s.record}


def resolve_models(backend, s=None):
    """(main model, fast model). EAGLE_AGENT_MODEL=auto picks the first of AUTO_PREFERENCE the key can use."""
    s = s or acfg.load()
    main = s.model
    if main == "auto":
        main = acfg.DEFAULT_MODEL
        try:
            ids = set(backend.list_models() or [])
            main = next((m for m in acfg.AUTO_PREFERENCE if m in ids), acfg.DEFAULT_MODEL)
        except Exception:  # noqa: BLE001 - models endpoint unreachable: the default model is always available
            pass
    fast = main if s.fast_model == "auto" else s.fast_model
    return main, fast


def verify(findings, ctx, run_dir=None, on_event=None, backend=None):
    """Ask the agent about every CANDIDATE_FAULT / UNCERTAIN finding of one photo.

    Returns {"enabled", "backend", "model", "fast_model", "decisions": {finding_id: decision}, "calls",
    "usage": {"input", "output", "cache_read", "cache_write"}, "cost_usd", "summary", "overview", "errors"}.
    A decision is Decision fields + model, cached, source (api | cache | replay | budget | refusal | error ...), crops.
    """
    s = acfg.load()
    reason = "backend supplied by the caller"
    if backend is None:
        backend, reason = backends.get_backend(s)
    findings = list(findings.values()) if isinstance(findings, dict) else list(findings or [])
    out = {"enabled": backend is not None, "backend": getattr(backend, "name", None), "model": None,
           "fast_model": None, "decisions": {}, "calls": 0,
           "usage": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}, "cost_usd": 0.0,
           "summary": "", "overview": None, "errors": [], "reason": reason}
    if backend is None:
        out["summary"] = f"agent off: {reason}"
        return out
    return _Run(s, backend, ctx, findings, run_dir, on_event).execute(out)


# ------------------------------------------------------------------ helpers
def _candidates(findings):
    seen, out = set(), []
    for f in findings:
        if f.get("status") in SEND and f.get("id") and f["id"] not in seen:
            seen.add(f["id"])
            out.append(f)
    # strong faults first: they get the budget when it is tight
    return sorted(out, key=lambda f: (_STATUS_RANK.get((f["status"], f.get("strength")), 2), str(f["id"])))


def _usage(resp):
    u = getattr(resp, "usage", None)
    g = (lambda k: int(getattr(u, k, 0) or 0)) if u is not None else (lambda k: 0)
    return {"input": g("input_tokens"), "output": g("output_tokens"), "cache_read": g("cache_read_input_tokens"),
            "cache_write": g("cache_creation_input_tokens")}


def _block_log(b):
    """Transcript form of a content block: text kept, images replaced by their hash and size."""
    t = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
    get = b.get if isinstance(b, dict) else (lambda k, d=None: getattr(b, k, d))
    if t == "text":
        return {"type": "text", "text": get("text")}
    if t == "image":
        src = get("source") or {}
        data = src.get("data") if isinstance(src, dict) else getattr(src, "data", None)
        raw = base64.b64decode(data) if data else b""
        try:
            size = list(Image.open(io.BytesIO(raw)).size)          # header only
        except Exception:  # noqa: BLE001
            size = None
        return {"type": "image", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "size": size}
    if t == "tool_use":
        return {"type": "tool_use", "id": get("id"), "name": get("name"), "input": get("input")}
    if t == "tool_result":
        c = get("content")
        c = [_block_log(x) for x in c] if isinstance(c, list) else c
        return {"type": "tool_result", "tool_use_id": get("tool_use_id"), "is_error": bool(get("is_error")),
                "content": c}
    if t in ("thinking", "redacted_thinking"):
        return {"type": t, "chars": len(get("thinking") or "")}
    return {"type": t}


def _msg_log(m):
    c = m["content"]
    return {"role": m["role"], "content": [_block_log(b) for b in c] if isinstance(c, list) else c}


class _Transcript:
    def __init__(self, run_dir):
        self.path = Path(run_dir) / TRANSCRIPT if run_dir else None
        self.lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **event):
        if not self.path:
            return
        event = {"t": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"), **event}
        line = acfg.redact(json.dumps(event, ensure_ascii=False, default=str))
        with self.lock, open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class _Budget:
    """API requests (and tokens) per photo. A finding's first call only needs one free call; follow-up turns,
    the overview and escalations only use calls no unstarted finding still needs."""

    def __init__(self, calls, tokens, unstarted):
        self.left, self.tokens_left, self.unstarted = calls, tokens, unstarted
        self.lock = threading.Lock()

    def _take(self):
        if self.left <= 0 or self.tokens_left <= 0:
            return False
        self.left -= 1
        return True

    def start(self):
        with self.lock:
            self.unstarted = max(0, self.unstarted - 1)
            return self._take()

    def spare(self):
        with self.lock:
            return self.left > self.unstarted and self._take()

    def spend(self, usage):
        with self.lock:
            self.tokens_left -= usage["input"] + usage["cache_write"] + usage["output"]


class _Run:
    def __init__(self, s, backend, ctx, findings, run_dir, on_event):
        self.s, self.backend, self.ctx, self.on_event = s, backend, ctx, on_event
        self.photo = ctx.photo
        self.size = tools.photo_size(self.photo)
        self.sha = str(self.photo.get("sha") or tools.pixels_sha(self.photo["rgb"], (0, 0) + self.size))
        self.fmap = tools.findings_map(ctx, findings)
        self.cands = _candidates(findings)
        self.log = _Transcript(run_dir)
        self.lock = threading.Lock()
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        self.cost, self.calls, self.errors = 0.0, 0, []
        self.main = self.fast = None
        self.system = [{"type": "text", "text": prompts.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
        self.prefix = None
        self.done = 0

    # ---------------------------------------------------------------- orchestration
    def execute(self, out):
        t0 = time.time()
        decisions, pending = {}, []
        for f in self.cands:
            prep = self._prepare(f)
            hit = self._lookup(f, prep)
            if hit:
                decisions[f["id"]] = hit
                self._emit(f, hit)
            else:
                pending.append((f, prep))
        if pending and self.backend.kind != "llm":
            for f, prep in pending:
                why = ("replay: the evidence crop changed since the decision was recorded" if prep.get("mismatch")
                       else "replay: no recorded decision for this finding")
                decisions[f["id"]] = self._record(unclear(f["id"], why, f.get("hint")), "replay", [], 0, "replay-miss")
                self._emit(f, decisions[f["id"]])
        elif pending:
            self.main, self.fast = resolve_models(self.backend, self.s)
            self.budget = _Budget(self.s.max_calls, self.s.token_budget, len(pending))
            self.log.write(event="start", photo=self.sha, backend=self.backend.name, model=self.main,
                           fast_model=self.fast, candidates=[f["id"] for f, _ in pending],
                           system_sha=hashlib.sha256(prompts.SYSTEM_PROMPT.encode()).hexdigest()[:16],
                           prompt_version=acfg.PROMPT_VERSION)
            self.prefix = self._prefix()
            notes = None
            if self.s.overview and len(pending) >= self.s.overview_min:
                notes = self._overview()
                out["overview"] = notes
            workers = max(1, min(self.s.parallel, len(pending)))
            with ThreadPoolExecutor(workers, thread_name_prefix="ee-agent") as pool:
                results = list(pool.map(lambda fp: self._verify_one(fp[0], fp[1], notes), pending))
            for (f, _), rec in zip(pending, results):
                decisions[f["id"]] = rec
        out.update(model=self.main, fast_model=self.fast, decisions=decisions, calls=self.calls, usage=self.usage,
                   cost_usd=round(self.cost, 6), errors=self.errors)
        out["summary"] = self._summary(decisions, time.time() - t0)
        if self.calls:
            self.log.write(event="done", calls=self.calls, usage=self.usage, cost_usd=out["cost_usd"],
                           summary=out["summary"])
        return out

    def _emit(self, f, rec):
        with self.lock:
            self.done += 1
            done = self.done
        if self.on_event:
            try:
                self.on_event({"stage": "agent", "event": "decision", "finding_id": f["id"], "verdict": rec["verdict"],
                               "source": rec["source"], "done": done, "total": len(self.cands)})
            except Exception:  # noqa: BLE001 - a broken progress callback must not stop the inspection
                pass

    def _summary(self, decisions, dt):
        if not decisions:
            return "no candidate findings to verify"
        n = {v: sum(1 for d in decisions.values() if d["verdict"] == v) for v in ("CONFIRMED_OK", "CONFIRMED_FAULT",
                                                                                 "UNCLEAR")}
        reused = sum(1 for d in decisions.values() if d.get("cached"))
        model = self.fast if self.fast == self.main or not self.main else f"{self.fast} -> {self.main}"
        return (f"{len(decisions)} candidate(s) checked by the agent ({self.backend.name}"
                f"{', ' + model if model else ''}): {n['CONFIRMED_OK']} OK, {n['CONFIRMED_FAULT']} fault, "
                f"{n['UNCLEAR']} unclear; {self.calls} API call(s), {reused} reused, ${self.cost:.4f}, {dt:.1f} s")

    # ---------------------------------------------------------------- evidence + cache
    def _prepare(self, f):
        region = tools.evidence_region(self.photo, f.get("box"))
        pixels = tools.region_pixels(self.photo, region)
        crop_sha = tools.pixels_sha(pixels, region)
        parts = [acfg.PROMPT_VERSION, self.sha, f["id"], crop_sha, str(f.get("check")), str(f.get("question")),
                 str(f.get("expected")), str(f.get("found"))]
        key = hashlib.sha256("|".join(parts).encode()).hexdigest()
        return {"region": region, "pixels": pixels, "crop_sha": crop_sha, "key": key}

    def _cache_path(self, key):
        return self.s.cache_dir / key[:2] / f"{key}.json"

    def _lookup(self, f, prep):
        if self.backend.kind == "replay":
            e = self.backend.lookup(self.sha, f["id"], prep["crop_sha"])
            if not e:
                return None
            if e.get("mismatch"):
                prep["mismatch"] = True
                return None
            try:
                d = Decision.model_validate({"finding_id": f["id"], **{k: e.get(k) for k in (
                    "verdict", "confidence", "reason", "evidence_boxes", "rephoto_hint")}})
            except Exception as ex:  # noqa: BLE001 - a corrupt entry is a miss, reported once
                self.errors.append(f"replay entry for {f['id']} is invalid: {ex}"[:300])
                return None
            return self._record(d, e.get("model") or "replay", [], 0, "replay", cached=True)
        if not self.s.cache:
            return None
        p = self._cache_path(prep["key"])
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return dict(rec, cached=True, source="cache", calls=0)

    def _cache_put(self, prep, rec):
        if not self.s.cache:
            return
        p = self._cache_path(prep["key"])
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps({**rec, "cache_key": prep["key"]}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            self.errors.append(f"decision cache not writable: {e}"[:200])

    def _record(self, d, model, crops, calls, source, cached=False, **extra):
        rec = d.model_dump()
        rec["reason"] = acfg.redact(rec["reason"])
        rec["rephoto_hint"] = acfg.redact(rec["rephoto_hint"])
        rec.update(model=model, cached=cached, source=source, crops=crops, calls=calls, **extra)
        return rec

    # ---------------------------------------------------------------- requests
    def _prefix(self):
        """Per-photo context + downscaled photo: identical leading blocks of every request on this photo."""
        try:
            expected = self.ctx.expected_items(None, None) or []
        except Exception as e:  # noqa: BLE001
            expected = []
            self.errors.append(f"expected_items failed: {type(e).__name__}")
        img = tools.overview_image(self.photo, self.s.image_max)
        block, meta = tools.encode_image(img, self.s.image_max, cache=True)
        self.overview_meta = {"kind": "overview", "box": [0, 0, *self.size], **meta}
        text = prompts.photo_context(self.sha, self.size, meta["size"], expected, self.cands)
        return [{"type": "text", "text": text}, block]

    def _call(self, label, model, effort, messages, conv):
        params = dict(model=model, max_tokens=self.s.max_tokens, system=self.system, tools=tools.TOOLS,
                      messages=list(messages), output_config={"effort": effort},
                      cache_control={"type": "ephemeral"})
        self.log.write(event="request", finding_id=label, model=model, effort=effort, turn=conv["turn"],
                       messages=[_msg_log(m) for m in messages[conv["logged"]:]])
        conv["logged"] = len(messages)
        conv["turn"] += 1
        t0 = time.time()
        try:
            resp = self.backend.create(params)
        except Exception as e:
            self.log.write(event="error", finding_id=label, model=model, error=f"{type(e).__name__}: {e}"[:500],
                           latency_s=round(time.time() - t0, 3))
            raise
        usage = _usage(resp)
        served = getattr(resp, "model", None) or model
        cost = acfg.cost_usd(usage, served if served in acfg.PRICES else model)
        with self.lock:
            self.calls += 1
            self.cost += cost
            for k, v in usage.items():
                self.usage[k] += v
        self.budget.spend(usage)
        det = getattr(resp, "stop_details", None)
        self.log.write(event="response", finding_id=label, model=served, requested_model=model,
                       stop_reason=getattr(resp, "stop_reason", None),
                       stop_details={"category": getattr(det, "category", None),
                                     "explanation": getattr(det, "explanation", None)} if det else None,
                       content=[_block_log(b) for b in (getattr(resp, "content", None) or [])],
                       usage=usage, cost_usd=round(cost, 6), latency_s=round(time.time() - t0, 3))
        return resp

    def _overview(self):
        messages = [{"role": "user", "content": self.prefix + [{"type": "text", "text": prompts.OVERVIEW_REQUEST}]}]
        runner = tools.ToolRunner(self.ctx, None, self.fmap, self.s.image_max, allow_decision=False)
        conv = {"logged": 0, "turn": 0}
        try:
            for turn in range(2):
                if not self.budget.spare():
                    return None
                resp = self._call("overview", self.fast, self.s.fast_effort, messages, conv)
                if getattr(resp, "stop_reason", None) == "refusal":
                    return None
                blocks = list(getattr(resp, "content", None) or [])
                text = " ".join(b.text for b in blocks if getattr(b, "type", None) == "text").strip()
                uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
                if not uses or turn == 1:
                    return acfg.redact(text)[:1500] or None
                messages.append({"role": "assistant", "content": blocks})
                results = [tools.result_block(u.id, runner.run(u.name, u.input)) for u in uses]
                messages.append({"role": "user", "content": results + [{"type": "text",
                                                                        "text": prompts.OVERVIEW_FINISH}]})
        except Exception as e:  # noqa: BLE001 - the overview is optional context
            self.errors.append(acfg.redact(f"overview failed: {type(e).__name__}: {e}")[:300])
        return None

    def _finding_content(self, f, prep, runner, notes, escalation):
        x0, y0, x1, y1 = prep["region"]
        out_size = tools.fit_size(x1 - x0, y1 - y0, self.s.image_max,
                                  max(1.0, min(3.0, 768 / max(x1 - x0, y1 - y0))))
        block, meta = tools.encode_image(tools.to_pil(prep["pixels"], out_size), self.s.image_max)
        runner.crops.append({"kind": "evidence", "box": list(prep["region"]), **meta})
        content = [{"type": "text", "text": f"Image A - evidence crop: photo region {list(prep['region'])} shown at "
                                            f"{meta['size'][0]} x {meta['size'][1]} px."}, block]
        target = tools.normalize(str(f.get("target") or f.get("expected") or ""))
        if target and target in runner.vocab:
            try:
                dimg = self.ctx.drawing_crop(target)
            except Exception:  # noqa: BLE001 - optional evidence
                dimg = None
            if dimg is not None:
                dblock, dmeta = tools.encode_image(dimg, self.s.image_max)
                runner.crops.append({"kind": "drawing", "tag": target, **dmeta})
                content += [{"type": "text", "text": f"Image B - GA drawing around {target} (ground truth; a drawing, "
                                                     "not the photo)."}, dblock]
        content.append({"type": "text", "text": prompts.finding_message(f, notes, escalation)})
        return content

    def _verify_one(self, f, prep, notes):
        try:
            rec = self._loop(f, prep, notes, self.fast, self.s.fast_effort, first=True)
            if self._should_escalate(f, rec):
                rec2 = self._loop(f, prep, notes, self.main, self.s.effort, first=False,
                                  escalation=f"{rec['verdict']} at confidence {rec['confidence']:.2f}: {rec['reason']}")
                if rec2["source"] == "api":
                    rec2["escalated_from"] = {k: rec[k] for k in ("verdict", "confidence", "reason", "model")}
                    rec2["calls"] += rec["calls"]
                    rec2["crops"] = rec["crops"] + [c for c in rec2["crops"] if c not in rec["crops"]]
                    rec = rec2
                else:
                    rec["escalation"] = rec2["reason"]
            if rec["source"] == "api":
                self._cache_put(prep, rec)
                try:
                    self.backend.on_decision(self.sha, f["id"], prep["crop_sha"], rec)
                except Exception as e:  # noqa: BLE001 - recording is best effort
                    self.errors.append(f"recording failed: {e}"[:200])
        except Exception as e:  # noqa: BLE001 - one failed finding must not sink the photo
            msg = acfg.redact(f"agent error on {f['id']}: {type(e).__name__}: {e}")[:400]
            with self.lock:
                self.errors.append(msg)
            rec = self._record(unclear(f["id"], msg, f.get("hint")), self.fast, [], 0, "error")
        self.log.write(event="decision", finding_id=f["id"], **{k: rec.get(k) for k in (
            "verdict", "confidence", "reason", "evidence_boxes", "rephoto_hint", "model", "source", "calls")})
        self._emit(f, rec)
        return rec

    def _should_escalate(self, f, rec):
        if not self.s.escalate or rec["source"] != "api":
            return False
        if (self.main, self.s.effort) == (self.fast, self.s.fast_effort):
            return False
        strong = f.get("status") == "CANDIDATE_FAULT" and f.get("strength") == "strong"
        return strong and (rec["verdict"] == "UNCLEAR" or rec["confidence"] < 0.5)

    def _loop(self, f, prep, notes, model, effort, first, escalation=None):
        """One tool-use conversation about one finding; always returns a decision record."""
        fid = f["id"]
        runner = tools.ToolRunner(self.ctx, fid, self.fmap, self.s.image_max)
        runner.crops.append(self.overview_meta)
        opening = self.prefix + self._finding_content(f, prep, runner, notes, escalation)
        messages = [{"role": "user", "content": opening}]
        conv = {"logged": 0, "turn": 0}
        reprompted = retried = False
        tool_turns = calls = 0

        def give_up(reason, source, served=model):
            return self._record(unclear(fid, reason, f.get("hint")), served, runner.crops, calls, source)

        while True:
            ok = self.budget.start() if first and calls == 0 else self.budget.spare()
            if not ok:
                return give_up("agent budget exhausted", "budget")
            resp = self._call(fid, model, effort, messages, conv)
            calls += 1
            served = getattr(resp, "model", None) or model
            stop = getattr(resp, "stop_reason", None)
            if stop == "refusal":
                det = getattr(resp, "stop_details", None)
                cat, expl = getattr(det, "category", None), getattr(det, "explanation", None)
                return give_up(f"the model declined to answer (refusal{': ' + cat if cat else ''}"
                               f"{' - ' + expl if expl else ''})", "refusal", served)
            blocks = list(getattr(resp, "content", None) or [])
            uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
            messages.append({"role": "assistant", "content": blocks})
            if stop == "pause_turn" and not uses:
                continue
            if not uses:
                if reprompted:
                    return give_up("the agent answered without calling record_decision", "no_decision", served)
                reprompted = True
                messages.append({"role": "user", "content": [{"type": "text", "text": prompts.reprompt(fid)}]})
                continue
            results, decision, invalid = [], None, None
            for u in uses:                                  # parallel tool calls: run all, answer all together
                outcome = runner.run(u.name, u.input)
                if u.name == "record_decision":
                    if outcome.decision is not None:
                        decision = outcome.decision
                    else:
                        invalid = outcome.content
                results.append(tools.result_block(u.id, outcome))
            if decision is not None:
                source = "mock" if self.backend.name == "mock" else "api"   # mock answers are never cached
                return self._record(decision, served, runner.crops, calls, source, requested_model=model)
            if invalid is not None:
                if retried:
                    return give_up(f"invalid record_decision after one retry ({invalid})"[:600], "invalid", served)
                retried = True
            else:
                tool_turns += 1
            if tool_turns > self.s.max_turns:
                return give_up("tool-turn limit reached without a decision", "turn_limit", served)
            if tool_turns == self.s.max_turns:
                results.append({"type": "text", "text": prompts.LAST_TURN})
            messages.append({"role": "user", "content": results})
