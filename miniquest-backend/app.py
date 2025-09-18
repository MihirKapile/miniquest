import os
import io
import wave
import json
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from vosk import Model, KaldiRecognizer
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

# -----------------------------
# Flask app setup
# -----------------------------
app = Flask(__name__)
CORS(app, origins=["http://localhost:8081", "http://10.0.0.89:19000","http://10.0.0.89:5000"])

# -----------------------------
# SQLite Setup
# -----------------------------
DB_FILE = "miniquest.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS quests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            step TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            quest_id INTEGER,
            status TEXT,
            FOREIGN KEY (quest_id) REFERENCES quests(id)
        )
    ''')
    conn.commit()
    conn.close()

def save_progress(user, step_text):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO quests (step) VALUES (?)", (step_text,))
    quest_id = c.lastrowid
    c.execute("INSERT INTO progress (user, quest_id, status) VALUES (?, ?, ?)",
              (user, quest_id, "in_progress"))
    conn.commit()
    conn.close()
    return quest_id

def get_user_progress(user):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT quests.id, quests.step, progress.status
        FROM progress
        JOIN quests ON progress.quest_id = quests.id
        WHERE progress.user = ?
    """, (user,))
    rows = c.fetchall()
    conn.close()
    return [{"quest_id": r[0], "step": r[1], "status": r[2]} for r in rows]

# -----------------------------
# Vosk ASR Setup
# -----------------------------
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"
if not os.path.exists(VOSK_MODEL_PATH):
    raise Exception("Download Vosk model and unzip into project folder.")

vosk_model = Model(VOSK_MODEL_PATH)

def transcribe_audio(audio_bytes: bytes) -> str:
    wf = wave.open(io.BytesIO(audio_bytes), "rb")
    rec = KaldiRecognizer(vosk_model, wf.getframerate())
    rec.SetWords(True)
    results = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            res = json.loads(rec.Result())
            results.append(res.get("text", ""))
    final_res = json.loads(rec.FinalResult())
    results.append(final_res.get("text", ""))
    return " ".join(results).strip()

# -----------------------------
# LangGraph + Groq Setup
# -----------------------------
class QuestState(TypedDict):
    step: str
    user_input: str

# Initialize LLM
llm = Groq()

def miniquest_node(state: QuestState):
    user_input = state.get("user_input", "")
    prompt = f"You are a friendly quest master. The previous step was: '{state['step']}'. The player says: '{user_input}'. Continue the story in 1-2 sentences suitable for kids ages 5-9."
    response = llm(prompt=prompt, max_tokens=150)
    return {"step": response, "user_input": ""}  # reset input after processing

graph_builder = StateGraph(QuestState)
graph_builder.add_node("miniquest", miniquest_node)
graph_builder.add_edge(START, "miniquest")
graph_builder.add_edge("miniquest", END)
quest_graph = graph_builder.compile()

# -----------------------------
# API Routes
# -----------------------------

@app.route("/start", methods=["POST"])
def start_quest():
    user = request.form.get("user", "player1")
    initial_step = "Your MiniQuest begins in a magical forest. Which path will you take? Left or Right?"
    quest_id = save_progress(user, initial_step)
    return jsonify({"quest_id": quest_id, "step": initial_step})

@app.route("/turn", methods=["POST"])
def next_turn():
    """
    Accept live audio (WAV) from frontend, transcribe, run through LLM + graph, save step
    """
    user = request.form.get("user", "player1")
    audio_file = request.files.get("audio")
    previous_step = request.form.get("previous_step", "Your MiniQuest begins in a magical forest. Which path will you take? Left or Right?")

    if not audio_file:
        return jsonify({"error": "No audio uploaded"}), 400

    audio_bytes = audio_file.read()
    child_input = transcribe_audio(audio_bytes)

    # Run LangGraph node
    state = {"step": previous_step, "user_input": child_input}
    output_state = quest_graph.run(state)
    new_step = output_state["step"]

    quest_id = save_progress(user, new_step)

    return jsonify({
        "child_input": child_input,
        "ai_response": new_step,
        "quest_id": quest_id
    })

@app.route("/progress/<user>", methods=["GET"])
def progress(user):
    return jsonify(get_user_progress(user))

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "MiniQuest backend running"})

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
