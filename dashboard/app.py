"""Streamlit dashboard for the Rolling ATM Straddle & VWAP Scanner."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

SNAPSHOT_PATH = Path("data/snapshot.json")
REFRESH_INTERVAL_SECONDS = 2

st.set_page_config(
    page_title="Straddle & VWAP Scanner",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(ttl=1)
def _load_snapshot(path: Path) -> dict | None:
    """Load the latest scanner snapshot from disk."""
    if not path.exists():
        return None
    try:
        with path.open() as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _parse_straddle_keys(snapshot: dict) -> list[str]:
    """Extract sorted list of underlying symbols from the snapshot."""
    symbols = []
    for key in snapshot.get("candles", {}):
        if key.startswith("straddle:"):
            symbols.append(key.removeprefix("straddle:"))
    return sorted(symbols)


def _build_chart(candles: list[dict], symbol: str) -> go.Figure:
    """Build a Plotly candlestick + VWAP overlay figure.

    Args:
        candles: List of candle dicts with keys: timestamp, open, high, low, close, vwap.
        symbol: Display name for the chart title.

    Returns:
        Plotly Figure object ready for st.plotly_chart().
    """
    if not candles:
        return go.Figure()

    times = [datetime.fromtimestamp(c["timestamp"]) for c in candles]
    opens = [c["open"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    vwaps = [c["vwap"] for c in candles]

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=times,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="Straddle",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=times,
            y=vwaps,
            mode="lines",
            name="VWAP",
            line={"color": "#ff9800", "width": 2, "dash": "dot"},
        )
    )

    fig.update_layout(
        title=f"{symbol} — ATM Straddle Price + VWAP",
        xaxis_title="Time",
        yaxis_title="Straddle Price",
        xaxis_rangeslider_visible=False,
        height=520,
        template="plotly_dark",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
        margin={"l": 40, "r": 20, "t": 50, "b": 40},
    )
    return fig


def main() -> None:
    st.title("Rolling ATM Straddle & VWAP Scanner")

    snapshot = _load_snapshot(SNAPSHOT_PATH)

    if snapshot is None:
        st.warning(
            "Snapshot not found. Make sure the scanner is running:\n\n"
            "```\npython -m scanner.main\n```"
        )
        time.sleep(REFRESH_INTERVAL_SECONDS)
        st.rerun()
        return

    written_at = snapshot.get("written_at", 0)
    age_seconds = time.time() - written_at
    col_title, col_status = st.columns([4, 1])
    with col_status:
        color = "green" if age_seconds < 5 else "orange" if age_seconds < 15 else "red"
        st.markdown(
            f"<span style='color:{color}'>● Live</span> — updated {age_seconds:.1f}s ago",
            unsafe_allow_html=True,
        )

    symbols = _parse_straddle_keys(snapshot)
    if not symbols:
        st.info("No straddle data yet. Waiting for the first candle close (at the next :00).")
        time.sleep(REFRESH_INTERVAL_SECONDS)
        st.rerun()
        return

    selected = st.selectbox("Select underlying", symbols, index=0)
    candle_key = f"straddle:{selected}"
    candles = snapshot.get("candles", {}).get(candle_key, [])

    if candles:
        latest = candles[-1]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Straddle Price", f"{latest['close']:.2f}")
        m2.metric("VWAP", f"{latest['vwap']:.2f}")
        diff = latest["close"] - latest["vwap"]
        m3.metric("vs VWAP", f"{diff:+.2f}", delta_color="normal")
        m4.metric("Volume", f"{latest['volume']:,}")

        fig = _build_chart(candles, selected)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"No candles for {selected} yet.")

    # Latest signals panel
    signals = snapshot.get("signals", [])
    with st.expander(f"Latest Signals ({len(signals)})", expanded=bool(signals)):
        if signals:
            for sig in reversed(signals[-20:]):
                icon = "▲" if "UP" in sig["signal_type"] else "▼"
                ts = datetime.fromtimestamp(sig["timestamp"]).strftime("%H:%M")
                st.markdown(f"**{ts}** {icon} {sig['detail']}")
        else:
            st.write("No signals fired this session yet.")

    time.sleep(REFRESH_INTERVAL_SECONDS)
    st.rerun()


if __name__ == "__main__":
    main()
