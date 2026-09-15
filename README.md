# RVGL Live SessionScore

A real-time session scoring system for Re-Volt GL (RVGL) gaming sessions with comprehensive race analytics, live dashboards, and multi-car performance tracking.

[Live Demo](https://rvgl-live-sessionscore.onrender.com/)

## Overview

RVGL Live SessionScore is a web-based application designed for RVGL gaming communities to track and analyze racing sessions. The system provides granular race-by-race storage with rich aggregation capabilities, beautiful HTML dashboards, and accurate scoring mechanics that handle edge cases like DNF (Did Not Finish) and DNS (Did Not Start) penalties.

### Key Features

- Real-time score aggregation and player rankings
- Multi-car tracking per player with per-car statistics
- Time ladder rankings with split times relative to race leaders
- Automatic DNS/DNF penalty system with configurable thresholds
- Track boundary detection for comparative time analysis
- Support for both CSV data uploads and live-stream Coordinator integration
- Session archival with automatic cleanup of old data
- Responsive HTML interface with sortable tables

## Technology Stack

- Backend: FastAPI, Python 3.7+
- Database: SQLite (local, no external dependencies)
- Frontend: HTML, CSS, JavaScript
- Deployment: Render.com (or any Docker-compatible host)

## Getting Started

### Prerequisites

- Python 3.7 or higher
- pip (Python package manager)
- Git

### Installation

1. Clone the repository:

```bash
git clone https://github.com/GaneshM2004/RVGL-Live-SessionScore.git
cd RVGL-Live-SessionScore
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the server:

```bash
python app.py
```

The application will start on `http://localhost:8000` by default.

4. Open your browser and navigate to `http://localhost:8000` to access the session hub.

## Usage

### Session Hub

The main page displays all active and recently completed sessions with:

- Player counts per session
- Game mode and track information
- Session status (Active or Completed)
- Quick links to individual session dashboards

### Session Dashboard

Each session provides detailed analytics including:

- Score Ladder: Players ranked by total points with per-car breakdowns
- Time Ladder: Players ranked by cumulative time with DNF/DNS penalties applied
- Car Statistics: Performance data for each vehicle used in the session
- Individual Races: Detailed results for each race with split times and best lap times
- Podiums: Top 3 players in score, time, and wins categories

### Uploading Data

To upload race data via CSV:

```bash
python client_uploader.py
```

The application accepts CSV files with race results and automatically parses session metadata, track information, and player performance data.

## Project Structure

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
└── static/                         # CSS and JavaScript assets
    ├── css/
    │   └── style.css              # Styling
    └── js/
        └── *.js                    # Frontend logic
```

## API Reference

### Session Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Retrieve session hub with all active sessions |
| `/session/{session_id}` | GET | Retrieve detailed dashboard for a specific session |
| `/api/session/{session_id}/json` | GET | Get session data in JSON format |

### Data Upload

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/session/upload` | POST | Upload race data from CSV file |

### Coordinator Integration

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/coordinator/{coord_id}` | GET | View live Coordinator lobby |
| `/api/coordinator/ingest` | POST | Ingest live Coordinator lobby data |
| `/api/coordinator/{coord_id}/events` | GET | Server-sent events stream for live updates |
| `/api/coordinator/{coord_id}/end` | POST | Mark Coordinator session as completed |

## CSV Data Format

The application expects race data in the following CSV structure:

```
Version,Release,Network,Hosting
Session,Date,HostName/ServerName,GameMode,Laps,Pickups
Results,TrackName,NumberOfStarters
1,Player1,CarName,Time,BestLap,Finished
2,Player2,CarName,Time,BestLap,Finished
...
Results,Track2,NumberOfStarters
...
```

Times should be formatted as `MM:SS:MS` or `HH:MM:SS:MS` for times exceeding one hour, where MS represents milliseconds.

## Configuration

Key settings can be adjusted in `app.py`:

- `IDLE_TIMEOUT = 1200`: Time in seconds before marking a session as completed (20 minutes)
- `HOST_GRACE = 180`: Grace period for host reconnection (3 minutes)

### Scoring System

Points are calculated using the formula: `(number_of_starters - position + 1)` for completed races.

For players who did not finish:
- DNF Penalty: worst race time plus 30 seconds
- DNS (Did Not Start): Automatically injected into race results to ensure fair comparative analysis

## Deployment

### Render.com

The application is currently deployed at https://rvgl-live-sessionscore.onrender.com/

To deploy your own instance:

1. Push your repository to GitHub
2. Connect your repository to Render.com
3. Set the startup command to: `uvicorn app:app --host 0.0.0.0`
4. Deploy and Render will automatically scale as needed

### Docker

Create a Dockerfile:

```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0"]
```

Then build and run:

```bash
docker build -t rvgl-scoreboard .
docker run -p 8000:8000 rvgl-scoreboard
```

## Contributing

Contributions are welcome. To contribute:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature-name`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to your fork: `git push origin feature/your-feature-name`
5. Open a pull request

Areas for contribution include additional dashboard visualizations, performance optimizations, mobile responsiveness improvements, and additional export formats.

## Issues and Support

For bug reports, feature requests, or questions, please open an issue on the GitHub repository.

## Repository

https://github.com/GaneshM2004/RVGL-Live-SessionScore

## About

RVGL Live SessionScore is a community tool designed to enhance the Re-Volt GL gaming experience by providing comprehensive race analytics and session tracking capabilities.
