"""Build or refresh the passage index, and add scout notes from the terminal.

    python -m rag.index_notes                      # index all Wikipedia passages + saved notes
    python -m rag.index_notes add 937958 "Great first touch, slow on the turn" --context "vs Real Madrid"
    python -m rag.index_notes search "press resistant" --player 357565
"""
import argparse
import json

from rag.index import get_index, load_wikipedia_chunks
from rag.notes import add_note, list_notes, note_chunks


def rebuild() -> None:
    index = get_index()
    wiki = load_wikipedia_chunks()
    notes = note_chunks(list_notes())
    index.upsert(wiki + notes)
    print(f"indexed {len(wiki)} Wikipedia chunks and {len(notes)} scout notes; collection has {index.count()} points")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("add")
    a.add_argument("player_id", type=int)
    a.add_argument("text")
    a.add_argument("--author", default="scout")
    a.add_argument("--context")
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--player", type=int)
    s.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "add":
        print(json.dumps(add_note(args.player_id, args.text, args.author, args.context), indent=2))
    elif args.cmd == "search":
        for r in get_index().search(args.query, args.player, args.limit):
            print(f"[{r['score']}] {r['title']}\n  {r['text'][:200]}\n")
    else:
        rebuild()
