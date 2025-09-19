import os
import json
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from langgraph.graph import StateGraph, START, END
from typing import TypedDict
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Flask app setup
# -----------------------------
app = Flask(__name__)
CORS(app) # Enable CORS for all routes

# -----------------------------
# SQLite Setup
# -----------------------------
DB_FILE = "miniquest.db"

def init_db():
    """Initializes the database and creates tables if they don't exist."""
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
    """Saves a quest step and the user's progress."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO quests (step) VALUES (?)", (step_text,))
    quest_id = c.lastrowid
    c.execute("INSERT INTO progress (user, quest_id, status) VALUES (?, ?, ?)",
              (user, quest_id, "in_progress"))
    conn.commit()
    conn.close()
    return quest_id

# -----------------------------
# LangGraph + Groq Setup
# -----------------------------
class QuestState(TypedDict):
    step: str
    user_input: str

client = Groq()

def miniquest_node(state: QuestState):
    """Generates the next step in the quest using the Groq LLM."""
    user_input = state.get("user_input", "")
    previous_step = state['step']
    
    print(f"Generating next step. Previous: '{previous_step}', User said: '{user_input}'")
    
    # Handle cases where transcription might fail or be empty
    if not user_input:
        return {"step": f"I didn't quite catch that. You are still at the part of the story where: '{previous_step}'. Please tell me what you would like to do.", "user_input": ""}

    prompt = f"You are a friendly and creative storyteller for a kids' audio adventure game called 'MiniQuest'. Your audience is children aged 5-9. Keep your responses brief (1-3 sentences) and always end with a question to prompt the player for their next action. The previous story beat was: '{previous_step}'. The player just said: '{user_input}'. What happens next?"
    
    chat_completion = client.chat.completions.create(
        messages=[{"role": "user", "content": prompt}],
        model="llama-3.1-8b-instant",
    )
    response = chat_completion.choices[0].message.content.strip()
    
    print(f"LLM Response: {response}")
    return {"step": response, "user_input": ""}

# Build the LangGraph
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
    initial_step = "Your MiniQuest begins in a magical forest filled with glowing mushrooms. You see two paths. Will you take the 'left' path towards a sparkling river, or the 'right' path towards a dark, mysterious cave?"
    quest_id = save_progress(user, initial_step)
    print(f"Starting new quest for {user}. Quest ID: {quest_id}")
    return jsonify({"quest_id": quest_id, "ai_response": initial_step, "child_input": "Game Started"})

@app.route("/turn", methods=["POST"])
def next_turn():
    # The endpoint now expects JSON data instead of form data with a file
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data received"}), 400

    user = data.get("user", "player1")
    previous_step = data.get("previous_step", "No previous step provided.")
    child_input = data.get("child_input", "")

    state = {"step": previous_step, "user_input": child_input}
    output_state = quest_graph.invoke(state)
    new_step = output_state["step"]

    quest_id = save_progress(user, new_step)

    return jsonify({
        "child_input": child_input,
        "ai_response": new_step,
        "quest_id": quest_id
    })

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "MiniQuest backend is running!"})

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)