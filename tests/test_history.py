"""Tests for SQLite dictation history and usage statistics."""

from pathlib import Path

from localdictate.history import HistoryStore


def test_history_crud_search_and_stats(tmp_path: Path):
    store = HistoryStore(db_path=tmp_path / "history.db")

    id1 = store.add(
        raw_text="merhaba dünya nasılsın",
        final_text="Merhaba dünya, nasılsın?",
        language="tr",
        model_size="small",
        audio_duration_sec=2.0,
        inference_sec=0.5,
        used_llm=True,
    )
    id2 = store.add(
        raw_text="hello localdictate test",
        final_text="Hello LocalDictate test.",
        language="en",
        model_size="small",
        audio_duration_sec=1.5,
        inference_sec=0.3,
        used_llm=False,
    )

    recent = store.list_recent()
    assert [e.id for e in recent] == [id2, id1]
    assert recent[1].used_llm is True

    filtered = store.list_recent(query="LocalDictate")
    assert len(filtered) == 1
    assert filtered[0].id == id2

    stats = store.get_stats()
    assert stats.total_dictations == 2
    assert stats.total_words == 6
    assert abs(stats.avg_inference_sec - 0.4) < 1e-6

    store.delete(id1)
    assert len(store.list_recent()) == 1

    store.clear()
    assert store.list_recent() == []
