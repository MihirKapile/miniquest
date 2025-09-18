from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

class State(TypedDict):
    messages: Annotated[list, add_messages]
    current_node: str

graph_builder = StateGraph(State)
llm = Groq()

def miniquest_node(state: State):
    user_input = state["messages"][-1]["content"] if state["messages"] else ""
    
    current_node = state.get("current_node", "start")
    if current_node == "start":
        if "left" in user_input.lower():
            next_node = "meet_fox"
            prompt = "A friendly fox appears! Solve this mini-challenge: 2+3=?"
        else:
            next_node = "find_treasure"
            prompt = "You find a treasure chest! Pick a color: red or blue?"
    elif current_node == "meet_fox":
        next_node = "end"
        prompt = "Congrats! You finished the MiniQuest."
    elif current_node == "find_treasure":
        next_node = "end"
        prompt = "Congrats! You finished the MiniQuest."
    else:
        next_node = "end"
        prompt = "Congrats! You finished the MiniQuest."
    
    response = llm(prompt=prompt, max_tokens=150)
    
    return {"messages": [{"role": "assistant", "content": response}], "current_node": next_node}

graph_builder.add_node("miniquest_node", miniquest_node)
graph_builder.add_edge(START, "miniquest_node")
graph_builder.add_edge("miniquest_node", END)
graph = graph_builder.compile()
