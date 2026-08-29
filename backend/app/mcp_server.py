import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

logging.getLogger("mcp").setLevel(logging.WARNING)

BACKEND = Path(__file__).resolve().parent.parent

with open(BACKEND / "reference" / "herb_safety.json", encoding="utf-8") as f:
    SAFETY_DB = {entry["herb"]: entry for entry in json.load(f)}

mcp = FastMCP("charaka-herb-safety")


@mcp.tool()
def check_herb_safety(herb_name: str) -> str:
    """Look up safety information for an Ayurvedic herb.

    Returns contraindications, drug/herb interactions, pregnancy flags,
    and dosha cautions for the given herb. Use this whenever herbs are
    found in a query to provide accurate safety guidance.

    Args:
        herb_name: The canonical herb name (e.g. "ashwagandha", "guggulu").
    """
    herb = herb_name.lower().strip()
    entry = SAFETY_DB.get(herb)
    if not entry:
        return json.dumps({
            "herb": herb,
            "found": False,
            "message": f"No safety data available for '{herb}'. Advise consulting a qualified Ayurvedic practitioner.",
        })
    return json.dumps({
        "herb": entry["herb"],
        "found": True,
        "contraindications": entry.get("contraindications", []),
        "interactions": entry.get("interactions", []),
        "pregnancy_flag": entry.get("pregnancy_flag", "No specific data available"),
        "dosha_caution": entry.get("dosha_caution", "No specific data available"),
    })


if __name__ == "__main__":
    mcp.run(transport="stdio")
