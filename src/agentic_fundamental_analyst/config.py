"""Loads .env once at import time so FRED_KEY / TIINGO_KEY / EDGAR_USER_AGENT /
ANTHROPIC_API_KEY / LOGFIRE_TOKEN are in os.environ for every data-layer and
agent client, regardless of import order."""

from dotenv import load_dotenv

load_dotenv()
