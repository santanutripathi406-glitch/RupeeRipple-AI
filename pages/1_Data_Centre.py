"""Data Centre - load, upload, validate, repair and reset the shared dataset."""
import pandas as pd
import streamlit as st

from core import database as db
from core import state, ui
from core.data_processor import dataset_hash, dataset_summary, inr, template_csv
from core.validation import ENUMS, REQUIRED_COLUMNS, read_csv_bytes, validate_dataframe

c = ui.setup("Data Centre", "🗂️")
ui.hero("Data Centre", "Load the synthetic sample, upload your own CSV, validate every record and repair problems.")

ui.section("Data source", "Load the synthetic sample, upload a CSV, or reload a saved dataset.")
a, b, d = st.columns(3)
with a:
    if st.button("Load synthetic sample data", width="stretch", type="primary"):
        state.load_sample()
        st.success("Synthetic sample dataset loaded (dates start today).")
        st.rerun()
with b:
    st.download_button("Download CSV template", template_csv(), "rupeeripple_template.csv", "text/csv", width="stretch")
with d:
    if st.button("Reset to sample data", width="stretch"):
        state.load_sample()
        st.success("Reset to the synthetic sample dataset and default settings.")
        st.rerun()

up = st.file_uploader("Upload your own CSV", type=["csv"])
if up is not None:
    raw_up, err = read_csv_bytes(up.getvalue())
    if err:
        st.error(err)
    else:
        vr_up = validate_dataframe(raw_up)
        st.markdown(f"**Preview of `{up.name}`** — {len(raw_up)} rows")
        st.dataframe(raw_up.head(50), hide_index=True, width="stretch")
        if vr_up.fatal:
            for f in vr_up.fatal:
                st.error(f)
        else:
            st.info(f"{vr_up.n_valid} valid, {vr_up.n_errors} error(s), {vr_up.n_warnings} warning(s). "
                    "Rows with errors are kept visible in the editor below so you can fix them; they are excluded from calculations until fixed.")
            if st.button("Load this file into the application", type="primary"):
                state.set_dataset(raw_up, up.name)
                st.success(f"Loaded {len(raw_up)} rows from {up.name}. All pages now use this dataset.")
                st.rerun()

saved = db.list_datasets()
if len(saved):
    with st.expander(f"Previously imported datasets ({len(saved)})"):
        st.dataframe(saved, hide_index=True, width="stretch")
        pick = st.selectbox("Re-load a saved dataset", saved["sha"], format_func=lambda s: f"{saved.loc[saved.sha == s, 'name'].iloc[0]} ({s})")
        if st.button("Load selected dataset"):
            raw_s = db.load_dataset(pick)
            if raw_s is not None:
                state.set_dataset(raw_s, saved.loc[saved.sha == pick, "name"].iloc[0])
                st.rerun()

st.divider()
ui.section("Validation report", "Every record is checked; rows with errors are listed, never silently dropped.")
c = state.ctx()
m = st.columns(4)
m[0].metric("Records", c.vr.n_rows)
m[1].metric("Valid", c.vr.n_valid)
m[2].metric("Errors", c.vr.n_errors)
m[3].metric("Warnings", c.vr.n_warnings)
for f in c.vr.fatal:
    st.error(f)
if len(c.vr.issues):
    st.dataframe(c.vr.issues, hide_index=True, width="stretch",
                 column_config={"row": st.column_config.NumberColumn("CSV row", help="Row number in the file (header = row 1)")})
elif c.vr.ok:
    st.success("All records passed validation.")

if c.vr.ok:
    s = dataset_summary(c.df)
    st.caption(f"{s['n_active']} active records · receivables {inr(s['receivable_total'])} · obligations {inr(s['obligation_total'])} · "
               f"{s['first_date']} → {s['last_date']}")

st.divider()
ui.section("Edit or remove records")
st.caption("Edit cells, add rows, or delete rows (select a row and press Delete), then press **Apply edits**. Everything is re-validated.")
editor_key = f"editor_{c.sha}"
edited = st.data_editor(c.raw.reset_index(drop=True), num_rows="dynamic", width="stretch", key=editor_key,
                        column_config={"transaction_type": st.column_config.SelectboxColumn(options=sorted(ENUMS["transaction_type"])),
                                       "entity_type": st.column_config.SelectboxColumn(options=sorted(ENUMS["entity_type"])),
                                       "status": st.column_config.SelectboxColumn(options=sorted(ENUMS["status"])),
                                       "flexibility": st.column_config.SelectboxColumn(options=sorted(ENUMS["flexibility"]))})
if st.button("Apply edits", type="primary"):
    new_raw = edited.fillna("").astype(str).reset_index(drop=True)
    state.set_dataset(new_raw, "Edited dataset")
    vr_new = validate_dataframe(new_raw)
    st.success(f"Edits applied: {vr_new.n_valid} valid record(s), {vr_new.n_errors} error(s).")
    st.rerun()

with st.expander("Data schema"):
    st.markdown("""| Column | Meaning |
|---|---|
| transaction_id | Unique ID per record |
| entity_name | Customer / supplier / payee |
| entity_type | customer, supplier, employee, landlord, utility, government, other |
| transaction_type | receivable (cash in) · payable, payroll, rent, utilities, other (cash out) |
| amount | Positive rupee amount |
| due_date | Contractual due date (YYYY-MM-DD) |
| expected_date | Expected receipt date for receivables (blank → due_date). For `paid` receivables it is read as the actual payment date |
| status | pending, overdue, paid (paid rows are assumed already in opening cash) |
| related_entity | Optional: entity this record is declared to be linked to (draws a *declared* graph edge) |
| flexibility | fixed or flexible (flexible obligations may be rescheduled **if the other party agrees**) |""")
