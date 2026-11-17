import datetime as dt

import pandas as pd

from core import charts
from core.data_processor import inr
from core.ui import styled


def test_indian_grouping_and_styled_tables_keep_numeric_values():
    assert inr(480000) == "₹4,80,000" and inr(1710000) == "₹17,10,000" and inr(-75000) == "-₹75,000"
    df = pd.DataFrame({"amount": [480000.0, None], "when": [dt.date(2026, 12, 4), None]})
    html = styled(df, ["amount"], ["when"]).to_html()
    assert "₹4,80,000" in html and "04 Dec 2026" in html and "—" in html
    assert df["amount"].iloc[0] == 480000.0          # underlying data untouched (sorting stays numeric)


def test_chart_axis_uses_indian_units_and_hover_is_formatted():
    assert [charts._short(v) for v in (0, 50000, 150000, 2500000, 12000000, -200000)] == ["₹0", "₹50k", "₹1.5L", "₹25L", "₹1.2Cr", "−₹2L"]
    daily = pd.DataFrame({"date": [dt.date(2026, 1, 1), dt.date(2026, 1, 2)], "inflow": [480000.0, 0.0], "outflow": [0.0, 75000.0]})
    fig = charts.cash_in_out(daily)
    assert "₹4,80,000" in list(fig.data[0].customdata) and "₹4L" in fig.layout.yaxis.ticktext
