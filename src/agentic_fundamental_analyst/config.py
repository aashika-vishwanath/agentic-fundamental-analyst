"""Loads .env once at import time so FRED_KEY / TIINGO_KEY / EDGAR_USER_AGENT
are in os.environ for every data-layer client, regardless of import order."""

from dotenv import load_dotenv

load_dotenv()
