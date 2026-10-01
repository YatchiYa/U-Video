"""Background jobs for the API: renders, mixes, project creation, exports, QA, website analysis.

- A job is a record (kind, project, params, status, progress events, result) in a Store: Redis when REDIS_URL is
  set (Docker: api + worker containers share it), otherwise in memory (single-process dev: `ugc serve`).
- Two queues: "gpu" (one job at a time: the GPU can hold one model) and "light" (CPU jobs that must not wait behind
  a one-hour render).
- The worker runs every job in a subprocess (`python -m ugc_studio.jobs exec <id>`): a crash or an out-of-memory in
  a model can't take the worker down, and cancel really stops the work. The subprocess prints JSON lines
  (progress / result / error) that the worker turns into job events.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

QUEUE_OF = {"render": "gpu", "mix": "gpu", "create": "gpu", "persona": "gpu", "image": "gpu",
            "export": "light", "qa": "light", "site": "light", "preview": "light"}
TERMINAL = ("done", "failed", "cancelled")


def _now() -> float:
    return round(time.time(), 3)


# ====================================================================== stores
class MemoryStore:
    """In-process store (dev / tests). Thread-safe."""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._events: dict[str, list] = defaultdict(list)
        self._queues: dict[str, list[str]] = defaultdict(list)
        self._cancel: set[str] = set()
        self._lock = threading.Condition()
        self._beat = 0.0

    def save(self, job: dict) -> None:
        with self._lock:
            self._jobs[job["id"]] = dict(job)

    def get(self, jid: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(jid)
            return dict(j) if j else None

    def update(self, jid: str, **fields) -> None:
        with self._lock:
            self._jobs[jid].update(fields)
            self._lock.notify_all()

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(j) for j in self._jobs.values()]

    def add_event(self, jid: str, ev: dict) -> None:
        with self._lock:
            self._events[jid].append(ev)
            self._lock.notify_all()

    def events(self, jid: str, since: int = 0) -> list[dict]:
        with self._lock:
            return list(self._events[jid][since:])

    def push(self, queue: str, jid: str) -> None:
        with self._lock:
            self._queues[queue].append(jid)
            self._lock.notify_all()

    def pop(self, queue: str, timeout: float = 1.0) -> str | None:
        with self._lock:
            if not self._queues[queue]:
                self._lock.wait(timeout)
            return self._queues[queue].pop(0) if self._queues[queue] else None

    def remove_from_queue(self, queue: str, jid: str) -> bool:
        with self._lock:
            if jid in self._queues[queue]:
                self._queues[queue].remove(jid)
                return True
            return False

    def queued(self, queue: str) -> list[str]:
        with self._lock:
            return list(self._queues[queue])

    def request_cancel(self, jid: str) -> None:
        with self._lock:
            self._cancel.add(jid)

    def cancel_requested(self, jid: str) -> bool:
        with self._lock:
            return jid in self._cancel

    def heartbeat(self, info: dict | None = None) -> None:
        self._beat = time.time()
        if info is not None:
            self._info = info

    def worker_alive(self) -> bool:
        return time.time() - self._beat < 30

    def worker_info(self) -> dict:
        return getattr(self, "_info", {}) if self.worker_alive() else {}

    def ping(self) -> bool:
        return True


class RedisStore:
    """Shared store for the api and worker containers."""

    P = "ugc:"

    def __init__(self, url: str):
        import redis

        self.r = redis.Redis.from_url(url, decode_responses=True, socket_keepalive=True, health_check_interval=30,
                                      retry_on_timeout=True)

    def save(self, job: dict) -> None:
        self.r.set(f"{self.P}job:{job['id']}", json.dumps(job))
        self.r.zadd(f"{self.P}jobs", {job["id"]: job["created"]})

    def get(self, jid: str) -> dict | None:
        raw = self.r.get(f"{self.P}job:{jid}")
        return json.loads(raw) if raw else None

    def update(self, jid: str, **fields) -> None:
        key = f"{self.P}job:{jid}"
        with self.r.pipeline() as pipe:  # optimistic transaction: api and worker may update the same job
            while True:
                try:
                    pipe.watch(key)
                    job = json.loads(pipe.get(key))
                    job.update(fields)
                    pipe.multi()
                    pipe.set(key, json.dumps(job))
                    pipe.execute()
                    return
                except Exception as e:  # noqa: BLE001 - WatchError: retry
                    if type(e).__name__ != "WatchError":
                        raise

    def all(self) -> list[dict]:
        ids = self.r.zrevrange(f"{self.P}jobs", 0, 499)
        raws = self.r.mget([f"{self.P}job:{i}" for i in ids]) if ids else []
        return [json.loads(x) for x in raws if x]

    def add_event(self, jid: str, ev: dict) -> None:
        self.r.rpush(f"{self.P}events:{jid}", json.dumps(ev))

    def events(self, jid: str, since: int = 0) -> list[dict]:
        return [json.loads(x) for x in self.r.lrange(f"{self.P}events:{jid}", since, -1)]

    def push(self, queue: str, jid: str) -> None:
        self.r.rpush(f"{self.P}queue:{queue}", jid)

    def pop(self, queue: str, timeout: float = 1.0) -> str | None:
        import redis

        try:
            item = self.r.blpop([f"{self.P}queue:{queue}"], timeout=max(1, int(timeout)))
        except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError):  # e.g. after the host slept
            time.sleep(1)
            return None  # the worker loop simply asks again on a fresh connection
        return item[1] if item else None

    def remove_from_queue(self, queue: str, jid: str) -> bool:
        return bool(self.r.lrem(f"{self.P}queue:{queue}", 0, jid))

    def queued(self, queue: str) -> list[str]:
        return self.r.lrange(f"{self.P}queue:{queue}", 0, -1)

    def request_cancel(self, jid: str) -> None:
        self.r.set(f"{self.P}cancel:{jid}", "1", ex=86400)

    def cancel_requested(self, jid: str) -> bool:
        return bool(self.r.exists(f"{self.P}cancel:{jid}"))

    def heartbeat(self, info: dict | None = None) -> None:
        self.r.set(f"{self.P}worker", str(time.time()), ex=30)
        if info is not None:
            self.r.set(f"{self.P}worker_info", json.dumps(info), ex=30)
        else:
            self.r.expire(f"{self.P}worker_info", 30)

    def worker_alive(self) -> bool:
        return bool(self.r.exists(f"{self.P}worker"))

    def worker_info(self) -> dict:
        raw = self.r.get(f"{self.P}worker_info")
        return json.loads(raw) if raw else {}

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:  # noqa: BLE001
            return False


_STORE = None


def store():
    global _STORE
    if _STORE is None:
        url = os.environ.get("REDIS_URL", "").strip()
        _STORE = RedisStore(url) if url else MemoryStore()
    return _STORE


def set_store(s) -> None:  # tests / embedded dev worker
    global _STORE
    _STORE = s


# ====================================================================== API side
def submit(kind: str, project: str | None = None, params: dict | None = None) -> dict:
    if kind not in QUEUE_OF:
        raise ValueError(f"unknown job kind {kind!r}")
    s = store()
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "project": project, "params": params or {},
           "queue": QUEUE_OF[kind], "status": "queued", "created": _now(), "started": None, "finished": None,
           "stage": None, "message": "waiting for the worker", "result": None, "error": None, "events": 0}
    s.save(job)
    s.add_event(job["id"], {"t": job["created"], "event": "queued", "message": "queued"})
    s.push(job["queue"], job["id"])
    return job


def get(jid: str) -> dict | None:
    job = store().get(jid)
    if job and job["status"] == "queued":
        q = store().queued(job["queue"])
        job["position"] = q.index(jid) + 1 if jid in q else None
    return job


def list_jobs(project: str | None = None, limit: int = 50) -> list[dict]:
    jobs = [j for j in store().all() if project is None or j.get("project") == project]
    return sorted(jobs, key=lambda j: j["created"], reverse=True)[:limit]


def cancel(jid: str) -> dict:
    s = store()
    job = s.get(jid)
    if not job:
        raise KeyError(jid)
    if job["status"] in TERMINAL:
        return job
    if job["status"] == "queued" and s.remove_from_queue(job["queue"], jid):
        s.update(jid, status="cancelled", finished=_now(), message="cancelled before it started")
        s.add_event(jid, {"t": _now(), "event": "cancelled", "message": "cancelled"})
    else:
        s.request_cancel(jid)  # the worker kills the running subprocess
    return s.get(jid)


# ====================================================================== worker side
def _python() -> str:
    return os.environ.get("UGC_JOB_PYTHON") or sys.executable


def run_one(jid: str, s=None, poll: float = 0.5) -> dict:
    """Run a queued job in a subprocess, turning its JSON lines into events; honours cancel requests."""
    s = s or store()
    job = s.get(jid)
    if job is None or job["status"] != "queued":
        return job or {}
    s.update(jid, status="running", started=_now(), message="starting")
    s.add_event(jid, {"t": _now(), "event": "started", "message": "started"})
    from ugc_studio.config import OUTPUTS_DIR

    logs = OUTPUTS_DIR / "_jobs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{jid}.json").write_text(json.dumps(job))
    errlog = open(logs / f"{jid}.log", "w")  # noqa: SIM115 - closed below
    proc = subprocess.Popen([_python(), "-m", "ugc_studio.jobs", "exec", str(logs / f"{jid}.json")],
                            stdout=subprocess.PIPE, stderr=errlog, text=True, bufsize=1, start_new_session=True)
    lines: list[str] = []
    reader = threading.Thread(target=lambda: [lines.append(ln) for ln in proc.stdout], daemon=True)
    reader.start()
    result, error, n = None, None, 0
    cancelled = False
    while True:
        while n < len(lines):
            try:
                ev = json.loads(lines[n])
            except json.JSONDecodeError:
                ev = {"event": "log", "message": lines[n].strip()}
            n += 1
            ev.setdefault("t", _now())
            if ev.get("event") == "result":
                result = ev.get("data")
            elif ev.get("event") == "error":
                error = ev.get("message")
            else:
                s.add_event(jid, ev)
                if ev.get("event") == "progress":
                    s.update(jid, stage=ev.get("stage"), message=ev.get("message"))
        if proc.poll() is not None and not reader.is_alive():
            if n >= len(lines):
                break
            continue
        if not cancelled and s.cancel_requested(jid):
            cancelled = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        s.heartbeat()
        time.sleep(poll)
    errlog.close()
    code = proc.returncode
    if cancelled:
        s.update(jid, status="cancelled", finished=_now(), message="cancelled")
        s.add_event(jid, {"t": _now(), "event": "cancelled", "message": "cancelled"})
    elif code == 0 and error is None:
        s.update(jid, status="done", finished=_now(), result=result, message="done")
        s.add_event(jid, {"t": _now(), "event": "done", "message": "done"})
    else:
        if error is None:
            tail = (logs / f"{jid}.log").read_text()[-1500:]
            error = f"the job process exited with code {code}:\n{tail}"
        s.update(jid, status="failed", finished=_now(), error=error, message=error.splitlines()[0][:200])
        s.add_event(jid, {"t": _now(), "event": "failed", "message": error})
    return s.get(jid)


def work(queues: tuple[str, ...] = ("gpu", "light"), stop: threading.Event | None = None) -> None:
    """Worker: one loop per queue (gpu jobs never run two at a time)."""
    stop = stop or threading.Event()
    s = store()
    info = {"gpu": _gpu_name(), "queues": list(queues), "pid": os.getpid()}

    def loop(queue: str) -> None:
        while not stop.is_set():
            s.heartbeat(info)
            jid = s.pop(queue, timeout=2)
            if jid:
                try:
                    run_one(jid, s)
                except Exception as e:  # noqa: BLE001 - never let the worker die
                    log.exception("job %s crashed the runner", jid)
                    s.update(jid, status="failed", finished=_now(), error=str(e))

    threads = [threading.Thread(target=loop, args=(q,), daemon=True, name=f"worker-{q}") for q in queues]
    for t in threads:
        t.start()
    for t in threads:
        while t.is_alive() and not stop.is_set():
            t.join(1)


def _gpu_name() -> str | None:
    """The GPU this worker renders on (reported to the API: the API container itself has no GPU)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip().splitlines()[0] if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


# ====================================================================== job process
def _emit(event: str, **data) -> None:
    print(json.dumps({"event": event, "t": _now(), **data}, default=str), flush=True)


def execute(job: dict) -> Any:
    """The work itself (runs inside the job subprocess)."""
    from ugc_studio import service
    from ugc_studio.config import OUTPUTS_DIR

    kind, params = job["kind"], job["params"]
    folder = OUTPUTS_DIR / job["project"] if job.get("project") else None

    def progress(stage: str, msg: str) -> None:
        _emit("progress", stage=stage, message=msg)

    if kind == "render":
        from ugc_studio.engine import Studio

        st = Studio(folder, progress=progress, quality=params.get("quality"))
        res = st.build(only=params.get("only"), deliveries=tuple(params.get("deliveries") or ("web",)))
        out = {"deliveries": {k: str(v) for k, v in res.deliveries.items()}, "total": res.timeline.total,
               "warnings": res.warnings, "seconds": round(res.seconds, 1)}
        if params.get("qa", True) and res.deliveries:
            progress("qa", "quality check")
            out["qa"] = _qa(folder, next(iter(res.deliveries.values())))
        return out
    if kind == "mix":
        res = service.rebuild_mix(folder, progress)
        return {"deliveries": {k: str(v) for k, v in res.deliveries.items()}, "total": res.timeline.total,
                "warnings": res.warnings, "seconds": round(res.seconds, 1)}
    if kind == "create":
        return service.create_project(progress=progress, **params)
    if kind == "export":
        progress("export", params.get("format", "tv"))
        return {"file": str(service.export(folder, params.get("format", "tv"), params.get("at", 0.0)))}
    if kind == "qa":
        video = service.main_video(folder)
        if not video:
            raise service.ServiceError("render the project first")
        progress("qa", "quality check")
        return _qa(folder, video)
    if kind == "site":
        from ugc_studio import director as dr
        from ugc_studio import site

        progress("site", f"reading {params['url']}")
        out_dir = OUTPUTS_DIR / "_sites" / uuid.uuid4().hex[:8]
        info = site.analyze(params["url"], out_dir)
        return {"brand": dr.brand_from_site(info).model_dump(), "title": info.get("title"),
                "sections": info.get("h2", [])[:10], "ctas": info.get("ctas", [])[:10],
                "pages": len(info.get("links", [])), "folder": str(out_dir)}
    if kind == "persona":
        from ugc_studio import personas

        progress("persona", "creating the identity sheet")
        p = personas.create(params["name"], params["description"], params.get("images"),
                            params.get("voice_style", ""), params.get("language", "English"))
        return {"name": p.name, "images": p.images}
    if kind == "preview":
        return {"file": str(service.contact_sheet(folder))}
    raise ValueError(f"unknown job kind {kind!r}")


def _qa(folder: Path, video: Path) -> dict:
    from dataclasses import asdict

    from ugc_studio import service

    r = service.qa(folder, video)
    d = asdict(r) if hasattr(r, "__dataclass_fields__") else dict(r)
    d["verdict"] = r.verdict
    return d


def _main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "exec":
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
        job = json.loads(Path(argv[1]).read_text())
        try:
            _emit("result", data=execute(job))
            return 0
        except Exception as e:  # noqa: BLE001 - reported to the user as the job error
            logging.exception("job failed")
            _emit("error", message=str(e) or type(e).__name__)
            return 1
    print("usage: python -m ugc_studio.jobs exec <job.json>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
