"""FastAPI app for the MVP web UI.

Routes:
    GET  /                         redirect → /jobs
    GET  /jobs                     list of kept jobs (table)
    GET  /jobs/{job_id}            job detail + application editor
    POST /jobs/{job_id}/application save application fields
    POST /jobs/{job_id}/discard    move to discarded/
    GET  /discarded                list of rejected jobs
    POST /discarded/{job_id}/restore  move back to jobs/
    GET  /config                   config form
    POST /config                   save config
    GET  /run                      run page
    POST /run/start                kick off background scrape
    POST /run/start-rescrape       background scrape with --rescrape
    POST /run/login                background login (visible browser)
    POST /run/stop                 cancel current task
    GET  /run/status               JSON status (for HTMX polling)
    GET  /run/logs                 SSE log stream
"""

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from . import config_io, geocode, jobs_io
from .runner import DONE_SENTINEL, controller


BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="LinkedIn Scraper MVP")


# --- Helpers ---

def _ctx(**extra) -> dict:
    return {
        "is_running": controller.is_running,
        "run_state": controller.state,
        **extra,
    }


# --- Root ---

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/jobs", status_code=303)


# --- Jobs ---

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, q: str = ""):
    jobs = jobs_io.list_jobs(discarded=False)
    if q:
        ql = q.lower()
        def match(r: dict) -> bool:
            return any(
                (str(r.get(k) or "").lower().find(ql) >= 0)
                for k in ("job_title", "company", "location")
            )
        jobs = [j for j in jobs if match(j)]
    return templates.TemplateResponse(
        request, "jobs.html",
        _ctx(jobs=jobs, q=q, kind="kept",
             count_kept=len(jobs_io.list_jobs(discarded=False)),
             count_disc=len(jobs_io.list_jobs(discarded=True))),
    )


@app.get("/discarded", response_class=HTMLResponse)
async def discarded_page(request: Request, q: str = ""):
    jobs = jobs_io.list_jobs(discarded=True)
    if q:
        ql = q.lower()
        def match(r: dict) -> bool:
            return any(
                (str(r.get(k) or "").lower().find(ql) >= 0)
                for k in ("job_title", "company", "location")
            )
        jobs = [j for j in jobs if match(j)]
    return templates.TemplateResponse(
        request, "jobs.html",
        _ctx(jobs=jobs, q=q, kind="discarded",
             count_kept=len(jobs_io.list_jobs(discarded=False)),
             count_disc=len(jobs_io.list_jobs(discarded=True))),
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    rec, _ = jobs_io.get_job(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found")
    in_discarded = not rec.get("matched", True)
    return templates.TemplateResponse(
        request, "job_detail.html",
        _ctx(job=rec, in_discarded=in_discarded),
    )


@app.post("/jobs/{job_id}/application", response_class=HTMLResponse)
async def save_application(
    request: Request,
    job_id: str,
    status: str = Form(""),
    motivation_letter: str = Form(""),
    cv_version: str = Form(""),
    applied_at: str = Form(""),
    rejected_at: str = Form(""),
    accepted_at: str = Form(""),
    notes: str = Form(""),
    add_history_event: str = Form(""),
    history_notes: str = Form(""),
):
    rec = jobs_io.update_application(
        job_id,
        status=status,
        motivation_letter=motivation_letter,
        cv_version=cv_version,
        applied_at=applied_at,
        rejected_at=rejected_at,
        accepted_at=accepted_at,
        notes=notes,
        add_history_event=add_history_event or None,
        history_notes=history_notes or None,
    )
    if rec is None:
        raise HTTPException(status_code=404)
    jobs_io.regenerate_summaries()
    in_discarded = not rec.get("matched", True)
    return templates.TemplateResponse(
        request, "_application_card.html",
        _ctx(job=rec, in_discarded=in_discarded, saved=True),
    )


@app.post("/jobs/{job_id}/discard")
async def discard_job(job_id: str):
    jobs_io.discard(job_id)
    jobs_io.regenerate_summaries()
    return RedirectResponse("/jobs", status_code=303)


@app.post("/discarded/{job_id}/restore")
async def restore_job(job_id: str):
    jobs_io.restore_from_discarded(job_id)
    jobs_io.regenerate_summaries()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


# --- Map ---

@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse(request, "map.html", _ctx())


@app.get("/map/data")
async def map_data():
    """Return geocoded coords for kept and discarded jobs.

    Skips Remote-only jobs and jobs without a location string. Geocodes any
    uncached locations serially (1 req/sec) before responding — first load on
    a fresh dataset can take a few seconds, subsequent loads are instant.
    Each job carries a ``discarded`` flag so the client can show/hide layers.
    """
    kept = jobs_io.list_jobs(discarded=False)
    discarded = jobs_io.list_jobs(discarded=True)

    def _is_mappable(j: dict) -> bool:
        return bool(j.get("location")) and (j.get("workplace_type") or "") != "Remote"

    mappable = [(j, False) for j in kept if _is_mappable(j)] + \
               [(j, True) for j in discarded if _is_mappable(j)]

    remote_kept = sum(1 for j in kept if (j.get("workplace_type") or "") == "Remote")
    remote_disc = sum(1 for j in discarded if (j.get("workplace_type") or "") == "Remote")

    data_dir = jobs_io.store().data_dir
    coords = await geocode.geocode_locations(
        [j["location"] for j, _ in mappable], data_dir,
    )

    out = []
    unmapped_kept = 0
    unmapped_disc = 0
    for j, is_disc in mappable:
        c = coords.get(j["location"])
        if not c:
            if is_disc:
                unmapped_disc += 1
            else:
                unmapped_kept += 1
            continue
        out.append({
            "job_id": j.get("job_id"),
            "job_title": j.get("job_title"),
            "company": j.get("company"),
            "location": j.get("location"),
            "workplace_type": j.get("workplace_type"),
            "discarded": is_disc,
            "lat": c["lat"],
            "lon": c["lon"],
        })
    return JSONResponse({
        "jobs": out,
        "kept": {
            "total": len(kept),
            "mapped": sum(1 for j in out if not j["discarded"]),
            "unmapped": unmapped_kept,
            "remote": remote_kept,
        },
        "discarded": {
            "total": len(discarded),
            "mapped": sum(1 for j in out if j["discarded"]),
            "unmapped": unmapped_disc,
            "remote": remote_disc,
        },
    })


# --- Config ---

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, saved: bool = False, error: str = ""):
    cfg = config_io.load_raw()
    view = config_io.to_form_view(cfg)
    return templates.TemplateResponse(
        request, "config.html",
        _ctx(view=view, saved=saved, error=error),
    )


@app.post("/config")
async def save_config(request: Request):
    form = await request.form()
    try:
        new_cfg = config_io.from_form(form)
        if not new_cfg.get("searches"):
            raise ValueError("Add at least one search row.")
        config_io.save(new_cfg)
    except Exception as e:
        return RedirectResponse(f"/config?error={e}", status_code=303)
    return RedirectResponse("/config?saved=true", status_code=303)


# --- Run ---

@app.get("/run", response_class=HTMLResponse)
async def run_page(request: Request):
    return templates.TemplateResponse(
        request, "run.html",
        _ctx(status=controller.status()),
    )


@app.post("/run/start")
async def run_start():
    try:
        await controller.start_run(config_path=config_io.CONFIG_PATH, rescrape=False)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return RedirectResponse("/run", status_code=303)


@app.post("/run/start-rescrape")
async def run_rescrape():
    try:
        await controller.start_run(config_path=config_io.CONFIG_PATH, rescrape=True)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return RedirectResponse("/run", status_code=303)


@app.post("/run/login")
async def run_login():
    cfg = config_io.load_raw()
    session_file = Path(((cfg.get("scrape") or {}).get("session_file")) or "linkedin_session.json")
    try:
        await controller.start_login(session_file)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return RedirectResponse("/run", status_code=303)


@app.post("/run/stop")
async def run_stop():
    controller.cancel()
    return RedirectResponse("/run", status_code=303)


@app.get("/run/status")
async def run_status():
    return controller.status()


@app.get("/run/logs")
async def run_logs(request: Request):
    queue = controller.subscribe()

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
                    continue
                if line == DONE_SENTINEL:
                    yield {"event": "done", "data": ""}
                    break
                yield {"event": "log", "data": line}
        finally:
            controller.unsubscribe(queue)

    return EventSourceResponse(event_stream())
