"""The tools the model can call.

A tool's docstring is not documentation, it is the contract the model reads to
decide whether to call it. Vague docstrings are the usual cause of an agent
picking the wrong tool, so each one says what it answers and when to reach for
it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

# Provisional. This is the scaffold tool for the bare loop, kept because it is
# real, cheap and unguessable by the model, which is what makes it a usable
# smoke test. Reconsider it when the five real tools land.
SITE_TIMEZONE = ZoneInfo("Asia/Karachi")


@tool
def get_site_time() -> str:
    """Get the current local date and time where Ammar is, in Lahore, Pakistan.

    Use this when a visitor asks what time it is for him, whether he is likely
    to be awake, or what day it is on his side. Do not use it for anything
    about his projects, writing or music.
    """
    now = datetime.now(SITE_TIMEZONE)
    return now.strftime("%A %d %B %Y, %H:%M") + " in Lahore (UTC+5)"


TOOLS = [get_site_time]
