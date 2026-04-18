# LehighLife AI — Product Requirements Document
**Agentathon 2025 · Lehigh University · 2-person team · 3-hour build**

---

## Overview

LehighLife is a personalized campus AI that knows a student's goals and acts on them without being asked. It watches dining menus and campus events in real time via Tavily, reasons against the student's profile (major, dietary needs, social comfort, upcoming deadlines), and proactively sends Discord nudges when it finds something relevant. AgentStatus.dev monitors the agent loop so judges can verify it's genuinely agentic.

> **The differentiator:** Every other team will edit the system prompt and demo Gradio. We show up with a branded frontend, live Discord feed, background agent loop, and AgentStatus verification.

---

## Stack

| Layer | Tool |
|---|---|
| Backend | Google Colab (`agentathon_final.ipynb`) |
| AI | OpenAI GPT-4o-mini with tool calling |
| Search/scraping | Tavily |
| Notifications | Discord webhook (already configured in starter kit) |
| Monitoring | AgentStatus.dev via `/predict` endpoint |
| Frontend | Single `index.html` file, vanilla JS, no build step |

---

## Architecture

### Frontend *(Person B owns)*
- Single `index.html` — open in browser, no install
- Onboarding flow saves profile to `localStorage`
- Dashboard with 3 suggestion cards + nudge feed
- Agent status dot that pings `/predict` every 60 seconds
- Syllabus PDF upload panel
- Connects to Colab via one `POST` to `/predict`

### Backend *(Person A owns)*
- `agentathon_final.ipynb` — modify existing 6 cells
- Add: `get_dining_menu` tool (Tavily)
- Add: `get_campus_events` tool (Tavily)
- Add: `parse_syllabus` tool
- Add: proactive loop cell (30-min background thread)
- `/predict` endpoint already exists — just verify it works

> The two halves are fully independent until integration. Frontend uses hardcoded placeholder data until Person A shares the Colab URL around the **45-minute mark**.

---

## Backend Specification

### Cell 3 — System Prompt *(REPLACE entirely)*

```python
USER_PROFILE = {
  "name": "Alex",
  "major": "Computer Science",
  "year": "Junior",
  "social_mode": "introvert",  # or "extrovert"
  "fitness_goals": ["eat more protein", "stay active"],
  "academic_goals": ["prep for OS exam", "find study group"],
  "dietary_prefs": ["no pork", "high protein"],
  "deadlines": ["OS exam in 9 days", "Networks HW due Friday"]
}

SYSTEM_PROMPT = f"""
You are LehighLife, a proactive AI companion for Lehigh University students.
Student profile: {USER_PROFILE}

Rules:
- Always search before making suggestions. Never guess.
- Reference the student's specific goals in every response.
- Post to Discord when you find something worth their attention.
- Introvert mode: suggest smaller, quieter, academic events.
- Extrovert mode: push socials, club fairs, group events.
- Be specific. Name the dish. Name the event. Give the time.
"""
```

---

### Cell 4 — Tools *(ADD three new tools, keep existing two)*

#### Tool: `get_dining_menu()`
- Calls `tavily.search()` with `include_domains=["lehigh.sodexomyway.com"]`
- Returns today's menu items, station names, and hours
- No parameters needed — agent decides when to call it
- Register in `TOOLS` list and `TOOL_FUNCTIONS` dict using same pattern as `search_web`

```python
def get_dining_menu() -> str:
    results = tavily.search(
        query="Rathbone dining hall Lehigh University menu today",
        max_results=3,
        include_domains=["lehigh.sodexomyway.com"]
    )
    output = []
    for r in results.get("results", []):
        output.append(f"{r['url']}\n{r['content'][:500]}")
    return "\n---\n".join(output) or "Menu unavailable."
```

#### Tool: `get_campus_events()`
- Calls `tavily.search()` targeting `lehigh.campuslabs.com`
- Returns event name, date, time, location, size cues
- Agent filters based on `social_mode` in the profile

```python
def get_campus_events() -> str:
    results = tavily.search(
        query="Lehigh University upcoming campus events this week",
        max_results=5,
        include_domains=["lehigh.campuslabs.com", "lehigh.edu"]
    )
    output = []
    for r in results.get("results", []):
        output.append(f"{r['url']}\n{r['content'][:400]}")
    return "\n---\n".join(output) or "No events found."
```

#### Tool: `parse_syllabus(text: str)`
- Accepts raw text extracted from a PDF
- Prompts the model to return structured deadlines
- Updates `USER_PROFILE["deadlines"]` with the result

```python
def parse_syllabus(text: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": f"Extract all exam dates and assignment deadlines from this syllabus. Return as JSON: {{course, exams: [{{name, date}}], assignments: [{{name, due}}]}}.\n\n{text[:3000]}"
        }],
        max_tokens=500
    )
    result = response.choices[0].message.content
    USER_PROFILE["deadlines"].append(f"Parsed from syllabus: {result[:200]}")
    return result
```

Register all three in `TOOLS` and `TOOL_FUNCTIONS`.

---

### Cell 4.5 — Proactive Loop *(ADD as a new cell — MOST IMPORTANT)*

This is what makes the agent genuinely agentic and what AgentStatus.dev verifies. Runs in a background daemon thread so Gradio still works simultaneously.

```python
import threading, time

def proactive_check():
    while True:
        nudge_prompt = f"""
        Proactive check for {USER_PROFILE['name']}.
        1. Call get_dining_menu — find one meal matching {USER_PROFILE['dietary_prefs']}
        2. Call get_campus_events — find one event matching {USER_PROFILE['social_mode']} preference
        3. Check these deadlines: {USER_PROFILE['deadlines']}
        Pick the 1-2 most relevant things and post a short personalized nudge to Discord.
        Keep it under 150 words. Be specific — name the dish, name the event, give the time.
        """
        run_agent(nudge_prompt, [])
        time.sleep(1800)  # every 30 minutes

thread = threading.Thread(target=proactive_check, daemon=True)
thread.start()
print("Proactive agent running in background")
```

---

### Cell 6 — `/predict` Endpoint *(already exists, just verify it works)*

After launching, immediately test with:

```bash
curl -X POST {YOUR_SHARE_URL}/predict \
  -H "Content-Type: application/json" \
  -d '{"data": ["What dining halls are open right now?"]}'
```

Share this URL with Person B as soon as it works.

---

## Frontend Specification

### Screen Flow

1. **Landing** — app name, tagline, Get Started button. Lehigh brown/gold theme.
2. **Onboarding Step 1** — name, major, year, social slider (introvert to extrovert)
3. **Onboarding Step 2** — fitness goal chips, dietary preference chips, academic goals text input
4. **Onboarding Step 3** — optional syllabus PDF upload, shows parsed deadlines as chips, skip link
5. **Dashboard** — main screen with suggestion cards, nudge feed, status dot, chat

---

### Dashboard Components

#### 🍽️ Meal Card
- On load: `POST` to `/predict` — *"What should I eat at Rathbone today given [dietary_prefs] and [fitness_goals]?"*
- Displays: dish name, station, hours, one sentence explaining why it fits their goals
- Refresh button re-calls `/predict`

#### 📅 Event Card
- On load: `POST` to `/predict` — *"What Lehigh event this week best fits someone who is [social_mode] and wants to [academic/social goals]?"*
- Displays: event name, date and time, location, one sentence on why it matches
- Introvert mode naturally surfaces smaller academic events via the system prompt

#### 📚 Study Nudge Card
- On load: `POST` to `/predict` — *"Given these deadlines [deadlines], what is the single most important thing I should focus on academically today?"*
- Displays: specific task, time estimate, urgency indicator

#### 🔔 Live Nudge Feed *(right panel or bottom)*
- Shows last 5 suggestions the agent has generated
- Stored in `localStorage` so it persists on refresh
- Each entry has: timestamp, category icon (meal/event/study), short text summary
- Populated every time any `/predict` call returns a response

#### 🟢 Agent Status Dot *(top nav)*
- Small colored circle in the header
- Every 60 seconds: `POST` a simple ping (`"Are you running?"`) to `/predict`
- Response within 5 seconds = 🟢 green dot
- Response after 5 seconds = 🟡 yellow dot
- No response = 🔴 red dot
- This is AgentStatus.dev's concept made visible in the UI

---

### Visual Design

| Token | Value |
|---|---|
| Primary color | `#3B1F0E` (deep Lehigh brown) |
| Accent color | `#C4952A` (Lehigh gold) |
| Background | `#FDFAF6` (warm off-white) |
| Cards | White background, subtle border, gold left-side accent stripe |
| Headings | Georgia serif |
| Body | system-ui |
| Icons | Emoji only — no icon library needed |

- **Onboarding:** full-screen centered steps, gold progress bar at top

---

### Syllabus PDF Upload

Use the browser `FileReader` API plus `pdf.js` from cdnjs to extract text client-side. Send to `/predict` with the prefix `"PARSE_SYLLABUS: "` followed by the raw text. Display the returned deadlines as removable chips on the onboarding screen. These chips feed into the study nudge card.

---

## Integration Contract

The frontend and backend share exactly **one interface**.

### Request
```
POST to {COLAB_SHARE_URL}/predict
Body: {"data": ["your message here"]}
Content-Type: application/json
No auth required
```

### Response
```
HTTP 200: {"data": ["response string"]}
Response time: 3–8 seconds — always show a loading spinner
Any non-200 = agent is down, show red status dot
```

### Special Message Prefixes
| Prefix | Action |
|---|---|
| `"PARSE_SYLLABUS: {raw text}"` | Backend calls `parse_syllabus` tool, returns JSON deadlines |
| `"UPDATE_PROFILE: {json}"` | Backend updates `USER_PROFILE` dict in memory |

---

## Build Timeline

### 0:00–0:20
- **Person A:** Replace system prompt in Cell 3. Hardcode demo student profile. Run Colab top to bottom and confirm it works.
- **Person B:** Build landing page and onboarding Step 1 with name, major, and social slider.

### 0:20–0:45
- **Person A:** Add `get_dining_menu` tool. Test live Tavily call. Confirm Discord message fires.
- **Person B:** Build onboarding Steps 2 and 3. Wire Finish button to save profile to `localStorage`.

### 0:45–1:15
- **Person A:** Add `get_campus_events` tool. Add proactive loop cell and run it once manually. Confirm Discord message appears. **Share Colab URL with Person B.**
- **Person B:** Build dashboard with 3 placeholder cards and nudge feed. Start wiring to `/predict` once URL arrives.

### 1:15–1:40
- **Person A:** Add `parse_syllabus` tool. Test with sample PDF text. Add second demo student profile for variety.
- **Person B:** Add syllabus upload on onboarding Step 3. Add agent status dot with 60-second ping. Run live end-to-end test.

### 1:40–2:00
- **Person A:** Polish console logs for demo visibility. Confirm AgentStatus.dev can reach `/predict`.
- **Person B:** Polish styling, add loading states to cards, check Chrome rendering.

### 2:00–3:00
- **Both:** Full demo run-throughs. Practice script. Fix whatever breaks. Buffer for surprises.
