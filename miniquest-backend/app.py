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
import re

load_dotenv()


app = Flask(__name__)
CORS(app)


FORBIDDEN_WORDS = [
    "kill", "die", "death", "blood", "gun", "knife", "hate",
    "ghost", "stupid", "dumb", "sex", "hell"
]

def contains_forbidden_words(text: str) -> bool:
    """Checks if a string contains any forbidden words (whole-word match, case-insensitive)."""
    return any(
        re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
        for word in FORBIDDEN_WORDS
    )

DB_FILE = "miniquest_v8.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
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

def init_event_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            quest_id INTEGER,
            child_id TEXT,
            turn_number INTEGER,
            latency_ms REAL,
            child_input TEXT,
            ai_response TEXT,
            additional_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def log_event(event_type: str, quest_id=None, child_id=None, turn_number=None, latency_ms=None,
              child_input=None, ai_response=None, additional_data=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO events 
        (event_type, quest_id, child_id, turn_number, latency_ms, child_input, ai_response, additional_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (event_type, quest_id, child_id, turn_number, latency_ms, child_input, ai_response,
          json.dumps(additional_data) if additional_data else None))
    conn.commit()
    conn.close()

@app.route("/log_event", methods=["POST"])
def log_event_api():
    data = request.get_json()
    event_type = data.get("eventType")
    quest_id = data.get("quest_id")
    child_id = data.get("child_id")
    turn_number = data.get("turn_number")
    latency_ms = data.get("latency_ms")
    child_input = data.get("child_input")
    ai_response = data.get("ai_response")
    additional_data = {k: v for k, v in data.items() if k not in ["eventType", "quest_id", "child_id",
                                                                  "turn_number", "latency_ms",
                                                                  "child_input", "ai_response"]}
    log_event(event_type, quest_id, child_id, turn_number, latency_ms, child_input, ai_response, additional_data)
    return jsonify({"status": "ok"})

def create_quest(user: str, initial_step_text: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    initial_state = {
        "branch": "start",
        "challenge_complete": False,
    }
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
    return { "state": state, "history": history, "created_at": quest_row['created_at'], "completed_at": quest_row['completed_at'] }

def update_quest_state(quest_id: int, new_state: dict):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE quests SET state_json = ? WHERE id = ?", (json.dumps(new_state), quest_id))
    conn.commit()
    conn.close()
    
def complete_quest(quest_id: int):
    """Marks a quest as completed with the current timestamp."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE quests SET completed_at = CURRENT_TIMESTAMP WHERE id = ?", (quest_id,))
    conn.commit()
    conn.close()

class QuestGraphState(TypedDict):
    quest_id: int; quest_data: dict; child_input: str; ai_response: str;

client = Groq()

def call_storyteller(prompt: str) -> str:
    try:
        chat_completion = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.1-8b-instant")
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error calling Groq API: {e}"); return "The storyteller is napping. Let's try again."


def re_prompt_node(state: QuestGraphState):
    return {"ai_response": "I didn't quite catch that. Do you want to go 'left' to the river or 'right' to the cave?"}

def cave_challenge_node(state: QuestGraphState):
    return {"ai_response": "You enter a cave with glowing crystals. On a pedestal, you see three gems: a red one, a blue one, and a green one. A tiny voice whispers, 'Touch the gem that is the color of a juicy apple.' Which one do you touch?"}

def cave_eval_node(state: QuestGraphState):
    child_input = state['child_input'].lower()
    quest_state = state['quest_data']['state']
    if "red" in child_input:
        quest_state["challenge_complete"] = True
        quest_state["branch"] = "cave_ending"
        update_quest_state(state['quest_id'], quest_state)
        return {"ai_response": "Yes! You touched the red gem. A secret door rumbles open, leading outside to a beautiful sunset! What a great discovery."}
    else:
        return {"ai_response": "That's not the one! The gem feels cold. Try touching a different color."}

def cave_ending_node(state: QuestGraphState):
    complete_quest(state['quest_id'])
    return {"ai_response": "You step through the secret door and see the wonderful sunset. You found the way through the mysterious cave! Congratulations on finishing your adventure."}

def river_challenge_node(state: QuestGraphState):
     return {"ai_response": "You arrive at a sparkling river where a friendly turtle is sunbathing. The turtle says, 'Hello! I have a fun riddle for you: I have a face and two hands, but no arms or legs. What am I?'"}

def river_eval_node(state: QuestGraphState):
    child_input = state['child_input'].lower()
    quest_state = state['quest_data']['state']
    if "clock" in child_input:
        quest_state["challenge_complete"] = True
        quest_state["branch"] = "river_ending"
        update_quest_state(state['quest_id'], quest_state)
        return {"ai_response": "You're so smart! The answer is a clock. The turtle is very impressed and shows you a secret path behind a waterfall that leads to a magical playground!"}
    else:
        return {"ai_response": "That's a good guess, but not quite! Remember, it has a face and hands. Do you want to try again?"}

def river_ending_node(state: QuestGraphState):
    complete_quest(state['quest_id'])
    return {"ai_response": "You slide down a mossy slide behind the waterfall and land in a grotto full of glowing bubbles. What a fun secret! Congratulations on finishing your adventure."}

def route_func(state: QuestGraphState) -> str:
    quest_state = state['quest_data']['state']
    child_input = state['child_input'].lower()
    branch = quest_state.get("branch", "start")
    challenge_complete = quest_state.get("challenge_complete", False)
    
    if challenge_complete:
        if 'cave' in branch:
            return "cave_ending_node"
        elif 'river' in branch:
            return "river_ending_node"
            
    if branch == "start":
        if "left" in child_input or "river" in child_input:
            quest_state['branch'] = 'river_challenge'
            update_quest_state(state['quest_id'], quest_state)
            return "river_challenge_node"
        elif "right" in child_input or "cave" in child_input:
            quest_state['branch'] = 'cave_challenge'
            update_quest_state(state['quest_id'], quest_state)
            return "cave_challenge_node"
        else:
            return "re_prompt_node"
            
    elif branch == 'cave_challenge': return "cave_eval_node"
    elif branch == 'river_challenge': return "river_eval_node"
    
    return "re_prompt_node"

graph_builder = StateGraph(QuestGraphState)
nodes = {
    "re_prompt_node": re_prompt_node,
    "cave_challenge_node": cave_challenge_node, "cave_eval_node": cave_eval_node, "cave_ending_node": cave_ending_node,
    "river_challenge_node": river_challenge_node, "river_eval_node": river_eval_node, "river_ending_node": river_ending_node,
}
for name, node in nodes.items():
    graph_builder.add_node(name, node)

node_name_map = {name: name for name in nodes.keys()}
graph_builder.add_conditional_edges(START, route_func, node_name_map)

for name in nodes:
    graph_builder.add_edge(name, END)

quest_graph = graph_builder.compile()


@app.route("/start", methods=["POST"])
def start_quest():
    user = request.json.get("user", "player1")
    initial_step = "Your MiniQuest begins in a magical forest! You see two paths. Will you take the 'left' path to a sparkling river, or the 'right' path to a mysterious cave?"
    quest_id = create_quest(user, initial_step)
    return jsonify({"quest_id": quest_id, "ai_response": initial_step})

@app.route("/turn", methods=["POST"])
def next_turn():
    data = request.get_json(); quest_id = data.get("quest_id"); child_input = data.get("child_input", "")
    if not quest_id: return jsonify({"error": "Missing 'quest_id'"}), 400
    if contains_forbidden_words(child_input): return jsonify({"ai_response": "Let's talk about something else! What's your favorite animal?"})
    
    quest_data = get_quest_data(quest_id)
    if not quest_data: return jsonify({"error": "Quest not found"}), 404
    
    graph_state = quest_graph.invoke({"quest_id": quest_id, "quest_data": quest_data, "child_input": child_input})
    ai_response = graph_state.get("ai_response", "Hmm, I seem to be lost in thought. Can you say that again?")
    
    if contains_forbidden_words(ai_response): 
        ai_response = "My mind went blank! Let's sing a happy song instead."
    
    add_quest_step(quest_id, ai_response, child_input)
    return jsonify({"quest_id": quest_id, "ai_response": ai_response})

@app.route("/dashboard/<int:quest_id>", methods=["GET"])
def get_dashboard_data(quest_id):
    quest_data = get_quest_data(quest_id)
    if not quest_data:
        return jsonify({"error": "Quest not found"}), 404

    time_on_task = "In progress"
    if quest_data.get("created_at") and quest_data.get("completed_at"):
        start = datetime.datetime.fromisoformat(quest_data["created_at"])
        end = datetime.datetime.fromisoformat(quest_data["completed_at"])
        duration = end - start
        time_on_task = f"{duration.seconds // 60}m {duration.seconds % 60}s"

    choices_made = []
    skills_tagged = set()
    quest_state = quest_data.get("state", {})
    branch = quest_state.get("branch", "")

    if "cave" in branch:
        choices_made.append({"choice": "Explored the cave", "skill": "Bravery"})
        skills_tagged.add("Bravery")
    elif "river" in branch:
        choices_made.append({"choice": "Visited the river", "skill": "Curiosity"})
        skills_tagged.add("Curiosity")

    if quest_state.get("cave_challenge_1_complete"):
        choices_made.append({"choice": "Solved the gem puzzle", "skill": "Problem-Solving"})
        skills_tagged.add("Problem-Solving")

    if quest_state.get("cave_challenge_2_complete"):
        choices_made.append({"choice": "Helped the dragon", "skill": "Kindness"})
        skills_tagged.add("Kindness")

    if quest_state.get("river_challenge_1_complete"):
        choices_made.append({"choice": "Solved the turtle's riddle", "skill": "Logic"})
        skills_tagged.add("Logic")

    if quest_state.get("river_challenge_2_complete"):
        choices_made.append({"choice": "Discovered the waterfall secret", "skill": "Creativity"})
        skills_tagged.add("Creativity")

    if not choices_made:
        choices_made.append({"choice": "No major choices made yet.", "skill": None})

    return jsonify({
        "time_on_task": time_on_task,
        "choices_made": choices_made,
        "skills_tagged": list(skills_tagged)
    })

@app.route("/recap/<int:quest_id>", methods=["POST"])
def generate_recap(quest_id):
    quest_data = get_quest_data(quest_id)
    if not quest_data or not quest_data['history']: return jsonify({"error": "Not enough data"}), 400
    history_text = "\n".join([f"Storyteller: \"{s['ai_response']}\"\nChild: \"{s['child_input']}\"" for s in quest_data['history']])
    prompt = f"Based on this transcript of a kids' game, write a simple, positive, 3-sentence story recap.\n\nTranscript:\n{history_text}\n\nRecap:"
    recap = call_storyteller(prompt)
    return jsonify({"recap": recap})

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "MiniQuest v8 backend is running!"})

if __name__ == "__main__":
    init_db()
    init_event_db()
    app.run(host="0.0.0.0", port=5000, debug=True)