import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from bot.main import run  # noqa: E402

if __name__ == "__main__":
    asyncio.run(run())
