from pathlib import Path

from streamlit.testing.v1 import AppTest

from living_glossary.data import build
from test_data import SAMPLE

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_ui_query(tmp_path, monkeypatch):
    snapshot = tmp_path / "sample"
    build(SAMPLE, snapshot)
    monkeypatch.setenv("GLOSSARY_SNAPSHOT", str(snapshot))
    app = AppTest.from_file(APP).run(timeout=30)
    assert not app.exception
    app.button[0].click().run(timeout=30)
    assert not app.exception
    assert not app.error
    assert len(app.dataframe) == 1
    assert b"squash" in app.session_state["export"]


def test_ui_bad_sql(tmp_path, monkeypatch):
    snapshot = tmp_path / "sample"
    build(SAMPLE, snapshot)
    monkeypatch.setenv("GLOSSARY_SNAPSHOT", str(snapshot))
    app = AppTest.from_file(APP).run(timeout=30)
    app.checkbox[0].check().run()
    app.text_area[0].set_value("DELETE FROM glossary")
    app.button[0].click().run()
    assert app.error
    assert not app.exception
