import json

from agent.tools import run_tool
from rag.index import chunk_text, wikipedia_chunks
from rag.notes import add_note, list_notes


def test_chunk_text_groups_short_and_splits_long():
    short = "\n\n".join(f"Paragraph {i} " + "word " * 30 for i in range(6))
    chunks = chunk_text(short)
    assert all(len(c.split()) <= 300 for c in chunks)
    assert len(chunks) < 6  # short paragraphs are merged
    long = ". ".join(["This is a sentence with several words in it"] * 80) + "."
    parts = chunk_text(long)
    assert len(parts) > 1 and all(len(p.split()) <= 300 for p in parts)


def test_wikipedia_chunks_carry_attribution():
    doc = {"tm_player_id": 7, "title": "Some Player", "url": "https://en.wikipedia.org/wiki/Some_Player",
           "revision_id": 42, "licence": "CC BY-SA 4.0", "style_of_play": "Quick and direct.\n\nGood in the air."}
    chunks = wikipedia_chunks(doc)
    assert chunks and chunks[0]["licence"] == "CC BY-SA 4.0" and chunks[0]["url"].endswith("Some_Player")
    assert wikipedia_chunks(doc | {"style_of_play": None}) == []


def test_hybrid_search_respects_player_filter(passage_index):
    hits = passage_index.search("good in the air", limit=3)
    assert hits[0]["player_id"] == 4
    only3 = passage_index.search("good in the air", player_id=3, limit=3)
    assert only3 and {h["player_id"] for h in only3} == {3}


def test_new_note_is_searchable_immediately(passage_index):
    note = add_note(3, "Superb left-footed switches of play; vulnerable to the press on his weaker side.",
                    author="Davron", context="vs Real Club B")
    assert list_notes(3)[-1]["note_id"] == note["note_id"]
    hits = passage_index.search("switches of play", player_id=3, limit=2)
    assert hits[0]["source"] == "scout_note" and hits[0]["source_id"] == note["note_id"]


def test_search_notes_tool(passage_index):
    out, err = run_tool("search_notes", {"query": "composed under pressure", "player_id": 3})
    r = json.loads(out)
    assert not err and r["passages"]
    p = r["passages"][0]
    assert p["player_name"] == "Pablo Builder" and p["source_id"] and p["text"]
    _, err = run_tool("search_notes", {"query": "x", "limit": 20})
    assert err
