"""
RVGL Live Scoreboard — FastAPI Backend
============================================
Granular race-by-race storage, rich aggregation engine,
live HTML dashboard, and Bulletproof Time Ladder Penalties.
"""

import asyncio
import csv
import io
import sqlite3
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


app = FastAPI(title="RVGL Live Scoreboard")
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "scoreboard.db"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

IDLE_TIMEOUT = 1200  
HOST_GRACE = 180     

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id              TEXT PRIMARY KEY,
                host_name       TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'Active',
                last_updated    REAL NOT NULL,
                last_host_ping  REAL NOT NULL,
                mode            TEXT DEFAULT '',
                tracks_played   INTEGER DEFAULT 0,
                version         TEXT DEFAULT '',
                connection      TEXT DEFAULT '',
                session_date    TEXT DEFAULT '',
                pickups         TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS races (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                track_name  TEXT NOT NULL,
                race_order  INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );
            CREATE TABLE IF NOT EXISTS race_results (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id       INTEGER NOT NULL,
                player_name   TEXT NOT NULL,
                car           TEXT NOT NULL,
                position      INTEGER NOT NULL,
                finished      INTEGER NOT NULL DEFAULT 1,
                time_str      TEXT DEFAULT '',
                best_lap_str  TEXT DEFAULT '',
                points_earned INTEGER DEFAULT 0,
                FOREIGN KEY (race_id) REFERENCES races(id)
            );
        """)

@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

@app.on_event("startup")
def on_startup():
    STATIC_DIR.mkdir(exist_ok=True)
    TEMPLATES_DIR.mkdir(exist_ok=True)
    init_db()

class UploadPayload(BaseModel):
    csv_content: str
    is_host: bool

def _time_to_ms(t: str) -> int:
    t = t.strip().strip('"')
    if not t or t == "—": return 0
    try:
        t = t.replace(".", ":") 
        parts = t.split(":")
        if len(parts) == 4:
            return int(parts[0])*3600000 + int(parts[1])*60000 + int(parts[2])*1000 + int(parts[3])
        elif len(parts) == 3:
            return int(parts[0])*60000 + int(parts[1])*1000 + int(parts[2])
    except Exception:
        pass
    return 0

def _ms_to_str(ms: int) -> str:
    if ms <= 0: return "—"
    hours = ms // 3600000
    ms %= 3600000
    minutes = ms // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}:{millis:03d}"

def _format_split(diff: int) -> str:
    if diff <= 0: return "—"
    if diff >= 60000:
        dm = diff // 60000
        ds = (diff % 60000) // 1000
        dms = diff % 1000
        return f"+{dm:02d}:{ds:02d}:{dms:03d}"
    else:
        ds = diff // 1000
        dms = diff % 1000
        return f"+{ds:02d}:{dms:03d}"

def _safe_int(val):
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0

def _parse_csv(csv_text: str):
    reader = csv.reader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        stripped = [c.strip() for c in row]
        if stripped:
            rows.append(stripped)

    host_name, mode, version, connection, date_str, pickups = "Unknown", "", "", "", "", ""
    laps = 1  
    races = []
    current_race = None

    for row in rows:
        tag = row[0].lower().strip('"') if row else ""
        if tag == "version":
            if len(row) >= 4:
                version = row[1].strip().strip('"')
                connection = f"{row[2].strip().strip('\"')} ({row[3].strip().strip('\"')})"
        elif tag == "session":
            if len(row) >= 6:
                date_str = row[1].strip().strip('"')
                host_name = row[2].strip().strip('"') if row[2].strip().strip('"') not in ("Server", "Client") else row[3].strip().strip('"')
                mode = row[3].strip().strip('"')
                laps = _safe_int(row[4].strip().strip('"'))
                pickups = "Enabled" if row[5].strip().strip('"').lower() == "true" else "Disabled"
            elif len(row) >= 5:
                date_str = row[1].strip().strip('"')
                raw2 = row[2].strip().strip('"')
                host_name = raw2 if raw2 not in ("Server", "Client") else row[3].strip().strip('"')
                mode = row[3].strip().strip('"')
                laps = _safe_int(row[4].strip().strip('"'))
        elif tag == "results":
            if current_race is not None:
                races.append(current_race)
            track = row[1].strip().strip('"') if len(row) >= 2 else "Unknown Track"
            csv_starters = _safe_int(row[2]) if len(row) >= 3 else 0 
            current_race = {"track": track, "starters": csv_starters, "players": []}
        elif current_race is not None and row[0].strip().strip('"').isdigit():
            if len(row) >= 6:
                time_str = row[3].strip().strip('"') if len(row) > 3 else ""
                best_lap = row[4].strip().strip('"') if len(row) > 4 else ""
                finished_val = row[5].strip().strip('"').lower() == "true"
                current_race["players"].append({
                    "position": _safe_int(row[0]),
                    "name": row[1].strip().strip('"'),
                    "car": row[2].strip().strip('"'),
                    "time_str": time_str,
                    "best_lap_str": best_lap,
                    "finished": finished_val,
                })

    if current_race is not None:
        races.append(current_race)

    # ── Master Roster Database Injection ──
    # Collects all names that raced at any point and injects them into missing races.
    # We leave time_str blank so the aggregator forces a severe penalty on them.
    player_cars = {}
    for race in races:
        for p in race["players"]:
            player_cars[p["name"]] = p["car"]

    for race in races:
        race_players = {p["name"]: p for p in race["players"]}
        for missing_name, car in player_cars.items():
            if missing_name not in race_players:
                race["players"].append({
                    "position": 99, 
                    "name": missing_name,
                    "car": car,
                    "time_str": "", 
                    "best_lap_str": "—",
                    "finished": False,
                })

    return host_name, mode, version, connection, date_str, pickups, races

@app.post("/api/session/upload")
async def upload_session(payload: UploadPayload):
    now = time.time()
    try:
        host_name, mode, version, connection, date_str, pickups, races = _parse_csv(payload.csv_content)
    except Exception:
        return JSONResponse({"error": "Failed to parse CSV"}, status_code=400)

    if not host_name or host_name == "Unknown":
        return JSONResponse({"error": "Could not determine host name"}, status_code=400)

    # Prevent CSV uploader from creating duplicate sessions if Coordinator is actively tracking this lobby
    with get_db() as conn:
        active_coord = conn.execute(
            "SELECT id FROM sessions WHERE status='Active' AND connection LIKE '%Coordinator%'",
        ).fetchone()
        if active_coord:
            return JSONResponse({"status": "ignored", "reason": "Coordinator SSE is actively tracking this match"})

    tracks_played = len(races)

    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE host_name = ? AND status = 'Active'", (host_name,)).fetchone()
        session_id = None
        if row:
            if now - row["last_updated"] > IDLE_TIMEOUT:
                conn.execute("UPDATE sessions SET status = 'Completed' WHERE id = ?", (row["id"],))
            else:
                session_id = row["id"]

        if session_id is None:
            session_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO sessions 
                (id, host_name, status, last_updated, last_host_ping, mode, tracks_played, version, connection, session_date, pickups) 
                VALUES (?, ?, 'Active', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, host_name, now, now, mode, tracks_played, version, connection, date_str, pickups)
            )
        else:
            if not payload.is_host:
                last_hp = row["last_host_ping"] if row else 0
                if now - last_hp <= HOST_GRACE:
                    return JSONResponse({"status": "ignored", "reason": "Host is active"})

        if payload.is_host:
            conn.execute("UPDATE sessions SET last_updated=?, last_host_ping=?, mode=?, tracks_played=?, version=?, connection=?, session_date=?, pickups=? WHERE id=?", (now, now, mode, tracks_played, version, connection, date_str, pickups, session_id))
        else:
            conn.execute("UPDATE sessions SET last_updated=?, mode=?, tracks_played=?, version=?, connection=?, session_date=?, pickups=? WHERE id=?", (now, mode, tracks_played, version, connection, date_str, pickups, session_id))

        old_race_ids = [r["id"] for r in conn.execute("SELECT id FROM races WHERE session_id=?", (session_id,)).fetchall()]
        if old_race_ids:
            placeholders = ",".join("?" * len(old_race_ids))
            conn.execute(f"DELETE FROM race_results WHERE race_id IN ({placeholders})", old_race_ids)
        conn.execute("DELETE FROM races WHERE session_id=?", (session_id,))

        for order, race in enumerate(races, start=1):
            starters = race["starters"]
            cur = conn.execute("INSERT INTO races (session_id, track_name, race_order) VALUES (?, ?, ?)", (session_id, race["track"], order))
            race_id = cur.lastrowid

            for p in race["players"]:
                pts = (starters - p["position"] + 1) if p["finished"] else 0
                if pts < 0: pts = 0
                conn.execute(
                    """INSERT INTO race_results (race_id, player_name, car, position, finished, time_str, best_lap_str, points_earned) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (race_id, p["name"], p["car"], p["position"], int(p["finished"]), p["time_str"], p["best_lap_str"], pts)
                )

    return JSONResponse({"status": "ok"})

@app.get("/api/session/{session_id}/json")
async def session_json(session_id: str):
    with get_db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)

        race_rows = conn.execute("SELECT * FROM races WHERE session_id=? ORDER BY race_order", (session_id,)).fetchall()
        all_results = []
        track_names = []
        race_track_map = {}
        track_counts = {}

        for r in race_rows:
            results = conn.execute("SELECT * FROM race_results WHERE race_id=? ORDER BY position", (r["id"],)).fetchall()
            base_name = r["track_name"]
            track_counts[base_name] = track_counts.get(base_name, 0) + 1
            if track_counts[base_name] > 1:
                unique_name = f"{base_name} ({track_counts[base_name]})"
            else:
                unique_name = base_name

            track_names.append(unique_name)
            race_track_map[r["id"]] = unique_name
            all_results.append((dict(r), [dict(res) for res in results]))

        # --- 1. Score Ladder (Multi-Car Tracking) ---
        player_stats = defaultdict(lambda: {
            "points": 0, "wins": 0, "races": 0, "tracks": {}, 
            "cars_used": set(), 
            "car_details": defaultdict(lambda: {"points": 0, "wins": 0, "races": 0, "tracks": {}})
        })
        
        for race, results in all_results:
            unique_track = race_track_map[race["id"]]
            for res in results:
                ps = player_stats[res["player_name"]]
                car = res["car"]
                
                # Overall Player Stats
                ps["points"] += res["points_earned"]
                if res["finished"]:
                    ps["races"] += 1
                ps["tracks"][unique_track] = res["points_earned"]
                ps["cars_used"].add(car)
                if res["position"] == 1 and res["finished"]:
                    ps["wins"] += 1
                    
                # Specific Car Stats
                cd = ps["car_details"][car]
                cd["points"] += res["points_earned"]
                if res["finished"]:
                    cd["races"] += 1
                cd["tracks"][unique_track] = res["points_earned"]
                if res["position"] == 1 and res["finished"]:
                    cd["wins"] += 1

        score_ladder = []
        for name, s in sorted(player_stats.items(), key=lambda x: (-x[1]["points"], -x[1]["wins"], x[0][::-1])):
            avg = round(s["points"] / s["races"], 2) if s["races"] > 0 else 0
            
            # Build the nested breakdown for the frontend
            car_breakdown = []
            for c_name, c_stats in s["car_details"].items():
                c_avg = round(c_stats["points"] / c_stats["races"], 2) if c_stats["races"] > 0 else 0
                car_breakdown.append({
                    "car": c_name,
                    "points": c_stats["points"],
                    "wins": c_stats["wins"],
                    "avg": c_avg,
                    "tracks": c_stats["tracks"]
                })
                
            score_ladder.append({
                "player_name": name, 
                "total_points": s["points"], 
                "wins": s["wins"], 
                "avg_points": avg, 
                "tracks": s["tracks"],
                "cars": list(s["cars_used"]),
                "car_breakdown": sorted(car_breakdown, key=lambda x: -x["points"]) # Sort best car to top
            })

        # --- 2. Track Boundaries ---
        track_best_ms = defaultdict(lambda: float('inf'))
        track_worst_ms = defaultdict(int)
        
        for race, results in all_results:
            unique_track = race_track_map[race["id"]]
            for res in results:
                ms = _time_to_ms(res["time_str"])
                if res["finished"] and ms > 0:
                    if ms < track_best_ms[unique_track]:
                        track_best_ms[unique_track] = ms
                    if ms > track_worst_ms[unique_track]:
                        track_worst_ms[unique_track] = ms

        # --- 3. Time Ladder (Fixed DNS Tagging) ---
        player_times = defaultdict(lambda: {"total_ms": 0, "tracks": {}})
        all_players = set()
        
        for race, results in all_results:
            for res in results:
                all_players.add(res["player_name"])

        for race, results in all_results:
            unique_track = race_track_map[race["id"]]
            best_for_track = track_best_ms[unique_track] if track_best_ms[unique_track] != float('inf') else 0
            worst_for_track = track_worst_ms[unique_track] if track_worst_ms[unique_track] != 0 else 60000 
            dnf_penalty_ms = worst_for_track + 30000 
            
            raced_this_track = {res["player_name"]: res for res in results}

            for player in all_players:
                pt = player_times[player]
                res = raced_this_track[player]
                ms = _time_to_ms(res["time_str"])
                
                # Check if this player was forcefully injected (DNS)
                is_dns = (not res["finished"] and not res["time_str"])
                
                if res["finished"] and ms > 0:
                    pt["total_ms"] += ms
                    if ms == best_for_track:
                        pt["tracks"][unique_track] = res["time_str"]
                    else:
                        pt["tracks"][unique_track] = _format_split(ms - best_for_track)
                elif is_dns:
                    pt["total_ms"] += dnf_penalty_ms
                    gap = dnf_penalty_ms - best_for_track if best_for_track > 0 else 0
                    pt["tracks"][unique_track] = f"DNS {_format_split(gap)}"
                else:
                    pt["total_ms"] += dnf_penalty_ms
                    gap = dnf_penalty_ms - best_for_track if best_for_track > 0 else 0
                    pt["tracks"][unique_track] = f"DNF {_format_split(gap)}"

        time_ladder_sorted = sorted(player_times.items(), key=lambda x: x[1]["total_ms"])
        first_total = time_ladder_sorted[0][1]["total_ms"] if time_ladder_sorted else 0

        time_ladder = []
        for name, t in time_ladder_sorted:
            total_str = _ms_to_str(t["total_ms"])
            split_ms = t["total_ms"] - first_total if first_total > 0 and t["total_ms"] > 0 else 0
            time_ladder.append({
                "player_name": name, 
                "total_time": total_str, 
                "split": _format_split(split_ms) if split_ms > 0 else "—", 
                "tracks": t["tracks"]
            })

        # --- 4. Car Stats ---
        car_data = defaultdict(lambda: {"score": 0, "races": 0, "wins": 0, "drivers": set()})
        for race, results in all_results:
            for res in results:
                c = car_data[res["car"]]
                c["score"] += res["points_earned"]
                if res["finished"]:
                    c["races"] += 1
                c["drivers"].add(res["player_name"])
                if res["position"] == 1 and res["finished"]: 
                    c["wins"] += 1

        car_stats = [{"car": car, "total_score": d["score"], "races": d["races"], "wins": d["wins"], "avg_points": round(d["score"] / d["races"], 2) if d["races"] > 0 else 0, "drivers": sorted(d["drivers"])} for car, d in sorted(car_data.items(), key=lambda x: -x[1]["score"])]

        # --- 5. Single Races (Fixed Ghost Filtering) ---
        single_races = []
        for race, results in all_results:
            unique_track = race_track_map[race["id"]]
            best_for_track = track_best_ms[unique_track] if track_best_ms[unique_track] != float('inf') else 0
            worst_for_track = track_worst_ms[unique_track] if track_worst_ms[unique_track] != 0 else 60000 
            dnf_penalty_ms = worst_for_track + 30000 

            # Sort finished players first, then DNF players
            sorted_results = sorted(results, key=lambda x: (0 if x["finished"] else 1, x["position"]))

            players = []
            for res in sorted_results:
                is_dns = (not res["finished"] and not res["time_str"])
                if is_dns:
                    continue

                ms = _time_to_ms(res["time_str"])
                
                if res["finished"] and ms > 0:
                    split_ms = ms - best_for_track
                    split_str = _format_split(split_ms) if res["position"] != 1 else "—"
                    display_time = res["time_str"]
                    display_rank = res["position"]
                else:
                    split_ms = dnf_penalty_ms - best_for_track if best_for_track > 0 else 0
                    split_str = f"DNF {_format_split(split_ms)}"
                    display_time = "DNF"
                    display_rank = "—"  # Shows '—' instead of '0' for DNF rank

                players.append({
                    "rank": display_rank, 
                    "name": res["player_name"], 
                    "car": res["car"],
                    "time": display_time, 
                    "split": split_str,
                    "best_lap": res["best_lap_str"] if res["finished"] else "—", 
                    "finished": bool(res["finished"]), 
                    "points": res["points_earned"],
                })
            single_races.append({"track": race["track_name"], "race_order": race["race_order"], "players": players})

        top_score = [{"name": s["player_name"], "value": s["total_points"]} for s in score_ladder[:3]]
        top_time = [{"name": t["player_name"], "value": t["total_time"]} for t in time_ladder[:3]]
        top_wins = [{"name": s["player_name"], "value": s["wins"]} for s in sorted(score_ladder, key=lambda x: (-x["wins"], -x["total_points"]))[:3]]

        # --- 6. Detect Random/Spec Car Session ---
        is_random_session = False
        valid_cars_per_race = []
        for race, results in all_results:
            # Gather all cars used in this race (ignoring DNS ghosts)
            race_cars = set(res["car"] for res in results if not (not res["finished"] and not res["time_str"]))
            if race_cars:
                valid_cars_per_race.append(race_cars)
                
        # If EVERY race had exactly 1 unique car used by all players...
        if valid_cars_per_race and all(len(c) == 1 for c in valid_cars_per_race):
            total_unique = set().union(*valid_cars_per_race)
            # ...and the cars changed across the session, it's a random lobby!
            if len(total_unique) > 1:
                is_random_session = True

    return JSONResponse({
        "session": dict(session), 
        "is_random_session": is_random_session, 
        "track_names": track_names, 
        "podiums": {"score": top_score, "time": top_time, "wins": top_wins}, 
        "score_ladder": score_ladder, 
        "time_ladder": time_ladder, 
        "car_stats": car_stats, 
        "single_races": single_races
    })

@app.get("/", response_class=HTMLResponse)
async def hub(request: Request):
    now = time.time()
    with get_db() as conn:
        # Mark inactive sessions (>20 min without updates) as Completed
        conn.execute("UPDATE sessions SET status='Completed' WHERE status='Active' AND ?-last_updated>1200", (now,))
        
        # Permanently purge sessions older than 1 hour (3600s)
        old_ids = [r["id"] for r in conn.execute("SELECT id FROM sessions WHERE ?-last_updated>3600", (now,)).fetchall()]
        if old_ids:
            ph = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM race_results WHERE race_id IN (SELECT id FROM races WHERE session_id IN ({ph}))", old_ids)
            conn.execute(f"DELETE FROM races WHERE session_id IN ({ph})", old_ids)
            conn.execute(f"DELETE FROM sessions WHERE id IN ({ph})", old_ids)

        # Query: Active non-coordinator sessions OR Completed sessions updated within the last 20 minutes (1200s)
        sessions = conn.execute(
            """SELECT * FROM sessions 
               WHERE (status='Active' AND connection NOT LIKE '%Coordinator%' AND version != 'Coordinator')
                  OR (status='Completed' AND ?-last_updated <= 1200)
               ORDER BY last_updated DESC""",
            (now,)
        ).fetchall()

        enriched = []
        for s in sessions:
            pc = conn.execute("SELECT COUNT(DISTINCT rr.player_name) as cnt FROM race_results rr JOIN races r ON rr.race_id=r.id WHERE r.session_id=?", (s["id"],)).fetchone()["cnt"]
            
            is_coord = "Coordinator" in (s["version"] or "") or "Coordinator" in (s["connection"] or "") or (len(s["id"]) > 20 and "-" not in s["id"])
            link = f"/coordinator/{s['id']}" if is_coord else f"/session/{s['id']}"

            enriched.append({
                "id": s["id"],
                "host_name": s["host_name"],
                "mode": s["mode"],
                "tracks_played": s["tracks_played"],
                "player_count": pc,
                "last_updated": s["last_updated"],
                "status": s["status"],
                "link": link
            })

    return templates.TemplateResponse(request=request, name="hub.html", context={"sessions": enriched})

@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_dashboard(request: Request, session_id: str):
    with get_db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session: return HTMLResponse("<h1>Session not found</h1>", status_code=404)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"session": dict(session)})


# =============================================================================
# Coordinator SSE Integration
# All routes below are strictly additive. CSV pipeline is untouched above.
# =============================================================================

COORDINATOR_BASE = "https://net.rv.gl/api/sessions"


@app.get("/api/coordinator/global-events")
async def proxy_global_events():
    """Proxies the global Coordinator SSE stream to bypass browser CORS."""
    upstream_url = f"{COORDINATOR_BASE}/events"

    async def event_generator():
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream("GET", upstream_url) as response:
                    async for line in response.aiter_lines():
                        yield f"{line}\n"
                        if line == "":
                            yield "\n"
            except (httpx.RemoteProtocolError, httpx.ReadError):
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class CoordinatorIngestPayload(BaseModel):
    coord_id: str
    lobby_name: str
    mode: str = "Arcade"
    car_rating: str = "Rookie"
    pickups: str = "Enabled"
    date_str: str = ""
    history: list


@app.get("/coordinator/{coord_id}", response_class=HTMLResponse)
async def coordinator_dashboard(request: Request, coord_id: str):
    """Serves the coordinator lobby page (matches Active or Completed sessions)."""
    with get_db() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE id=? OR host_name=?",
            (coord_id, f"coord:{coord_id}")
        ).fetchone()
    ctx = {
        "coord_id": coord_id,
        "session": dict(session) if session else None,
    }
    return templates.TemplateResponse(request=request, name="coordinator_dashboard.html", context=ctx)

@app.get("/api/coordinator/{coord_id}/events")
async def coordinator_events_proxy(coord_id: str):
    """
    Proxies the Coordinator lobby SSE stream to the browser.
    Handles keep-alive ping comments and forwards event: end for session termination.
    Uses httpx async streaming so the server never blocks.
    """
    upstream_url = f"{COORDINATOR_BASE}/{coord_id}/events"

    async def event_generator():
        # httpx timeout=None keeps the connection open indefinitely for SSE
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream("GET", upstream_url) as response:
                    async for line in response.aiter_lines():
                        # Forward every SSE line verbatim: data:, event:, and : ping comments
                        yield f"{line}\n"
                        # Blank line signals end of one SSE message block
                        if line == "":
                            yield "\n"
            except (httpx.RemoteProtocolError, httpx.ReadError):
                # Upstream closed — send a terminal event so the browser cleans up
                yield "event: end\n"
                yield 'data: {"reason":"session_ended"}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Prevents Nginx/proxies from buffering SSE chunks
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/coordinator/ingest")
async def coordinator_ingest(payload: CoordinatorIngestPayload):
    now = time.time()
    coord_session_key = f"coord:{payload.coord_id}"

    races = []
    player_cars: dict[str, str] = {}

    for entry in payload.history:
        track = entry.get("TrackName", entry.get("track", entry.get("Track", "Unknown Track")))
        results_raw = entry.get("Entries", entry.get("Results", entry.get("results", [])))
        starters = len(results_raw)

        race_players = []
        for result in results_raw:
            name = result.get("Name", result.get("name", "Unknown"))
            car = result.get("CarName", result.get("Car", result.get("car", "Unknown")))
            
            raw_time = result.get("TimeMS", result.get("Time", result.get("time", "")))
            if isinstance(raw_time, int):
                time_str = _ms_to_str(raw_time) if raw_time > 0 else ""
            else:
                time_str = str(raw_time)

            raw_best = result.get("BestLapMS", result.get("BestLap", result.get("best_lap", "")))
            if isinstance(raw_best, int):
                best_lap_str = _ms_to_str(raw_best) if raw_best > 0 else "—"
            else:
                best_lap_str = str(raw_best) if raw_best else "—"

            position = int(result.get("Position", result.get("position", 99)))
            finished_raw = result.get("Finished", result.get("finished", False))
            finished = finished_raw is True or str(finished_raw).lower() == "true"

            if position == 0 or not finished:
                position = 99

            player_cars[name] = car
            race_players.append({
                "position": position,
                "name": name,
                "car": car,
                "time_str": time_str,
                "best_lap_str": best_lap_str,
                "finished": finished,
            })

        # Skip aborted races where every player DNF'd
        if race_players and all(not p["finished"] for p in race_players):
            continue

        races.append({"track": track, "starters": starters, "players": race_players})

    # Master Roster Injection
    for race in races:
        race_player_names = {p["name"] for p in race["players"]}
        for missing_name, car in player_cars.items():
            if missing_name not in race_player_names:
                race["players"].append({
                    "position": 99,
                    "name": missing_name,
                    "car": car,
                    "time_str": "",
                    "best_lap_str": "—",
                    "finished": False,
                })

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=? OR host_name=?",
            (payload.coord_id, coord_session_key)
        ).fetchone()

        if row:
            session_id = row["id"]
            conn.execute(
                "UPDATE sessions SET host_name=?, last_updated=?, mode=?, version=?, tracks_played=?, pickups=?, session_date=? WHERE id=?",
                (payload.lobby_name, now, payload.mode, payload.car_rating, len(races), payload.pickups, payload.date_str, session_id)
            )
        else:
            session_id = payload.coord_id
            conn.execute(
                """INSERT INTO sessions
                (id, host_name, status, last_updated, last_host_ping, mode, tracks_played,
                 version, connection, session_date, pickups)
                VALUES (?, ?, 'Active', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, payload.lobby_name, now, now,
                 payload.mode, len(races), payload.car_rating, "Public (Coordinator)", payload.date_str, payload.pickups)
            )

        # Wipe and re-insert race results
        old_race_ids = [
            r["id"] for r in
            conn.execute("SELECT id FROM races WHERE session_id=?", (session_id,)).fetchall()
        ]
        if old_race_ids:
            ph = ",".join("?" * len(old_race_ids))
            conn.execute(f"DELETE FROM race_results WHERE race_id IN ({ph})", old_race_ids)
        conn.execute("DELETE FROM races WHERE session_id=?", (session_id,))

        for order, race in enumerate(races, start=1):
            starters = race["starters"]
            cur = conn.execute(
                "INSERT INTO races (session_id, track_name, race_order) VALUES (?, ?, ?)",
                (session_id, race["track"], order)
            )
            race_id = cur.lastrowid

            for p in race["players"]:
                pts = (starters - p["position"] + 1) if p["finished"] else 0
                if pts < 0:
                    pts = 0
                conn.execute(
                    """INSERT INTO race_results
                    (race_id, player_name, car, position, finished, time_str, best_lap_str, points_earned)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (race_id, p["name"], p["car"], p["position"],
                     int(p["finished"]), p["time_str"], p["best_lap_str"], pts)
                )

    return JSONResponse({"status": "ok", "session_id": session_id})

@app.post("/api/coordinator/{coord_id}/end")
async def coordinator_end(coord_id: str):
    """Marks a Coordinator session as Completed and updates last_updated timestamp."""
    now = time.time()
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET status='Completed', last_updated=? WHERE id=? OR host_name=?",
            (now, coord_id, f"coord:{coord_id}")
        )
    return JSONResponse({"status": "ended"})