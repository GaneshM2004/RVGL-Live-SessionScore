"""
RVGL Live Scoreboard — FastAPI Backend
============================================
Granular race-by-race storage, rich aggregation engine,
live HTML dashboard, and Bulletproof Time Ladder Penalties.
"""

import csv
import io
import sqlite3
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
        for r in race_rows:
            results = conn.execute("SELECT * FROM race_results WHERE race_id=? ORDER BY position", (r["id"],)).fetchall()
            all_results.append((dict(r), [dict(res) for res in results]))
            track_names.append(r["track_name"])

        # --- 1. Score Ladder (Multi-Car Tracking) ---
        player_stats = defaultdict(lambda: {
            "points": 0, "wins": 0, "races": 0, "tracks": {}, 
            "cars_used": set(), 
            "car_details": defaultdict(lambda: {"points": 0, "wins": 0, "races": 0, "tracks": {}})
        })
        
        for race, results in all_results:
            for res in results:
                ps = player_stats[res["player_name"]]
                car = res["car"]
                
                # Overall Player Stats
                ps["points"] += res["points_earned"]
                if res["finished"]:
                    ps["races"] += 1
                ps["tracks"][race["track_name"]] = res["points_earned"]
                ps["cars_used"].add(car)
                if res["position"] == 1 and res["finished"]:
                    ps["wins"] += 1
                    
                # Specific Car Stats
                cd = ps["car_details"][car]
                cd["points"] += res["points_earned"]
                if res["finished"]:
                    cd["races"] += 1
                cd["tracks"][race["track_name"]] = res["points_earned"]
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
            trk = race["track_name"]
            for res in results:
                ms = _time_to_ms(res["time_str"])
                if res["finished"] and ms > 0:
                    if ms < track_best_ms[trk]:
                        track_best_ms[trk] = ms
                    if ms > track_worst_ms[trk]:
                        track_worst_ms[trk] = ms

        # --- 3. Time Ladder (Fixed DNS Tagging) ---
        player_times = defaultdict(lambda: {"total_ms": 0, "tracks": {}})
        all_players = set()
        
        for race, results in all_results:
            for res in results:
                all_players.add(res["player_name"])

        for race, results in all_results:
            trk = race["track_name"]
            best_for_track = track_best_ms[trk] if track_best_ms[trk] != float('inf') else 0
            worst_for_track = track_worst_ms[trk] if track_worst_ms[trk] != 0 else 60000 
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
                        pt["tracks"][trk] = res["time_str"]
                    else:
                        pt["tracks"][trk] = _format_split(ms - best_for_track)
                elif is_dns:
                    pt["total_ms"] += dnf_penalty_ms
                    gap = dnf_penalty_ms - best_for_track if best_for_track > 0 else 0
                    pt["tracks"][trk] = f"DNS {_format_split(gap)}"
                else:
                    pt["total_ms"] += dnf_penalty_ms
                    gap = dnf_penalty_ms - best_for_track if best_for_track > 0 else 0
                    pt["tracks"][trk] = f"DNF {_format_split(gap)}"

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
            trk = race["track_name"]
            best_for_track = track_best_ms[trk] if track_best_ms[trk] != float('inf') else 0
            worst_for_track = track_worst_ms[trk] if track_worst_ms[trk] != 0 else 60000 
            dnf_penalty_ms = worst_for_track + 30000 

            players = []
            for res in results:
                # If they didn't finish and have no time recorded, they never started. Skip them!
                is_dns = (not res["finished"] and not res["time_str"])
                if is_dns:
                    continue

                ms = _time_to_ms(res["time_str"])
                
                if res["finished"] and ms > 0:
                    split_ms = ms - best_for_track
                    split_str = _format_split(split_ms) if res["position"] != 1 else "—"
                    display_time = res["time_str"]
                else:
                    split_ms = dnf_penalty_ms - best_for_track if best_for_track > 0 else 0
                    split_str = f"DNF {_format_split(split_ms)}"
                    display_time = "DNF"

                players.append({
                    "rank": res["position"], 
                    "name": res["player_name"], 
                    "car": res["car"],
                    "time": display_time, 
                    "split": split_str,
                    "best_lap": res["best_lap_str"] if res["finished"] else "—", 
                    "finished": bool(res["finished"]), 
                    "points": res["points_earned"],
                })
            single_races.append({"track": trk, "race_order": race["race_order"], "players": players})

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
        conn.execute("UPDATE sessions SET status='Completed' WHERE status='Active' AND ?-last_updated>1200", (now,))
        old_ids = [r["id"] for r in conn.execute("SELECT id FROM sessions WHERE ?-last_updated>3600", (now,)).fetchall()]
        if old_ids:
            ph = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM race_results WHERE race_id IN (SELECT id FROM races WHERE session_id IN ({ph}))", old_ids)
            conn.execute(f"DELETE FROM races WHERE session_id IN ({ph})", old_ids)
            conn.execute(f"DELETE FROM sessions WHERE id IN ({ph})", old_ids)
        sessions = conn.execute("SELECT * FROM sessions WHERE status='Active' ORDER BY last_updated DESC").fetchall()
        enriched = []
        for s in sessions:
            pc = conn.execute("SELECT COUNT(DISTINCT rr.player_name) as cnt FROM race_results rr JOIN races r ON rr.race_id=r.id WHERE r.session_id=?", (s["id"],)).fetchone()["cnt"]
            enriched.append({"id": s["id"], "host_name": s["host_name"], "mode": s["mode"], "tracks_played": s["tracks_played"], "player_count": pc, "last_updated": s["last_updated"]})
    return templates.TemplateResponse(request=request, name="hub.html", context={"sessions": enriched})

@app.get("/session/{session_id}", response_class=HTMLResponse)
async def session_dashboard(request: Request, session_id: str):
    with get_db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session: return HTMLResponse("<h1>Session not found</h1>", status_code=404)
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"session": dict(session)})