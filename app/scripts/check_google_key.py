#!/usr/bin/env python3
from backend.config import settings  # noqa: F401
import os


key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
if key:
    print("Google API key loaded: yes")
    print(f"Prefix: {key[:8]}...")
else:
    print("Google API key loaded: no")
