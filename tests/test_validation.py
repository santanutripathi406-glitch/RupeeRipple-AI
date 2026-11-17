import pandas as pd

from core.validation import REQUIRED_COLUMNS, read_csv_bytes, validate_dataframe

GOOD = "transaction_id,entity_name,entity_type,transaction_type,amount,due_date,expected_date,status,related_entity,flexibility\n"


def vr(text):
    raw, err = read_csv_bytes(text.encode())
    assert err is None
    return validate_dataframe(raw)


def test_11_invalid_csv_rejected_with_explanations():
    r = vr(GOOD + "A1,X,customer,receivable,abc,2026-01-05,,pending,,fixed\n"
                  "A2,Y,supplier,payable,-5,2026-13-45,,pending,,fixed\n"
                  "A3,Z,alien,payable,10,2026-01-05,,pending,,fixed\n"
                  "A4,,supplier,payable,0,2026-01-05,,pending,,fixed\n"
                  "A5,Ok,supplier,payable,10,2026-01-05,,pending,,fixed\n")
    assert r.n_valid == 1 and r.n_errors >= 5
    msgs = " ".join(r.issues["message"])
    assert "not a number" in msgs and "not a valid date" in msgs and "not valid" in msgs and "greater than zero" in msgs
    assert set(r.issues[r.issues.severity == "error"]["row"]) == {2, 3, 4, 5}      # nothing silently dropped
    raw, err = read_csv_bytes(b"")
    assert raw is None and err


def test_12_missing_columns_is_fatal_and_named():
    r = vr("transaction_id,entity_name,amount\nA,B,1\n")
    assert not r.ok and "due_date" in r.fatal[0] and "flexibility" in r.fatal[0]
    assert not validate_dataframe(None).ok and not validate_dataframe(pd.DataFrame(columns=REQUIRED_COLUMNS)).ok


def test_13_duplicate_transaction_ids_flagged():
    r = vr(GOOD + "D1,X,supplier,payable,10,2026-01-05,,pending,,fixed\n"
                  "D1,Y,supplier,payable,20,2026-01-06,,pending,,fixed\n"
                  "D2,Z,supplier,payable,30,2026-01-07,,pending,,fixed\n")
    dups = r.issues[r.issues["message"].str.contains("Duplicate")]
    assert len(dups) == 2 and r.n_valid == 1 and list(r.clean["transaction_id"]) == ["D2"]


def test_blank_expected_date_defaults_to_due_with_warning_and_formats_normalised():
    r = vr(GOOD + "B1, Acme ,CUSTOMER,Receivable,\"₹1,50,000\",2026-02-01,,PENDING,,Fixed\n")
    assert r.ok and r.n_warnings == 1
    row = r.clean.iloc[0]
    assert row["amount"] == 150000 and row["expected_date"] == row["due_date"] and row["entity_type"] == "customer"
