import os
from typing import List

from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from modal import Image, App, Secret, asgi_app, mount
from multion.client import MultiOn

import templates
from db import (
    get_notion_crm_api_key,
    get_notion_database_id,
    store_notion_crm_api_key,
    store_notion_database_id,
    clean_all_transcripts_except,
    append_segment_to_transcript,
    remove_transcript,
)
from llm import news_checker
from models import Memory
from notion_utils import store_memoy_in_db
from mem0 import MemoryClient

app = FastAPI()

modal_app = App(
    name="plugins_examples",
    secrets=[Secret.from_dotenv(".env")],
    mounts=[
        mount.Mount.from_local_dir("templates/", remote_path="templates/"),
    ],
)

mem0_api_key = os.getenv("MEM0_API_KEY")
if not mem0_api_key:
    raise ValueError(
        "MEM0_API_KEY is required. You can get it from https://app.mem0.ai"
    )


mem0 = MemoryClient(api_key=mem0_api_key)


@modal_app.function(
    image=Image.debian_slim().pip_install_from_requirements("requirements.txt"),
    keep_warm=1,  # need 7 for 1rps
    memory=(1024, 2048),
    cpu=4,
    allow_concurrent_inputs=10,
)
@asgi_app()
def plugins_app():
    return app


# **************************************************
# ************ On Memory Created Plugin ************
# **************************************************

# noinspection PyRedeclaration
templates = Jinja2Templates(directory="templates")


@app.post("/mem0-add")
def mem0_add(memory: Memory, uid: str):
    messages = [
        {
            "role": "user",
            "content": f"Here is the transcript of the conversation I had: {memory.transcript}",
        }
    ]
    mem0.add(messages, user_id=uid)
    memories = mem0.search(memory.transcript, user_id=uid)
    response = [row["memory"] for row in memories]
    return response


# *******************************************************
# ************ On Transcript Received Plugin ************
# *******************************************************


@app.post("/news-checker")
def news_checker_endpoint(uid: str, data: dict):
    session_id = data[
        "session_id"
    ]  # use session id in case your plugin needs the whole conversation context
    new_segments = data["segments"]
    clean_all_transcripts_except(uid, session_id)

    transcript: list[dict] = append_segment_to_transcript(uid, session_id, new_segments)
    message = news_checker(transcript)

    if message:
        # so that in the next call with already triggered stuff, it doesn't trigger again
        remove_transcript(uid, session_id)

    return {"message": message}


# https://e604-107-3-134-29.ngrok-free.app/news-checker
