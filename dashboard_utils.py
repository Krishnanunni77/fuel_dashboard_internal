import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import base64
from streamlit_autorefresh import st_autorefresh

try:
    from data_fetcher import (
        REGIONS,
        get_api_errors,
        clear_api_errors,
        build_daily_df,
        build_daily_alert_count_df,
        build_daily_pv_df,
        build_daily_amount_df,
        add_usfs_column,
        contains_usfs,
        prepare_data_loss_table,
        build_data_loss_summary
    )
except ImportError:
    st.error("Could not import 'data_fetcher.py'.")
    st.stop()

def load_image_base64(image_path):
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return ""

LOGO_BASE64 = load_image_base64("assets/logo.png")

UNIT_MAP = {
    "IND": "Liters",
    "NASA": "Gallons",
    "EU": "Liters",
    "FML": "Liters"
}

# ── Date range ──────────────────────────────────────────────
end_date = pd.Timestamp.now() - pd.Timedelta(days=2)
start_date = end_date - pd.Timedelta(days=10)
start_time_ms = int(pd.Timestamp(start_date).normalize().timestamp() * 1000)
end_time_ms = int(
    (pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)).timestamp() * 1000
)


# ── Load from Drive — cached in session_state so it only runs ONCE per session ──
@st.cache_resource(show_spinner="Loading data from Google Drive...")
def load_all_regions():
    """
    Downloads all region data from Google Drive once per session.
    Uses st.cache_resource so it survives Streamlit reruns (TV rotations).
    """
    from drive_cache import (
        get_drive_service,
        get_root_folder_id,
        download_jsonl,
    )

    service = get_drive_service()
    root_folder_id = get_root_folder_id()

    results = {}

    for region in REGIONS.keys():
        print(f"[Drive] Loading {region}...")

        # Download raw files from Drive
        theft_all     = download_jsonl(service, region, "theft.jsonl",     root_folder_id)
        fill_all      = download_jsonl(service, region, "fill.jsonl",      root_folder_id)
        low_fuel_all  = download_jsonl(service, region, "low_fuel.jsonl",  root_folder_id)
        data_loss_all = download_jsonl(service, region, "data_loss.jsonl", root_folder_id)
        theft_cev_all = download_jsonl(service, region, "theft_cev.jsonl", root_folder_id)
        fill_cev_all  = download_jsonl(service, region, "fill_cev.jsonl",  root_folder_id)

        # Filter to date range — use fixed values, no closure issue
        def filter_range(df, s=start_time_ms, e=end_time_ms):
            if df is not None and not df.empty and "time_ms" in df.columns:
                return df[(df["time_ms"] >= s) & (df["time_ms"] <= e)].copy()
            return df if df is not None else pd.DataFrame()

        theft_all     = filter_range(theft_all)
        fill_all      = filter_range(fill_all)
        low_fuel_all  = filter_range(low_fuel_all)
        data_loss_all = filter_range(data_loss_all)
        theft_cev_all = filter_range(theft_cev_all)
        fill_cev_all  = filter_range(fill_cev_all)

        # Add usfs column
        if not theft_all.empty:
            theft_all = add_usfs_column(theft_all)
        if not fill_all.empty:
            fill_all = add_usfs_column(fill_all)

        # PV subsets
        theft_pv = (
            theft_all[~theft_all["probable_variation_max"].isna()].copy()
            if not theft_all.empty and "probable_variation_max" in theft_all.columns
            else pd.DataFrame()
        )
        fill_pv = (
            fill_all[~fill_all["probable_variation_max"].isna()].copy()
            if not fill_all.empty and "probable_variation_max" in fill_all.columns
            else pd.DataFrame()
        )

        # USFS subsets
        theft_usfs = (
            theft_all[theft_all["usfs"].apply(contains_usfs)]
            if not theft_all.empty and "usfs" in theft_all.columns
            else pd.DataFrame()
        )
        fill_usfs = (
            fill_all[fill_all["usfs"].apply(contains_usfs)]
            if not fill_all.empty and "usfs" in fill_all.columns
            else pd.DataFrame()
        )

        results[region] = {
            "theft_raw":         theft_all,
            "fill_raw":          fill_all,
            "low_fuel_raw":      low_fuel_all,
            "data_loss_raw":     data_loss_all,
            "theft_cev":         theft_cev_all,
            "fill_cev":          fill_cev_all,
            "data_loss_table":   prepare_data_loss_table(data_loss_all, region),
            "data_loss_summary": build_data_loss_summary(data_loss_all),
            "theft_daily":       build_daily_df(theft_all),
            "fill_daily":        build_daily_df(fill_all),
            "low_fuel_daily":    build_daily_alert_count_df(low_fuel_all),
            "theft_cev_daily":   build_daily_df(theft_cev_all),
            "fill_cev_daily":    build_daily_df(fill_cev_all),
            "theft_pv_daily":    build_daily_pv_df(theft_pv),
            "fill_pv_daily":     build_daily_pv_df(fill_pv),
            "theft_usfs_daily":  build_daily_amount_df(theft_usfs),
            "fill_usfs_daily":   build_daily_amount_df(fill_usfs),
        }

        print(
            f"✅ {region} — "
            f"theft:{len(theft_all)} fill:{len(fill_all)} "
            f"low_fuel:{len(low_fuel_all)}"
        )

    return results


def refresh_data():
    """Clears cache AND resets checkpoint to window start so missing days are re-fetched."""
    from drive_cache import get_drive_service, get_root_folder_id, upload_checkpoint
    
    service = get_drive_service()
    root_folder_id = get_root_folder_id()
    
    # Set checkpoint to start of 10-day window, not zero
    # This means only missing/new days get re-fetched, not everything
    now = pd.Timestamp.now() - pd.Timedelta(days=2)
    window_start = now.normalize() - pd.Timedelta(days=10)
    window_start_ms = int(window_start.timestamp() * 1000)
    
    for region in REGIONS.keys():
        upload_checkpoint(service, region, window_start_ms, root_folder_id)
    
    st.cache_resource.clear()
    st.rerun()


# ── Plot functions ───────────────────────────────────────────

def create_plot(df, title, unit):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scattergl(
        x=df["time"], y=df["amount"],
        mode="markers+lines", name="Amount",
        line=dict(width=4.5), marker=dict(size=9)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scattergl(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="green", width=4.5)
        ))

    total = df["amount"].sum()
    avg = total / len(df) if len(df) else 0
    y_max = max(
        df["amount"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={"text": (
            f"<b style='font-size:30px'>{title}</b><br><br>"
            f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
        ), "x": 0.5, "xanchor": "center"},
        xaxis_title="Date", yaxis_title=unit,
        xaxis=dict(
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray',
            tickmode='linear', dtick=86400000,
            tickformat='%b %d\n%Y', tickangle=-45
        ),
        yaxis=dict(
            range=[0, y_max],
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray'
        ),
        height=450, margin=dict(t=100, b=40, l=60, r=60),
        showlegend=False
    )
    return fig


def create_plot_usfs(df, title, unit):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scattergl(
        x=df["time"], y=df["amount"],
        mode="markers+lines", name="Amount",
        line=dict(width=4.5), marker=dict(size=9)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scattergl(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="green", width=4.5)
        ))

    total = df["amount"].sum()
    avg = total / len(df) if len(df) else 0
    y_max = max(
        df["amount"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={"text": (
            f"<b style='font-size:30px'>{title}</b><br><br>"
            f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
        ), "x": 0.5, "xanchor": "center"},
        xaxis_title="Date", yaxis_title=unit,
        xaxis=dict(
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray',
            tickmode='linear', dtick=86400000,
            tickformat='%b %d\n%Y', tickangle=-45
        ),
        yaxis=dict(
            range=[0, y_max],
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray'
        ),
        height=420, margin=dict(t=100, b=40, l=60, r=60),
        showlegend=False
    )
    return fig


def create_plot_low_fuel(df, title):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scattergl(
        x=df["time"], y=df["vehicle_id"],
        mode="markers+lines", name="Alert Count",
        line=dict(width=3.5), marker=dict(size=9)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scattergl(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="red", width=5.5)
        ))

    total = df["vehicle_id"].sum()
    avg = total / len(df) if len(df) else 0
    y_max = max(
        df["vehicle_id"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={"text": (
            f"<b style='font-size:30px'>{title}</b><br><br>"
            f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
        ), "x": 0.5, "xanchor": "center"},
        xaxis_title="Date", yaxis_title="Alert Count",
        xaxis=dict(
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray',
            tickmode='linear', dtick=86400000,
            tickformat='%b %d\n%Y', tickangle=-45
        ),
        yaxis=dict(
            range=[0, y_max],
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray'
        ),
        height=420, margin=dict(t=100, b=40, l=60, r=60),
        showlegend=False
    )
    return fig


def create_plot_pv(df, title, unit):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scattergl(
        x=df["time"], y=df["probable_variation_max"],
        mode="markers+lines", name="Probable Variation",
        line=dict(width=4.5), marker=dict(size=9)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scattergl(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="green", width=4.5)
        ))

    total = df["probable_variation_max"].sum()
    avg = total / len(df) if len(df) else 0
    y_max = max(
        df["probable_variation_max"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={"text": (
            f"<b style='font-size:30px'>{title}</b><br><br>"
            f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
        ), "x": 0.5, "xanchor": "center"},
        xaxis_title="Date", yaxis_title=unit,
        xaxis=dict(
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray',
            tickmode='linear', dtick=86400000,
            tickformat='%b %d\n%Y', tickangle=-45
        ),
        yaxis=dict(
            range=[0, y_max],
            title_font=dict(size=26, color='black', family='Arial Black'),
            tickfont=dict(size=17, color='black', family='Arial Black'),
            showgrid=True, gridcolor='lightgray'
        ),
        height=420, margin=dict(t=100, b=40, l=60, r=60),
        showlegend=False
    )
    return fig
