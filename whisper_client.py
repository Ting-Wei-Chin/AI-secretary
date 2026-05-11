import os
import tempfile
import httpx
from openai import OpenAI


def transcribe_audio(audio_url: str, line_access_token: str) -> str:
    # Download audio from LINE
    headers = {"Authorization": f"Bearer {line_access_token}"}
    with httpx.Client() as client:
        response = client.get(audio_url, headers=headers)
        response.raise_for_status()

    with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
        tmp.write(response.content)
        tmp_path = tmp.name

    openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    with open(tmp_path, "rb") as audio_file:
        transcript = openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="zh",
        )

    os.unlink(tmp_path)
    return transcript.text
