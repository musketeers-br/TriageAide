# ADAPTATION INSTRUCTION: ELEVENLABS CONVAI INTEGRATION (STT/TTS) IN THE CURRENT PROJECT

You are a senior software engineer specialized in Python ecosystems, FastAPI/Flask, and Gradio. Your task is to analyze our current code structure (API and local Agents) and implement the necessary modifications to integrate it with the ElevenLabs Conversational AI voice agent.

## 1. Main Objective

Allow the user to interact via voice with our current agent through the web interface.

* ElevenLabs will capture the audio from the browser, perform STT on their cloud, and send the transcribed text to our backend.
* Our backend will process the text using our existing agent and return the response in text streaming format.
* ElevenLabs will receive this text and perform real-time TTS (voice generation) back to the browser.

## 2. Task 1: Mapping and Adapting the Backend (Local API)

Analyze our existing API and agent structure to perform the following implementations:

1. **Identify the Agent's Entry Point:** Locate where our agent receives the user's text string and where it generates the response.
2. **Create/Adapt Compatibility Endpoint:** Create a `POST` route (e.g., `/v1/chat/completions`) compatible with the format that ElevenLabs consumes (standard OpenAI Chat Completions).
3. **Implement Server-Sent Events (SSE) / Streaming:** Adapt our current agent's output so that it sends words as they are generated (chunks). ElevenLabs requires streaming responses to ensure low voice latency.
* Each data chunk sent must strictly follow the format: `data: {"choices": [{"delta": {"content": "word "}, "finish_reason": null}]}`
* The final block must send `finish_reason: "stop"`.


4. **Ensure Accessibility:** Make sure the API server is configured to listen on host `0.0.0.0` to receive traffic coming from the external tunnel.

> Backend example (for adaptation into what we already have!!):

```python
# app.py
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json
import asyncio

app = FastAPI()

async def call_your_agent(user_text):
    # TODO: Integrate your local model logic here (Ollama, HuggingFace, etc.)
    full_response = f"Processing locally on Linux: you said '{user_text}'."
    
    # Simulates streaming the response in chunks
    for word in full_response.split():
        chunk = {"choices": [{"delta": {"content": word + " "}, "finish_reason": None}]}
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0.1)
    
    yield f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}]})}\n\n"

@app.post("/v1/chat/completions")
async def chat(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    user_text = messages[-1]["content"] if messages else ""
    
    return StreamingResponse(call_your_agent(user_text), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

```

## 3. Task 2: Frontend Integration (Gradio)

Analyze our current Gradio interface to embed the ElevenLabs voice widget:

1. **Web Widget Injection:** Identify the ideal location in our current UI to place the voice control. Use Gradio's `gr.HTML()` component to inject the native ElevenLabs component:
```html
<elevenlabs-convai agent-id="CONFIGURE_VIA_VARIABLE"></elevenlabs-convai>
<script src="https://elevenlabs.io/convai-widget/index.js" async type="text/javascript"></script>

```

> Frontend example (for adaptation into what we already have!!):

```python
# interface.py
import gradio as gradio

# Replace with your agent ID generated in the ElevenLabs dashboard
ELEVENLABS_AGENT_ID = "YOUR_AGENT_ID_HERE"

# Official ElevenLabs JavaScript code wrapped in an HTML tag
custom_html = f"""
<div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 200px;">
    <h3>Active Voice Agent</h3>
    <p>Click the button below to start the voice conversation</p>
    
    <elevenlabs-convai agent-id="{ELEVENLABS_AGENT_ID}"></elevenlabs-convai>
    
    <script src="https://elevenlabs.io/convai-widget/index.js" async type="text/javascript"></script>
</div>
"""

with gradio.Blocks() as demo:
    gradio.Markdown("# My Voice-Enabled AI Interface")
    
    with gradio.Row():
        with gradio.Column():
            gradio.Markdown("### Voice Interaction")
            # Injects the conversational widget directly into the Gradio interface
            gradio.HTML(custom_html)
            
        with gradio.Column():
            gradio.Markdown("### Logs or Other System Functions")
            gradio.Textbox(label="System Status", value="Ready to talk...", interactive=False)

if __name__ == "__main__":
    demo.launch(server_port=7860)
```

## 4. Instructions and Automation for the SSH Tunnel (localhost.run)

To allow ElevenLabs to access the local FastAPI backend, add the following requirements to the project:

1. **Initialization Script (`tunnel.sh`):** Generate an automated Bash script that starts the public tunnel without requiring an account, using `localhost.run`. The script must:
* Open the SSH connection forwarding port `8000`.
* Filter the terminal output to prominently display only the generated `https://...` URL.
* Save this URL to a temporary log file (`.tunnel_url`) for easy reference.


2. **Documentation in README.md:** Create a `README.md` file detailing the exact step-by-step instructions for the human operator. The file must contain a section dedicated to the tunnel with the following commands for Linux:
```bash
# Manual command to open the tunnel
ssh -R 80:localhost:8000 localhost.run
```

## 5 - Environment Variables Configuration

We currently have these variables. Use and/or adjust them as needed:

```bash
# ElevenLabs Voice Integration
# Generate a strong random secret (e.g.: openssl rand -hex 32)
VOICE_BRIDGE_SECRET=015bbe1fd66b576478fab7033eb83bd654afa7017e167a1f0fb7036c2a52f83d
# ElevenLabs agent ID (from Conversational AI dashboard)
ELEVENLABS_AGENT_ID=agent_0801kt1tp3a7ft5twydwszz4k4v7
# ElevenLabs widget embed ID (optional, for iframe embed)
ELEVENLABS_WIDGET_ID=agent_0801kt1tp3a7ft5twydwszz4k4v7
# Public URL of the voice bridge (for ElevenLabs Custom LLM config and UI display)
# Use ngrok for local dev: ngrok http 8003
VOICE_BRIDGE_URL=http://localhost:8003
```