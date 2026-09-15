# RVGL Live SessionScore

A real-time session scoring system for **Re-Volt GL (RVGL)** gaming sessions with comprehensive race analytics, live dashboards, and multi-car performance tracking.

🎮 **[Live Demo](https://rvgl-live-sessionscore.onrender.com/)**

---

## 📋 What It Does

RVGL Live SessionScore is a web-based application designed for RVGL gaming communities to:

- **Track Live Scores** – Monitor player points, rankings, and performance in real-time
- **Analyze Race Data** – Granular race-by-race storage with rich aggregation and filtering
- **Display Multi-Car Stats** – Per-car and per-driver performance breakdowns
- **Time Ladder Rankings** – Accurate time-based rankings with DNF penalties
- **Session Management** – Support for both CSV uploads and Coordinator SSE streaming
- **Beautiful Dashboards** – Clean HTML interface with sortable tables and responsive design

**Key Features:**
- ✅ Real-time score aggregation and player rankings
- ✅ Multi-car tracking per player with per-car statistics
- ✅ Time ladder with split times relative to race leader
- ✅ Automatic DNS/DNF penalty system with configurable thresholds
- ✅ Track boundary detection for comparative time analysis
- ✅ Both CSV and live-stream (Coordinator) data ingestion
- ✅ Session archival with automatic cleanup

---

## 🛠️ Technology Stack

| Component | Technologies |
|-----------|--------------|
| **Backend** | FastAPI, Python 3.7+ |
| **Database** | SQLite (local, no external dependency) |
| **Frontend** | HTML, CSS, JavaScript |
| **Deployment** | Render (or any Docker-compatible host) |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.7 or higher
- pip (Python package manager)
- Git

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/GaneshM2004/RVGL-Live-SessionScore.git
   cd RVGL-Live-SessionScore
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server:**
   ```bash
   python app.py
   ```
   
   The application will start on `http://localhost:8000` by default.

4. **Open your browser:**
   - Navigate to `http://localhost:8000` to see the session hub
   - Upload a CSV session file or connect to a live Coordinator stream

---

## 📖 Usage

### Session Hub
The main page displays:
- All active and recently completed sessions
- Player counts per session
- Mode and track information
- Quick links to individual session dashboards

### Session Dashboard
Each session provides:
- **Score Ladder** – Players ranked by total points with per-car breakdowns
- **Time Ladder** – Players ranked by cumulative time with DNF/DNS penalties
- **Car Statistics** – Performance data for each vehicle used in the session
- **Individual Races** – Detailed results for each race with splits and best lap times
- **Podiums** – Top 3 players in score, time, and wins categories

### Data Upload
Upload race data via CSV:
```bash
python client_uploader.py
```

This script sends race data to the backend for live tracking.

---

## 📁 Project Structure

```
RVGL-Live-SessionScore/
├── app.py                          # FastAPI backend server
├── client_uploader.py              # CSV uploader utility
├── launch_rvgl_online.bat          # Windows launcher script
├── requirements.txt                # Python dependencies
├── scoreboard.db                   # SQLite database (created at runtime)
│
├── templates/                      # Jinja2 HTML templates
│   ├── hub.html                    # Session listing page
│   ├── dashboard.html              # Session details page
│   └── coordinator_dashboard.html  # Live stream viewer (Coordinator)
│
├── static/                         # CSS and JavaScript assets
│   ├── css/
│   │   └── style.css              # Styling
│   └── js/
│       └── *.js                    # Frontend logic
│
└── session_*.csv                   # Sample session data
```

---

## 🔌 API Endpoints

### Session Management
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Session hub (list all sessions) |
| `/session/{session_id}` | GET | Session dashboard |
| `/api/session/{session_id}/json` | GET | Session data in JSON format |

### Data Upload
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/session/upload` | POST | Upload race data from CSV |

### Coordinator Integration
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/coordinator/{coord_id}` | GET | Live Coordinator lobby viewer |
| `/api/coordinator/ingest` | POST | Ingest Coordinator lobby data |
| `/api/coordinator/{coord_id}/events` | GET | SSE stream for live updates |
| `/api/coordinator/{coord_id}/end` | POST | Mark Coordinator session as completed |

---

## 📊 CSV Format

Upload race results using this CSV structure:

```csv
Version,Release,Network,Hosting
Session,Date,HostName/ServerName,GameMode,Laps,Pickups
Results,TrackName,NumberOfStarters
1,Player1,CarName,Time,BestLap,Finished
2,Player2,CarName,Time,BestLap,Finished
...
Results,Track2,NumberOfStarters
...
```

---

## ⚙️ Configuration

Key settings in `app.py`:

```python
IDLE_TIMEOUT = 1200      # 20 minutes - mark session as completed if inactive
HOST_GRACE = 180         # 3 minutes - grace period for host re-connection
```

### Time Format
Times are stored as milliseconds internally and formatted as:
- **Format:** `MM:SS:MS` or `HH:MM:SS:MS` (for times >= 1 hour)
- **Example:** `01:23:456` (1 minute, 23 seconds, 456 milliseconds)

### Scoring System
- **Points:** Calculated as `(starters - position + 1)` for finished races
- **DNF Penalty:** `worst_race_time + 30 seconds`
- **DNS (Did Not Start):** Player roster injected automatically for fairness

---

## 🚢 Deployment

### Render.com (Current Deployment)
The app is deployed at: https://rvgl-live-sessionscore.onrender.com/

To deploy your own:
1. Push to GitHub
2. Connect repository to Render.com
3. Set startup command: `uvicorn app:app --host 0.0.0.0`
4. Render will auto-scale the instance as needed

### Docker
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0"]
```

---

## 🤝 Contributing

Contributions are welcome! To contribute:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to your fork: `git push origin feature/your-feature`
5. Open a Pull Request

### Areas for Contribution
- Additional dashboard visualizations (charts, graphs)
- Performance optimizations for large sessions
- Mobile-responsive improvements
- Additional export formats (JSON, PDF)
- Unit tests and CI/CD pipelines

---

## 📝 License

This project is provided as-is for the RVGL community. Check the LICENSE file for details.

---

## 🆘 Support & Issues

- **Found a bug?** [Open an issue](https://github.com/GaneshM2004/RVGL-Live-SessionScore/issues)
- **Questions?** Check existing issues or create a new one with the `question` label
- **Feature requests?** Open an issue with the `enhancement` label

---

## 📞 Contact

- **Maintainer:** [GaneshM2004](https://github.com/GaneshM2004)
- **Live Demo:** https://rvgl-live-sessionscore.onrender.com/

---

## 🎮 About RVGL

**Re-Volt GL** is a community-driven 3D online racing game. Learn more at [Re-Volt.io](https://re-volt.io/)

---

**Status:** 🟢 Active Development  
**Last Updated:** 2026  
**Contributors:** Welcome!
