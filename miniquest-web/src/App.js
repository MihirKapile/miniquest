import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  const [questId, setQuestId] = useState(null);
  const [story, setStory] = useState([]);
  const [listening, setListening] = useState(false);

  const recognitionRef = useRef(null);

  useEffect(() => {
    if (!('webkitSpeechRecognition' in window)) {
      alert('Your browser does not support voice recognition. Please use Chrome.');
      return;
    }

    const recognition = new window.webkitSpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    recognition.onresult = async (event) => {
      const transcript = event.results[0][0].transcript;
      console.log('User said:', transcript);
      setStory(prev => [...prev, { speaker: 'Child', text: transcript }]);
      setListening(false);
      await sendTurn(transcript);
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      setListening(false);
    };

    recognitionRef.current = recognition;
  }, []);

  const startQuest = async () => {
    try {
      const res = await axios.post('http://10.0.0.89:5000/start', null, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        params: { user: 'player1' },
      });
      setQuestId(res.data.quest_id);
      setStory([{ speaker: 'AI', text: res.data.ai_response }]);
    } catch (err) {
      console.error(err);
    }
  };

  const startListening = () => {
    if (!recognitionRef.current) return;
    setListening(true);
    recognitionRef.current.start();
  };

  const sendTurn = async (childInput) => {
    try {
      const previousStep = story.length > 0 ? story[story.length - 1].text : '';
      const res = await axios.post('http://10.0.0.89:5000/turn', {
        user: 'player1',
        previous_step: previousStep,
        child_input: childInput,
      });
      setStory(prev => [...prev, { speaker: 'AI', text: res.data.ai_response }]);
      setQuestId(res.data.quest_id);
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="App" style={{ padding: 20 }}>
      <h1>MiniQuest Web (Voice)</h1>
      <button onClick={startQuest}>Start Quest</button>
      <button onClick={startListening} disabled={listening} style={{ marginLeft: 10 }}>
        {listening ? 'Listening...' : 'Speak'}
      </button>

      <div style={{ marginTop: 20 }}>
        {story.map((line, idx) => (
          <p key={idx} style={{ color: line.speaker === 'AI' ? 'blue' : 'green' }}>
            {line.speaker}: {line.text}
          </p>
        ))}
      </div>
    </div>
  );
}

export default App;
