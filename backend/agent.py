# ── LehighLife AI — agent.py ──────────────────────────────────────────────────
# Run with: python agent.py
# Requires: pip install openai tavily-python gradio requests python-dotenv
# ─────────────────────────────────────────────────────────────────────────────

# ── SECTION 1: Imports & environment ─────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

import os
import json
import threading
import time
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from tavily import TavilyClient

# ── API credentials ───────────────────────────────────────────────────────────
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY      = os.getenv("TAVILY_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Email credentials ─────────────────────────────────────────────────────────
EMAIL_SENDER    = os.getenv("EMAIL_SENDER")     # your Gmail address
EMAIL_PASSWORD  = os.getenv("EMAIL_PASSWORD")   # Gmail App Password (16 chars)
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")  # student's email

client = OpenAI(api_key=OPENAI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

print("✅ Keys loaded")
print(f"   OpenAI:  {'✅' if OPENAI_API_KEY else '❌ MISSING'}")
print(f"   Tavily:  {'✅' if TAVILY_API_KEY else '❌ MISSING'}")
print(f"   Email:   {'✅' if EMAIL_SENDER and EMAIL_PASSWORD else '⚠️  not configured — email disabled'}")
print(f"   Discord: {'✅ (silent fallback)' if DISCORD_WEBHOOK_URL else '⚠️  not configured — skipping'}")


# ── SECTION 2: Student profile ────────────────────────────────────────────────
# Hardcoded demo student. Frontend updates this via UPDATE_PROFILE: prefix.
USER_PROFILE = {
    "name": "Alex",
    "major": "Computer Science",
    "year": "Junior",
    "social_mode": "introvert",          # "introvert" or "extrovert"
    "fitness_goals": ["eat more protein", "stay active"],
    "academic_goals": ["prep for OS exam", "find a study group for CSE 340"],
    "dietary_prefs": ["no pork", "high protein"],
    "deadlines": ["OS exam in 9 days", "Networks HW due Friday"]
}

print(f"\n✅ Profile loaded for: {USER_PROFILE['name']} ({USER_PROFILE['major']}, {USER_PROFILE['year']})")


# ── SECTION 3: System prompt ──────────────────────────────────────────────────
# Rebuilt on every call so profile changes are always reflected.

def build_system_prompt() -> str:
    return f"""
You are LehighLife, a proactive AI companion for Lehigh University students.

You know the following about this student:
- Name:               {USER_PROFILE['name']}
- Major / Year:       {USER_PROFILE['major']}, {USER_PROFILE['year']}
- Social style:       {USER_PROFILE['social_mode']}
- Fitness goals:      {', '.join(USER_PROFILE['fitness_goals'])}
- Academic goals:     {', '.join(USER_PROFILE['academic_goals'])}
- Dietary prefs:      {', '.join(USER_PROFILE['dietary_prefs'])}
- Upcoming deadlines: {', '.join(USER_PROFILE['deadlines'])}

Rules:
- Always search for current information before making any suggestion. Never guess.
- Reference the student's specific goals explicitly in every response.
- When you find something genuinely useful — a matching meal, event, or deadline
  reminder — send it as an email using the send_email tool.
- If social_mode is "introvert": surface smaller, quieter, academic events.
  Avoid suggesting large parties, loud venues, or crowded mixers.
- If social_mode is "extrovert": push social events, club fairs, group sessions.
- Be specific. Name the exact dish. Name the event. Give the time and location.
- Keep emails friendly, warm, and under 200 words.
- Do not send more than one email per proactive check.
"""

print("✅ System prompt ready")


# ── SECTION 4: Tools ──────────────────────────────────────────────────────────

# ── Tool 1: Web search ────────────────────────────────────────────────────────
def search_web(query: str) -> str:
    """Search for current Lehigh information using Tavily."""
    print(f"   🔍 Searching: {query}")
    results = tavily.search(
        query=f"Lehigh University {query}",
        max_results=3
    )
    output = []
    for r in results.get("results", []):
        output.append(f"Source: {r['url']}\n{r['content'][:400]}")
    return "\n\n---\n\n".join(output) if output else "No results found."


# ── Tool 2: Dining menu ───────────────────────────────────────────────────────
def get_dining_menu() -> str:
    """Fetch today's Rathbone dining hall menu and hours."""
    print("   🍽️  Fetching dining menu...")
    results = tavily.search(
        query="Rathbone dining hall Lehigh University menu today hours",
        max_results=3,
        include_domains=["lehigh.sodexomyway.com"]
    )
    output = []
    for r in results.get("results", []):
        output.append(f"Source: {r['url']}\n{r['content'][:500]}")
    return "\n\n---\n\n".join(output) if output else "Menu unavailable right now."


# ── Tool 3: Campus events ─────────────────────────────────────────────────────
def get_campus_events() -> str:
    """Fetch upcoming Lehigh campus events this week."""
    print("   📅 Fetching campus events...")
    results = tavily.search(
        query="Lehigh University upcoming campus events this week students",
        max_results=5,
        include_domains=["lehigh.campuslabs.com", "lehigh.edu"]
    )
    output = []
    for r in results.get("results", []):
        output.append(f"Source: {r['url']}\n{r['content'][:400]}")
    return "\n\n---\n\n".join(output) if output else "No events found."


# ── Tool 4: Parse syllabus ────────────────────────────────────────────────────
def parse_syllabus(text: str) -> str:
    """Extract exam dates and assignment deadlines from raw syllabus text."""
    print("   📄 Parsing syllabus...")
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": (
                "Extract all exam dates and assignment deadlines from this syllabus. "
                "Return ONLY valid JSON in this exact format, nothing else:\n"
                '{"course": "course name", '
                '"exams": [{"name": "...", "date": "..."}], '
                '"assignments": [{"name": "...", "due": "..."}]}\n\n'
                f"{text[:3000]}"
            )
        }],
        max_tokens=600
    )
    result = response.choices[0].message.content or "{}"

    # Update the live profile with parsed deadlines
    try:
        cleaned = result.replace("```json", "").replace("```", "").strip()
        parsed  = json.loads(cleaned)
        course  = parsed.get("course", "Unknown course")
        exams   = [f"{e['name']} on {e['date']}" for e in parsed.get("exams", [])]
        assigns = [f"{a['name']} due {a['due']}" for a in parsed.get("assignments", [])]
        new_deadlines = exams + assigns
        USER_PROFILE["deadlines"].extend(new_deadlines)
        print(f"   ✅ Parsed {len(exams)} exams + {len(assigns)} assignments for {course}")
        print(f"   📌 Added to profile: {new_deadlines}")
    except Exception as e:
        print(f"   ⚠️  Could not parse syllabus JSON: {e}")

    return result


# ── Tool 5: Send email (PRIMARY notification channel) ─────────────────────────
def send_email(subject: str, body: str) -> str:
    """
    Send a personalized nudge email directly to the student.
    Private and personal — not visible to anyone else.
    """
    sender    = EMAIL_SENDER
    password  = EMAIL_PASSWORD
    recipient = EMAIL_RECIPIENT

    if not sender or not password or not recipient:
        msg = (
            "⚠️  Email not configured. "
            "Add EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT to your .env file."
        )
        print(f"   {msg}")
        return msg

    print(f"   📧 Sending email to {recipient}...")
    print(f"      Subject: {subject}")

    msg = MIMEMultipart("alternative")
    msg["From"]    = f"LehighLife AI <{sender}>"
    msg["To"]      = recipient
    msg["Subject"] = subject

    # Plain text fallback
    msg.attach(MIMEText(body, "plain"))

    # HTML version — clean and on-brand
    html_body = f"""
    <div style="font-family: Georgia, serif; max-width: 520px; margin: 0 auto; color: #1a1a1a;">
      <div style="background: #3B1F0E; padding: 16px 24px; border-radius: 8px 8px 0 0;">
        <span style="color: #F5D99A; font-size: 18px; font-weight: bold;">&#127891; LehighLife</span>
        <span style="color: #C4952A; font-size: 13px; margin-left: 8px;">Your campus AI</span>
      </div>
      <div style="background: #FDFAF6; padding: 24px; border: 1px solid #e8e0d4; border-radius: 0 0 8px 8px;">
        <p style="font-size: 15px; line-height: 1.7; white-space: pre-wrap;">{body}</p>
        <hr style="border: none; border-top: 1px solid #e8e0d4; margin: 20px 0;">
        <p style="font-size: 12px; color: #999;">
          Sent by LehighLife AI &middot; Personalized for {USER_PROFILE['name']}
        </p>
      </div>
    </div>
    """
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())
        print(f"   ✅ Email sent successfully to {recipient}")
        return f"Email sent to {recipient} ✅"
    except smtplib.SMTPAuthenticationError:
        err = (
            "❌ Gmail auth failed — make sure EMAIL_PASSWORD is a 16-character "
            "App Password, not your regular Gmail password. "
            "Generate one at myaccount.google.com > Security > App passwords."
        )
        print(f"   {err}")
        return err
    except Exception as e:
        err = f"❌ Email failed: {str(e)}"
        print(f"   {err}")
        return err


# ── Discord: SILENT FALLBACK only — never exposed as an agent tool ─────────────
def _post_discord_silent() -> None:
    """
    Posts a generic status ping to Discord — no suggestion content.
    Competitors see only that your agent is alive, nothing about what it found.
    Called internally after each proactive check, never by the AI model.
    """
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        ping = (
            f"🟢 **LehighLife** agent heartbeat — "
            f"proactive check completed for {USER_PROFILE['name']}"
        )
        requests.post(DISCORD_WEBHOOK_URL, json={"content": ping}, timeout=5)
    except Exception:
        pass  # Discord failure never affects anything


# ── Register tools ─────────────────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search for current info about Lehigh courses, professors, events, dining, campus news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_dining_menu",
            "description": "Get today's live Rathbone dining hall menu, food stations, and hours at Lehigh University.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_campus_events",
            "description": "Get upcoming Lehigh University campus events this week. Use to find events matching the student's social preferences and goals.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "parse_syllabus",
            "description": "Parse raw syllabus text to extract exam dates and assignment deadlines. Automatically updates the student's profile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw text extracted from the syllabus PDF"
                    }
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send a personalized nudge email directly to the student. "
                "Use this whenever you find something relevant to their goals — "
                "a matching meal, a good event, an upcoming deadline reminder. "
                "This is the primary and preferred way to reach the student."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Email subject line — be specific, e.g. 'High-protein lunch at Rathbone today'"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body — warm, specific, under 200 words. Address student by name. Reference their goals."
                    }
                },
                "required": ["subject", "body"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "search_web":        search_web,
    "get_dining_menu":   get_dining_menu,
    "get_campus_events": get_campus_events,
    "parse_syllabus":    parse_syllabus,
    "send_email":        send_email,
}

print("\n✅ Tools registered:")
for name in TOOL_FUNCTIONS:
    print(f"   • {name}")


# ── SECTION 5: Core agent loop ────────────────────────────────────────────────

def run_agent(user_message: str, history: list) -> str:
    """
    Core agentic loop. Runs until the model stops calling tools.
    history: list of (human_msg, assistant_msg) tuples from Gradio.
    """

    # Handle special prefixes from the frontend
    if user_message.startswith("UPDATE_PROFILE:"):
        try:
            profile_json = user_message.replace("UPDATE_PROFILE:", "").strip()
            new_profile  = json.loads(profile_json)
            USER_PROFILE.update(new_profile)
            print(f"\n✅ Profile updated: {USER_PROFILE}")
            return f"Profile updated for {USER_PROFILE.get('name', 'student')} ✅"
        except Exception as e:
            return f"Could not update profile: {str(e)}"

    if user_message.startswith("PARSE_SYLLABUS:"):
        raw_text = user_message.replace("PARSE_SYLLABUS:", "").strip()
        return parse_syllabus(raw_text)

    # Build full message history
    messages = [{"role": "system", "content": build_system_prompt()}]
    for human, assistant in history:
        messages.append({"role": "user",      "content": human})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": user_message})

    print(f"\n🤖 Agent: {user_message[:80]}{'...' if len(user_message) > 80 else ''}")

    # Agentic tool-calling loop
    while True:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1000
        )
        message       = response.choices[0].message
        finish_reason = response.choices[0].finish_reason

        if finish_reason == "tool_calls":
            messages.append(message)
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                print(f"   🔧 {fn_name}({json.dumps(fn_args)[:80]})")
                fn     = TOOL_FUNCTIONS.get(fn_name)
                result = fn(**fn_args) if fn else f"Unknown tool: {fn_name}"
                messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result
                })
        else:
            reply = message.content or "No response."
            print(f"   ✅ Done: {reply[:80]}{'...' if len(reply) > 80 else ''}")
            return reply


print("✅ Agent loop ready")


# ── SECTION 6: Proactive background loop ─────────────────────────────────────

def proactive_check():
    """
    Wakes up every 30 minutes. Checks dining + events + deadlines.
    Emails the student directly. Posts only a silent heartbeat to Discord.
    This is what AgentStatus.dev verifies is genuinely running.
    """
    print("\n⏰ Proactive loop starting — first check in 15 seconds...")
    time.sleep(15)

    while True:
        print("\n" + "─" * 60)
        print("⏰ PROACTIVE CHECK")
        print("─" * 60)

        nudge_prompt = f"""
You are doing a proactive check for {USER_PROFILE['name']}.

Step 1: Call get_dining_menu.
        Find one specific meal matching their prefs: {USER_PROFILE['dietary_prefs']}
        and fitness goals: {USER_PROFILE['fitness_goals']}.

Step 2: Call get_campus_events.
        Their social mode is "{USER_PROFILE['social_mode']}" — filter accordingly.
        Academic goals: {USER_PROFILE['academic_goals']}.

Step 3: Check deadlines: {USER_PROFILE['deadlines']}.
        If anything is within 3 days, include a brief study nudge.

Step 4: Call send_email with:
        - Subject: something specific (name the meal or event)
        - Body: warm, personal, under 200 words
        - Address them as {USER_PROFILE['name']}
        - Cover the 1-2 most relevant things you found
        - Be specific: exact dish names, exact event names, exact times
        - Do NOT be generic or vague
"""
        try:
            run_agent(nudge_prompt, [])
            _post_discord_silent()
        except Exception as e:
            print(f"⚠️  Proactive check error: {e}")

        print(f"\n⏰ Next check in 30 minutes")
        print("─" * 60)
        time.sleep(1800)


proactive_thread = threading.Thread(target=proactive_check, daemon=True)
proactive_thread.start()
print("✅ Proactive email agent running in background (every 30 min)")


# ── SECTION 7: Gradio UI + API endpoints ─────────────────────────────────────
import gradio as gr
from fastapi import Request


def respond(message: str, history: list) -> str:
    return run_agent(message, history)


with gr.Blocks(title="LehighLife AI") as demo:
    gr.ChatInterface(
        fn=respond,
        title="🎓 LehighLife — Lehigh Campus AI",
        description=(
            f"Personalized campus companion for {USER_PROFILE['name']}. "
            "Ask about dining, events, or your upcoming deadlines."
        ),
        examples=[
            "What should I eat at Rathbone today?",
            "Find me a campus event that fits my vibe this week",
            "What should I study today given my deadlines?",
            "Email me a summary of today's best options",
            "What dining halls are open late tonight?",
        ],
    )

app = demo.app


# /predict — called by the frontend cards and AgentStatus.dev
@app.post("/predict")
async def predict_endpoint(request: Request):
    body    = await request.json()
    message = (
        body["data"][0]
        if isinstance(body.get("data"), list)
        else body.get("message", "ping")
    )
    result = run_agent(str(message), [])
    return {"data": [result]}


# /health — quick liveness check for AgentStatus.dev
@app.get("/health")
async def health():
    return {
        "status":  "ok",
        "agent":   "LehighLife",
        "student": USER_PROFILE["name"],
        "email":   "configured" if EMAIL_SENDER else "not configured",
        "tools":   list(TOOL_FUNCTIONS.keys())
    }


print("\n" + "═" * 60)
print("🚀 Launching LehighLife AI")
print("═" * 60)
print(f"   Student:  {USER_PROFILE['name']} — {USER_PROFILE['major']}, {USER_PROFILE['year']}")
print(f"   Email to: {EMAIL_RECIPIENT or '❌ NOT SET — add EMAIL_RECIPIENT to .env'}")
print(f"   Tools:    {', '.join(TOOL_FUNCTIONS.keys())}")
print("\n   ⬇️  Your public URL will appear below.")
print("   ⬇️  Give it to your frontend partner.\n")
print("═" * 60 + "\n")

demo.launch(
    share=True,
    debug=False,
    show_error=True
)