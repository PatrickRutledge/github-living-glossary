import os
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.csv as csv
import streamlit as st

from living_glossary.curate import append_glossary_entry, load_candidates
from living_glossary.data import connect, query


st.set_page_config(page_title="GitHub Living Glossary", layout="wide")
st.title("GitHub Living Glossary")
st.caption("Explore a selected snapshot. Observations and interpretations remain separate.")

explore_tab, curate_tab = st.tabs(["Explore snapshot", "Curate candidates"])

with explore_tab:
    snapshot = Path(os.environ.get("GLOSSARY_SNAPSHOT", "dist/sample"))
    st.info(f"Snapshot: {snapshot}. The default contains synthetic examples, not collected user text.")

    try:
        connection = connect(snapshot)
    except (OSError, ValueError, KeyError, duckdb.Error) as error:
        st.error(f"Cannot open snapshot: {error}. Build or download a snapshot first.")
        st.stop()

    table = st.selectbox("Dataset", ["glossary", "observations", "annotations"])
    language = st.text_input("Language code (optional)", placeholder="en")
    term = st.text_input("Contains text (optional)")
    limit = st.number_input("Maximum exported rows", min_value=1, max_value=100_000, value=1000)
    advanced = st.checkbox("Write SQL")
    sql = st.text_area(
        "One SELECT query; tables: glossary, observations, annotations",
        value="SELECT * FROM glossary",
    ) if advanced else ""
    st.caption("Local browser UI backed by local Python. Large snapshots need sufficient local memory.")

    if st.button("Run query", type="primary"):
        try:
            if not advanced:
                clauses = []
                if language:
                    if table == "annotations":
                        clauses.append("observation_id IN (SELECT id FROM observations WHERE language = ?)")
                    else:
                        clauses.append("language = ?")
                field = {"glossary": "term", "observations": "text", "annotations": "note"}[table]
                if term:
                    clauses.append(f"contains(lower({field}), lower(?))")
                params = ([language] if language else []) + ([term] if term else [])
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                result = connection.execute(
                    f'SELECT * FROM "{table}"{where} LIMIT ?', params + [int(limit)]
                ).to_arrow_table()
            else:
                result = query(connection, sql, int(limit))
            st.write(f"{result.num_rows} rows returned (limited to {limit}).")
            st.dataframe(result.slice(0, 1000))
            output = pa.BufferOutputStream()
            csv.write_csv(result, output)
            st.session_state["export"] = output.getvalue().to_pybytes()
        except (ValueError, duckdb.Error) as error:
            st.session_state.pop("export", None)
            st.error(str(error))
    connection.close()
    if "export" in st.session_state:
        st.download_button("Download last query as CSV", st.session_state["export"],
                           "query-results.csv", "text/csv")
    st.caption("CSV contains source text. Import columns as text in spreadsheets to avoid formula execution.")

with curate_tab:
    st.caption(
        "Review mined term candidates and promote them into a source directory's "
        "glossary.jsonl. This writes to source JSONL, never to a built snapshot; "
        "run `glossary build` afterwards to produce an updated snapshot, and "
        "`glossary render` to update the published page."
    )
    source_dir = Path(st.text_input(
        "Source directory (observations.jsonl/glossary.jsonl live here)",
        value=os.environ.get("GLOSSARY_SOURCE", "data/sample"),
    ))
    candidates_path = Path(st.text_input(
        "Candidates file (from `glossary mine-terms`)",
        value=os.environ.get("GLOSSARY_CANDIDATES", "dist/candidates.jsonl"),
    ))
    reviewer_id = st.text_input("Your reviewer ID", value=os.environ.get("USER", ""))

    candidates = []
    if candidates_path.exists():
        try:
            candidates = load_candidates(candidates_path)
        except (OSError, ValueError) as error:
            st.error(f"Cannot read candidates: {error}")
    else:
        st.warning(f"No candidates file at {candidates_path}. Run `glossary mine-terms` first.")

    if candidates:
        labels = [f"{c['term']} ({c['language']}, freq={c['frequency']})" for c in candidates]
        choice = st.selectbox("Candidate", range(len(candidates)), format_func=lambda i: labels[i])
        selected = candidates[choice]
        st.write("Linked observations (evidence):", selected["observation_ids"])

        with st.form("curate_form"):
            sense = st.text_input("Sense (short machine-readable label, e.g. git.rebase)")
            definition = st.text_area("Definition")
            target_language = st.text_input("Target language (optional)", value="none")
            translation = st.text_input("Translation (optional)", value="none")
            status = st.selectbox("Status", ["reviewed", "disputed", "unreviewed"])
            observation_id = st.selectbox("Evidence observation_id", selected["observation_ids"])
            submitted = st.form_submit_button("Add to glossary.jsonl", type="primary")

        if submitted:
            try:
                entry = append_glossary_entry(
                    source_dir,
                    term=selected["term"],
                    language=selected["language"],
                    sense=sense,
                    definition=definition,
                    reviewer_id=reviewer_id,
                    observation_id=observation_id,
                    target_language=target_language or "none",
                    translation=translation or "none",
                    status=status,
                )
                st.success(f"Added glossary entry {entry['id']} to {source_dir / 'glossary.jsonl'}")
            except (ValueError, OSError) as error:
                st.error(str(error))

