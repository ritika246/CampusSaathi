
import re
import unicodedata
import json
import os
import requests
import base64

from fastapi import FastAPI, UploadFile, File, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv


# --------------------------------------------------
# 1. LOAD ENVIRONMENT VARIABLES
# --------------------------------------------------

load_dotenv()

GNANI_API_KEY = os.getenv("GNANI_API_KEY")

app = FastAPI(title="CampusSaathi")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# 2. LOAD CAMPUS KNOWLEDGE BASE
# --------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "campus_data.json")

with open(DATA_FILE, "r", encoding="utf-8") as file:
    campus_data = json.load(file)

faqs = campus_data["faqs"]


# --------------------------------------------------
# 3. TEXT NORMALIZATION
# --------------------------------------------------

def normalize_text(text):
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()

    # Remove invisible Unicode formatting characters
    text = re.sub(r"[\u200b-\u200f\uFEFF]", "", text)

    # Remove punctuation
    text = re.sub(r"[^\w\s]", " ", text)

    # Remove extra spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


# --------------------------------------------------
# 4. FIND ANSWERS FROM CAMPUS FAQs
# --------------------------------------------------


def get_campus_answer(question, language_code="en-IN"):
    normalized_question = normalize_text(question)

    for faq in faqs:
        possible_questions = [faq["question"]]
        possible_questions.extend(faq.get("alternatives", []))

        for possible_question in possible_questions:
            normalized_possible = normalize_text(possible_question)

            if (
                normalized_possible in normalized_question
                or normalized_question in normalized_possible
            ):
                answers = faq.get("answers", {})
                return answers.get(language_code, faq["answer"])

    return (
        "Sorry, I don't have an answer for that question. "
        "Please contact the college administration."
    )


# --------------------------------------------------
# 5. REQUEST MODELS
# --------------------------------------------------

class TTSRequest(BaseModel):
    text: str
    language: str = "te-IN"


class QuestionRequest(BaseModel):
    question: str


# --------------------------------------------------
# 6. WELCOME ENDPOINT
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "Welcome to CampusSaathi!",
        "status": "Backend is running"
    }


# --------------------------------------------------
# 7. CHECK GNANI API KEY
# --------------------------------------------------

@app.get("/check-gnani")
def check_gnani():
    if not GNANI_API_KEY:
        return {"status": "API key not found"}

    return {"status": "Gnani API key loaded successfully"}


# --------------------------------------------------
# 8. EXTRACT TRANSCRIPT
# --------------------------------------------------

def extract_transcript(transcription):
    if not isinstance(transcription, dict):
        return None

    # Check top-level response fields
    for key in ["transcript", "text"]:
        value = transcription.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    # Check nested output
    output = transcription.get("output")

    if isinstance(output, dict):
        for key in ["literal", "transcript", "text"]:
            value = output.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

    elif isinstance(output, str) and output.strip():
        return output.strip()

    return None


# --------------------------------------------------
# 9. SPEECH-TO-TEXT USING GNANI PRISMA v3.0
# --------------------------------------------------

@app.post("/transcribe")
async def transcribe_audio(
    audio_file: UploadFile = File(...),
    language_code: str = "indic-auto"
):
    if not GNANI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Gnani API key not configured"
        )

    url = "https://api.vachana.ai/stt/v3"

    headers = {
        "X-API-Key-ID": GNANI_API_KEY
    }

    files = {
        "audio_file": (
            audio_file.filename,
            audio_file.file,
            audio_file.content_type or "application/octet-stream"
        )
    }

    data = {
        "model": "prisma-v3.0",
        "language_code": language_code,
        "format": "verbatim"
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=60
        )

        if not response.ok:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            )

        return response.json()

    except requests.RequestException as error:
        raise HTTPException(
            status_code=502,
            detail=f"Gnani API request failed: {str(error)}"
        )

    finally:
        audio_file.file.close()


# --------------------------------------------------
# 10. TEXT-TO-SPEECH USING GNANI TIMBRE
# --------------------------------------------------

@app.post("/speak")
def text_to_speech(request: TTSRequest):

    if not GNANI_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Gnani API key not configured"
        )

    url = "https://api.vachana.ai/api/v1/tts/inference"

    headers = {
        "X-API-Key-ID": GNANI_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "text": request.text,
        "model": "timbre-v2.5",
        "voice": "Yukti",
        "language": request.language,
        "audio_config": {
            "encoding": "linear_pcm",
            "container": "wav",
            "num_channels": 1,
            "sample_rate": 48000,
            "sample_width": 2
        }
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60
        )

        if not response.ok:
            raise HTTPException(
                status_code=response.status_code,
                detail=response.text
            )

        return Response(
            content=response.content,
            media_type="audio/wav",
            headers={
                "Content-Disposition":
                    "attachment; filename=campus_reply.wav"
            }
        )

    except requests.RequestException as error:
        raise HTTPException(
            status_code=502,
            detail=f"Gnani TTS request failed: {str(error)}"
        )


# --------------------------------------------------
# 11. ASK QUESTIONS USING CAMPUS KNOWLEDGE BASE
# --------------------------------------------------


@app.post("/ask")
def ask_campus(
    request: QuestionRequest,
    language_code: str = "en-IN"
):
    answer = get_campus_answer(
        request.question,
        language_code
    )

    return {
        "question": request.question,
        "answer": answer
    }



# --------------------------------------------------
# 12. COMPLETE VOICE ASSISTANT: STT -> FAQ -> TTS
# --------------------------------------------------

@app.post("/voice-ask")
async def voice_ask(
    audio_file: UploadFile = File(...),
    language_code: str = "indic-auto"
):

    # Step 1: Convert speech into text
    transcription = await transcribe_audio(
        audio_file,
        language_code
    )

    # Step 2: Extract recognized question
    transcript = extract_transcript(transcription)

    if not transcript:
        raise HTTPException(
            status_code=502,
            detail="Could not recognize speech"
        )
               
     # Step 3: Identify the detected language
    detected_language = transcription.get(
               "detected_language_code"
          )

    supported_languages = {
      "te-IN",
      "hi-IN",
      "en-IN",
      "ta-IN",
      "kn-IN",
      "ml-IN",
      "mr-IN",
      "gu-IN",
      "bn-IN",
      "pa-IN"
   }

    if detected_language in supported_languages:
       response_language = detected_language
    elif language_code in supported_languages:
         response_language = language_code
    else:
          response_language = "en-IN"

     # Step 4: Find answer in the detected language
    answer = get_campus_answer(transcript, response_language)

    # Step 5: Improve BVRIT pronunciation
    speech_text = answer

    if response_language == "te-IN":
        speech_text = speech_text.replace(
            "BVRIT", "బి వీ ఆర్ ఐ టీ"
        )

    elif response_language == "hi-IN":
        speech_text = speech_text.replace(
            "BVRIT", "बी वी आर आई टी"
        )

    else:
        speech_text = speech_text.replace(
            "BVRIT", "B. V. R. I. T."
        )

    # Step 6: Convert answer into speech
    speech_response = text_to_speech(
        TTSRequest(
            text=speech_text,
            language=response_language
        )
    )

    # Step 7: Convert audio into Base64
    audio_base64 = base64.b64encode(
        speech_response.body
    ).decode("utf-8")

    return {
        "transcript": transcript,
        "answer": answer,
        "detected_language": detected_language,
        "audio_base64": audio_base64,
        "audio_content_type": "audio/wav"
    }
