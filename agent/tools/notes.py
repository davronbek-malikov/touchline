"""search_notes: qualitative evidence from scout notes and Wikipedia style-of-play text."""
from agent.schemas import SearchNotesInput
from agent.tools.db import ToolError, rows


def search_notes(args: SearchNotesInput) -> dict:
    from rag.index import get_index

    try:
        hits = get_index().search(args.query, args.player_id, args.limit)
    except Exception as e:  # index missing or unreachable
        raise ToolError(f"notes index unavailable ({type(e).__name__}); run python -m rag.index_notes") from e
    names = {}
    ids = sorted({h["player_id"] for h in hits})
    if ids:
        names = {r["player_id"]: r["name"] for r in rows(
            f"SELECT player_id, name FROM players WHERE player_id IN ({', '.join('?' * len(ids))})", ids)}
    passages = [{
        "source_id": h["source_id"], "source": h["source"], "title": h["title"], "url": h.get("url"),
        "licence": h.get("licence"), "player_id": h["player_id"], "player_name": names.get(h["player_id"]),
        "text": h["text"],
    } for h in hits]
    notes = [] if passages else ["No scout notes or Wikipedia passages match."]
    return {"query": args.query, "passages": passages, "notes": notes}
