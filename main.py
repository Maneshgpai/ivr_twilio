import os
import json
import base64
import asyncio
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') # requires OpenAI Realtime API Access
PORT = int(os.getenv('PORT', 5000))


## Test from normal my phone and call to Customer care
## Clean UI for webphone
## Clean UI to show below on screen
    # Conversation transcript\
    # Caller info - Phone nbr, I.P\
    # Intent and questions asked - summarized\
    # Keyword for interrupting (response.cancel)
    # Pricing of every call - OpenAI charges + Monthly $7\
    # Function call - Book appt on Google Calendar, Xfr call to Owner\
    # At end of every call - logs entry in Database and sends a summary via email / whatsapp / CRM
    # Can connect to FInance or Sales department, based on intent")

## Identify the business areas where there are tons of calls, which could be automated by AI. 
#   Which will pay, which I could have access to sales partners, which can show immediate benefit



## Business details
WELCOME_MESSAGE = """Welcome to Virgolife Private Ltd, your destination for rare and vintage collectors' cars. How can I assist you today?"""
company_name = """Virgolife"""
company_descr = """Virgolife Private Ltd is a Delaware-based company that curates and sells rare, vintage, and collectors' editions of second-hand cars. Established in 1995, Virgolife has built a reputation for sourcing, restoring, and maintaining iconic automobiles from the 1950s through the 1980s. Our cars are sought after by collectors, enthusiasts, and hobbyists worldwide."""
address = """Virgolife Private Limited, Delaware"""
website = """www.physikally.com"""
car_inventory = """There are currently these cars - 
1. 1957 Chevrolet Bel Air
Condition: Fully Restored
Color: Matador Red
Engine: 283 V8 with 4-barrel carburetor
Transmission: 2-Speed Powerglide Automatic
Rarity: High. Iconic 1950s American classic
Price: $75,000
Availability: Immediate
History: Award-winning restoration; known for its distinctive tailfins and chrome detailing.


2. 1965 Ford Mustang Fastback
Condition: Restored with original parts
Color: Wimbledon White
Engine: 289 V8
Transmission: 4-Speed Manual
Rarity: Medium. First-generation Mustang
Price: $82,000
Availability: Waitlist (2 months)
History: Icon of American muscle cars; the perfect blend of performance and style.

3. 1955 Mercedes-Benz 300SL Gullwing
    Condition: Original, preserved
    Color: Silver
    Engine: 3.0L Inline-6
    Transmission: 4-Speed Manual
    Rarity: Extremely Rare. One of the most sought-after vintage cars
    Price: $1,750,000
    Availability: By private appointment only
    History: The 300SL Gullwing is a highly prized collector's car with its iconic doors and advanced engineering for its time."""

customer_services_provided = """Assist with customer requests regarding vehicle maintenance and restoration services. Provide details on car appraisal services and consultation sessions for car collectors. Offer information about membership in the Virgolife Collectors Club, which includes exclusive access to rare car listings, car meets, and community events."""
finance_info = """Finance option is available. If customer is interested in knowing the terms, you will transfer the call to the Finance department fn_connect_finance_dept"""

## Characterstics of the IVR agent
agent_name = """Virgo champion"""
agent_tone = """Your tone should be human, friendly and approachable, conveying a love for classic cars while maintaining professionalism. Enthusiasts should feel like they are speaking with someone who shares their passion for preserving automotive history."""
answer_style = """You are to keep your responses very brief, with short answers."""

SYSTEM_MESSAGE = f"""You are the intelligent voice response (IVR) agent with the name {agent_name}, working for the company {company_name}, assisting their customers with their inquiries. Your purpose is to streamline customer interactions, guide them to the right information, and ensure an exceptional customer experience. {company_descr}. Company is situated at {address}. The website is {website}\
You are to answer to questions only if the answer is available below.
{car_inventory}
{customer_services_provided}
{finance_info}
You are to strictly follow the tone and style given here:{agent_tone}\{answer_style}
Fallback Response:In case of any uncertainty or complex queries, politely inform the customer: "I'll need to transfer you to one of our vintage car specialists for more detailed assistance. Please hold while I connect you."\ """

VOICE = 'alloy'
LOG_EVENT_TYPES = [
    'response.content.done', 'rate_limits.updated', 'response.done',
    'input_audio_buffer.committed', 'input_audio_buffer.speech_stopped',
    'input_audio_buffer.speech_started', 'session.created'
]

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

@app.get("/", response_class=HTMLResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    # <Say> punctuation to improve text-to-speech flow
    response.say(WELCOME_MESSAGE, voice='Polly.Danielle-Neural')
    response.pause(length=1)
    # response.say("O.K. you can start talking!")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    async with websockets.connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        await send_session_update(openai_ws)
        stream_sid = None

        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.open:
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)
                    if response['type'] == 'session.updated':
                        print("Session updated successfully:", response)
                    if response['type'] == 'response.audio.delta' and response.get('delta'):
                        # Audio from OpenAI
                        try:
                            audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                            audio_delta = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {
                                    "payload": audio_payload
                                }
                            }
                            await websocket.send_json(audio_delta)
                        except Exception as e:
                            print(f"Error processing audio data: {e}")
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_session_update(openai_ws):
    """Send session update to OpenAI WebSocket."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad","threshold": 0.5,"prefix_padding_ms": 300,"silence_duration_ms": 600}, #Activation threshold for VAD (0.0 to 1.0).Amount of audio to include before speech starts (in milliseconds).
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": SYSTEM_MESSAGE,
            "modalities": ["text", "audio"],
            "temperature": 0.6,
            # "input_audio_transcription":
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)



# tools = [
#   {
#     "type": "function",
#     "function": {
#       "name": "get_current_weather",
#       "description": "Get the current weather in a given location",
#       "parameters": {
#         "type": "object",
#         "properties": {
#           "location": {
#             "type": "string",
#             "description": "The city and state, e.g. San Francisco, CA",
#           },
#           "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
#         },
#         "required": ["location"],
#       },
#     }
#   }
# ]
# messages = [{"role": "user", "content": "What's the weather like in Boston today?"}]
# completion = client.chat.completions.create(
#   model="gpt-4o",
#   messages=messages,
#   tools=tools,
#   tool_choice="auto"
# )
# print(completion)
