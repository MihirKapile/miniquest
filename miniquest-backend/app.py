import os
import json
import sqlite3
import random
import datetime
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
CORS(app)

# -----------------------------
# Safety Filters
# -----------------------------
FORBIDDEN_WORDS = [
    "kill", "die", "death", "blood", "gun", "knife", "fight", "hate",
    "scary", "monster", "ghost", "stupid", "dumb", "sex", "hell"
]

def contains_forbidden_words(text: str) -> bool:
    """Checks if a string contains any forbidden words."""
    return any(word in text.lower() for word in FORBIDDEN_WORDS)

# -----------------------------
# SQLite Setup (V5 - with Timestamps)
# -----------------------------
DB_FILE = "miniquest_v5.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Added completed_at for session duration tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS quests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            state_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS quest_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quest_id INTEGER NOT NULL,
            step_number INTEGER NOT NULL,
            ai_response TEXT NOT NULL,
            child_input TEXT,
            FOREIGN KEY (quest_id) REFERENCES quests(id)
        )
    ''')
    conn.commit()
    conn.close()

# --- Database Helper Functions ---
# (create_quest, add_quest_step, get_quest_data, update_quest_state remain largely the same)

def create_quest(user: str, initial_step_text: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    initial_state = {"challenge": "none", "branch": "start"}
    c.execute("INSERT INTO quests (user, state_json) VALUES (?, ?)", (user, json.dumps(initial_state)))
    quest_id = c.lastrowid
    c.execute(
        "INSERT INTO quest_steps (quest_id, step_number, ai_response, child_input) VALUES (?, ?, ?, ?)",
        (quest_id, 1, initial_step_text, "Game Started")
    )
    conn.commit()
    conn.close()
    return quest_id

def add_quest_step(quest_id: int, ai_response: str, child_input: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT MAX(step_number) FROM quest_steps WHERE quest_id = ?", (quest_id,))
    next_step_number = (c.fetchone()[0] or 0) + 1
    c.execute(
        "INSERT INTO quest_steps (quest_id, step_number, ai_response, child_input) VALUES (?, ?, ?, ?)",
        (quest_id, next_step_number, ai_response, child_input)
    )
    # Update the 'completed_at' timestamp to mark the last interaction time
    c.execute("UPDATE quests SET completed_at = CURRENT_TIMESTAMP WHERE id = ?", (quest_id,))
    conn.commit()
    conn.close()

def get_quest_data(quest_id: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT state_json, created_at, completed_at FROM quests WHERE id = ?", (quest_id,))
    quest_row = c.fetchone()
    if not quest_row: return {}
    state = json.loads(quest_row['state_json'])
    c.execute("SELECT * FROM quest_steps WHERE quest_id = ? ORDER BY step_number ASC", (quest_id,))
    history_rows = c.fetchall()
    history = [dict(row) for row in history_rows]
    conn.close()
    return {
        "state": state,
        "history": history,
        "created_at": quest_row['created_at'],
        "completed_at": quest_row['completed_at']
    }

def update_quest_state(quest_id: int, new_state: dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE quests SET state_json = ? WHERE id = ?", (json.dumps(new_state), quest_id))
    conn.commit()
    conn.close()

# --- LangGraph Setup (remains the same as v4) ---
class QuestGraphState(TypedDict):
    quest_id: int; quest_data: dict; child_input: str; ai_response: str; next_node: str
client = Groq()
def call_storyteller(prompt: str) -> str:
    try:
        chat_completion = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.1-8b-instant")
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling Groq API: {e}"); return "The storyteller is napping. Let's try again."
def create_story_node(branch_prompt: str):
    def story_node(state: QuestGraphState):
        history = state['quest_data']['history']; child_input = state['child_input']
        history_summary = "\n".join([f"Story: {s['ai_response']}\nChild: {s['child_input']}" for s in history[-4:]])
        prompt = f"You are a friendly kids' storyteller for 'MiniQuest' (ages 5-9). Keep responses to 1-3 sentences and end with a question. Be fun and safe.\n--- STORY CONTEXT ---\n{branch_prompt}\n--- STORY SO FAR ---\n{history_summary}\nChild just said: '{child_input}'\n\nWhat happens next?"
        return {"ai_response": call_storyteller(prompt)}
    return story_node
river_node = create_story_node("The player is on the 'River Path', a place with sparkling water and friendly fish."); cave_node = create_story_node("The player is on the 'Cave Path', a not-so-scary cave with glowing crystals.");
def challenge_node(state: QuestGraphState):
    prompts = {"math": "Ask a simple addition question (e.g., 1+1).", "emotion": "Ask to name a feeling (e.g., 'What does happy feel like?').", "words": "Ask to name something of a color (e.g., 'Name something red.')."}
    challenge_type = state['quest_data']['state'].get("challenge_type", "math")
    return {"ai_response": call_storyteller(f"You are a friendly squirrel tutor. {prompts.get(challenge_type)}")}
def challenge_eval_node(state: QuestGraphState):
    return {"ai_response": call_storyteller(f"A child answered a challenge with: '{state['child_input']}'. Give a short, positive reply (e.g., 'Great job!') and say 'Now, back to our adventure!' and ask a new question to continue.")}
def router_node(state: QuestGraphState) -> dict:
    quest_data = state['quest_data']; quest_state = quest_data['state']; num_steps = len(quest_data['history']); child_input = state['child_input'].lower()
    next_node = "";
    if quest_state.get("challenge") == "pending": next_node = "challenge_eval_node"; quest_state['challenge'] = 'completed'
    elif num_steps >= 3 and num_steps % 3 == 0 and quest_state.get("challenge") != "completed": next_node = "challenge_node"; quest_state['challenge'] = 'pending'; quest_state['challenge_type'] = random.choice(['math', 'emotion', 'words'])
    elif quest_state.get("branch") == "start":
        if "left" in child_input or "river" in child_input: next_node = "river_node"; quest_state['branch'] = 'river'
        elif "right" in child_input or "cave" in child_input: next_node = "cave_node"; quest_state['branch'] = 'cave'
        else: next_node = "re_prompt_node"
    else: next_node = f"{quest_state.get('branch', 'river')}_node"
    update_quest_state(state['quest_id'], quest_state)
    return {"next_node": next_node}
def re_prompt_node(state: QuestGraphState): return {"ai_response": "I didn't quite catch that. Do you want to go 'left' to the river or 'right' to the cave?"}
def route_logic(state: QuestGraphState) -> str: return state.get("next_node", "re_prompt_node")
graph_builder = StateGraph(QuestGraphState); graph_builder.add_node("router", router_node); graph_builder.add_node("river_node", river_node); graph_builder.add_node("cave_node", cave_node); graph_builder.add_node("challenge_node", challenge_node); graph_builder.add_node("challenge_eval_node", challenge_eval_node); graph_builder.add_node("re_prompt_node", re_prompt_node)
graph_builder.add_edge(START, "router"); graph_builder.add_conditional_edges("router", route_logic, {"river_node": "river_node", "cave_node": "cave_node", "challenge_node": "challenge_node", "challenge_eval_node": "challenge_eval_node", "re_prompt_node": "re_prompt_node"});
graph_builder.add_edge("river_node", END); graph_builder.add_edge("cave_node", END); graph_builder.add_edge("challenge_node", END); graph_builder.add_edge("challenge_eval_node", END); graph_builder.add_edge("re_prompt_node", END)
quest_graph = graph_builder.compile()

# -----------------------------
# API Routes
# -----------------------------
@app.route("/start", methods=["POST"])
def start_quest():
    user = request.json.get("user", "player1")
    initial_step = "Your MiniQuest begins in a magical forest filled with glowing mushrooms. You see two paths. Will you take the 'left' path towards a sparkling river, or the 'right' path towards a dark, mysterious cave?"
    quest_id = create_quest(user, initial_step)
    return jsonify({"quest_id": quest_id, "ai_response": initial_step})

@app.route("/turn", methods=["POST"])
def next_turn():
    data = request.get_json(); quest_id = data.get("quest_id"); child_input = data.get("child_input", "")
    if not quest_id: return jsonify({"error": "Missing 'quest_id'"}), 400
    if contains_forbidden_words(child_input): return jsonify({"ai_response": "Let's talk about something else! What's your favorite color?"})
    quest_data = get_quest_data(quest_id)
    if not quest_data: return jsonify({"error": "Quest not found"}), 404
    graph_state = quest_graph.invoke({"quest_id": quest_id, "quest_data": quest_data, "child_input": child_input})
    ai_response = graph_state["ai_response"]
    if contains_forbidden_words(ai_response): ai_response = "My mind went blank! Let's sing a silly song instead."
    add_quest_step(quest_id, ai_response, child_input)
    return jsonify({"quest_id": quest_id, "ai_response": ai_response})

# --- NEW DASHBOARD ROUTES ---
@app.route("/dashboard/<int:quest_id>", methods=["GET"])
def get_dashboard_data(quest_id):
    quest_data = get_quest_data(quest_id)
    if not quest_data: return jsonify({"error": "Quest not found"}), 404

    # Calculate time on task
    time_on_task = "In progress"
    if quest_data.get("created_at") and quest_data.get("completed_at"):
        start = datetime.datetime.fromisoformat(quest_data["created_at"])
        end = datetime.datetime.fromisoformat(quest_data["completed_at"])
        duration = end - start
        time_on_task = f"{duration.seconds // 60} minutes, {duration.seconds % 60} seconds"

    # Extract choices and tagged skills
    choices_made = []
    skills_tagged = set()
    for step in quest_data['history']:
        child_input = (step.get('child_input') or "").lower()
        if "left" in child_input or "river" in child_input:
            choices_made.append({"choice": "Took the river path", "skill": "Curiosity"})
            skills_tagged.add("Curiosity")
        elif "right" in child_input or "cave" in child_input:
            choices_made.append({"choice": "Explored the cave", "skill": "Bravery"})
            skills_tagged.add("Bravery")

    # Simulate skill tagging for challenges
    quest_state = quest_data.get("state", {})
    if quest_state.get("challenge") == "completed":
        skill_map = {"math": "Problem-Solving", "emotion": "Empathy", "words": "Creativity"}
        challenge_type = quest_state.get("challenge_type", "math")
        skills_tagged.add(skill_map.get(challenge_type))
        
    return jsonify({
        "time_on_task": time_on_task,
        "choices_made": choices_made,
        "skills_tagged": list(skills_tagged)
    })

@app.route("/recap/<int:quest_id>", methods=["POST"])
def generate_recap(quest_id):
    quest_data = get_quest_data(quest_id)
    if not quest_data or not quest_data['history']:
        return jsonify({"error": "Not enough data to generate recap"}), 400
    
    history_text = "\n".join([f"Storyteller said: \"{s['ai_response']}\" then the child said: \"{s['child_input']}\"" for s in quest_data['history']])
    prompt = f"Based on the following transcript of a kids' adventure game, write a simple, positive, 3-sentence story recap. Pretend you are summarizing a storybook.\n\nTranscript:\n{history_text}\n\nRecap:"
    
    recap = call_storyteller(prompt)
    return jsonify({"recap": recap})

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "MiniQuest v5 backend is running!"})

# -----------------------------
# Run App
# -----------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)