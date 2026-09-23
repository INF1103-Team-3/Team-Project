import os
import time
from dotenv import load_dotenv
import requests

load_dotenv()

API_URL = "https://openrouter.ai/api/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
    "Content-Type": "application/json",
}

payload = {
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",   # your exact model ID
    "messages": [
        {"role": "user", "content": "Reply with exactly: BiteFinder AI connection OK"}
    ],
}

for attempt in range(3):
    response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
    print("Status code:", response.status_code)

    if response.status_code == 200:
        print("Reply:", response.json()["choices"][0]["message"]["content"])
        break
    elif response.status_code == 429:
        print(f"Rate limited — waiting 20s before retry (attempt {attempt + 1}/3)...")
        time.sleep(20)
    else:
        print("Error details:", response.json())
        break
else:
    print("Still rate limited after 3 attempts. Wait a few minutes and try again.")
