import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import base64
from pathlib import Path
from datetime import timedelta
from streamlit_autorefresh import st_autorefresh


# ─────────────────────────────────────────────────────────────────────────────
# Drive cache import (primary data source)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from drive_cache import (
        get_drive_service,
        get_root_folder_id,
        load_cached_data,
    )
    DRIVE_AVAILABLE = True
except ImportError:
    DRIVE_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Live data-fetcher (fallback)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from data_fetcher import (
        REGIONS,
        run_region_cached_with_range,
        get_api_errors,
        clear_api_errors,
    )
    FETCHER_AVAILABLE = True
except ImportError:
    st.error("Could not import 'data_fetcher.py'. Please ensure the file exists and is named correctly.")
    st.stop()


st.set_page_config(page_title="Fuel Monitoring Dashboard", layout="wide")


# ─────────────────────────────────────────────────────────────────────────────
# Logo
# ─────────────────────────────────────────────────────────────────────────────
def load_image_base64(image_path):
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        return ""

LOGO_BASE64 = load_image_base64("assets/logo.png")


RATE_CATEGORIES = [
    "Refills ignored by humans",
    "Total refill alerts",
    "Refill True Positive rate (%)",
    "Refill False Positive rate (%)",
    "Thefts ignored by humans",
    "Total theft alerts",
    "Theft True Positive rate (%)",
    "Theft False Positive rate (%)"
]

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
header_col1, header_col2 = st.columns([6, 1])

with header_col1:
    st.title("Fuel Trends Dashboard")

with header_col2:
    st.markdown(
        f"""
        <div style="display:flex; justify-content:flex-end; align-items:center;">
            <img 
                src="data:image/png;base64,{LOGO_BASE64}"
                style="
                    height:70px;
                    max-width:260px;
                    width:auto;
                    image-rendering: -webkit-optimize-contrast;
                    image-rendering: crisp-edges;
                "
            />
        </div>
        """,
        unsafe_allow_html=True
    )

# ─────────────────────────────────────────────────────────────────────────────
# Date range inputs
# ─────────────────────────────────────────────────────────────────────────────
end_time_start = pd.Timestamp.now() - pd.Timedelta(days=2)
START_DATE = (end_time_start - pd.Timedelta(days=10)).date()
END_DATE = end_time_start.date()

start_time_ms = int(pd.Timestamp(START_DATE).normalize().timestamp() * 1000)
end_time_ms   = int((pd.Timestamp(END_DATE).normalize() + pd.Timedelta(days=1)).timestamp() * 1000)

if st.button("🔄 Refresh Data"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Drive service — cached so we only authenticate once per session
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_drive_handles():
    if not DRIVE_AVAILABLE:
        return None, None
    try:
        service        = get_drive_service()
        root_folder_id = get_root_folder_id()
        return service, root_folder_id
    except Exception as exc:
        st.warning(f"Google Drive unavailable ({exc}). Falling back to live API.")
        return None, None


# ─────────────────────────────────────────────────────────────────────────────
# Core loader: Drive → API fallback, cached 6 h
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner=True, ttl=6 * 60 * 60)
def load_all_regions(start_ms, end_ms):
    service, root_folder_id = _get_drive_handles()
    results = {}

    for region, url in REGIONS.items():

        # 1. Try Drive cache
        if DRIVE_AVAILABLE and service is not None:
            try:
                results[region] = load_cached_data(
                    service, region, root_folder_id, start_ms, end_ms
                )
                continue                        # success → next region
            except Exception as exc:
                st.warning(
                    f"Drive cache failed for **{region}** ({exc}). "
                    f"Fetching from live API…"
                )

        # 2. Fallback: live API
        results[region] = run_region_cached_with_range(region, url, start_ms, end_ms)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Fetch data
# ─────────────────────────────────────────────────────────────────────────────
clear_api_errors()

with st.spinner("Fetching data from Dashboard APIs..."):
    RESULTS = load_all_regions(start_time_ms, end_time_ms)

    api_errors = get_api_errors()
    if api_errors:
        st.warning(
            f"**Data Incomplete Due to API Errors**\n\n"
            f"**{len(api_errors)} API requests failed** due to timeouts. "
            f"Some data may be missing in the dashboard."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────
def filter_data_by_date_range(results, start_ms, end_ms):
    filtered = {}
    for region, data in results.items():
        filtered[region] = {}
        for key, df in data.items():
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                filtered[region][key] = df
                continue
            if isinstance(df, pd.DataFrame) and 'time_ms' in df.columns:
                filtered[region][key] = df[
                    (df['time_ms'] >= start_ms) &
                    (df['time_ms'] <= end_ms)
                ].copy()
            else:
                filtered[region][key] = df
    return filtered


def build_fuel_summary_values(fill_daily, theft_daily):
    total_theft  = theft_daily["amount"].sum() if not theft_daily.empty else 0
    total_refill = fill_daily["amount"].sum()  if not fill_daily.empty  else 0
    mv_avg_theft  = int(theft_daily["moving average"].iloc[-1]) if not theft_daily.empty else 0
    mv_avg_refill = int(fill_daily["moving average"].iloc[-1])  if not fill_daily.empty  else 0
    return [round(total_theft, 2), round(total_refill, 2), mv_avg_theft, mv_avg_refill]


def build_lng_cng_ratio(fill_raw):
    if fill_raw.empty or "fuel_type" not in fill_raw.columns:
        return None, None

    def calc_ratio(df):
        if df.empty:
            return None
        total = df["amount"].count()
        kgs = df["Amount_kgs"].count() if "Amount_kgs" in df.columns else 0
        return round((kgs / total) * 100, 2) if total else None

    lng_df = fill_raw[fill_raw["fuel_type"].str.lower() == "lng"]
    cng_df = fill_raw[fill_raw["fuel_type"].str.lower() == "cng"]
    return calc_ratio(lng_df), calc_ratio(cng_df)


def build_tp_fp_table(refill_df, theft_df, ignored_refill_df, ignored_theft_df):
    total_refills   = len(refill_df)
    total_thefts    = len(theft_df)
    ignored_refills = len(ignored_refill_df)
    ignored_thefts  = len(ignored_theft_df)

    tp_refill = (total_refills  - ignored_refills) / total_refills  * 100 if total_refills  else 0
    fp_refill = ignored_refills / total_refills  * 100                     if total_refills  else 0
    tp_theft  = (total_thefts   - ignored_thefts)  / total_thefts   * 100 if total_thefts   else 0
    fp_theft  = ignored_thefts  / total_thefts   * 100                     if total_thefts   else 0

    return [
        ignored_refills, total_refills, round(tp_refill, 2), round(fp_refill, 2),
        ignored_thefts,  total_thefts,  round(tp_theft,  2), round(fp_theft,  2),
    ]


def build_combined_data_loss_summary(results):
    rows = []
    for region, data in results.items():
        summary = data.get("data_loss_summary", pd.DataFrame())
        if summary is not None and not summary.empty:
            tmp = summary.copy()
            tmp["Region"] = region
            rows.append(tmp)
    if not rows:
        return pd.DataFrame()
    final_df = pd.concat(rows, ignore_index=True)
    return final_df[["Region", "Data loss type", "Count"]]


# ─────────────────────────────────────────────────────────────────────────────
# Chart builders  (identical to original — untouched)
# ─────────────────────────────────────────────────────────────────────────────
def create_plot(df, title, unit):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scatter(
        x=df["time"], y=df["amount"],
        mode="markers+lines", name="Amount",
        line=dict(width=4), marker=dict(size=14)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="green", width=2)
        ))

    total = df["amount"].sum()
    avg   = total / len(df) if len(df) else 0
    y_max = max(
        df["amount"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={
            "text": (
                f"<b style='font-size:30px'>{title}</b><br>"
                f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
            ),
            "x": 0.5, "xanchor": "center"
        },
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
        height=450, margin=dict(t=100, b=40, l=60, r=60), showlegend=False
    )
    return fig


def create_plot_usfs(df, title, unit):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scatter(
        x=df["time"], y=df["amount"],
        mode="markers+lines", name="Amount",
        line=dict(width=4), marker=dict(size=14)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="green", width=2)
        ))

    total = df["amount"].sum()
    avg   = total / len(df) if len(df) else 0
    y_max = max(
        df["amount"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={
            "text": (
                f"<b style='font-size:30px'>{title}</b><br>"
                f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
            ),
            "x": 0.5, "xanchor": "center"
        },
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
        height=420, margin=dict(t=100, b=40, l=60, r=60), showlegend=False
    )
    return fig


def create_plot_low_fuel(df, title):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scatter(
        x=df["time"], y=df["vehicle_id"],
        mode="markers+lines", name="Alert Count",
        line=dict(width=4), marker=dict(size=14)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="red", width=4)
        ))

    total = df["vehicle_id"].sum()
    avg   = total / len(df) if len(df) else 0
    y_max = max(
        df["vehicle_id"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={
            "text": (
                f"<b style='font-size:30px'>{title}</b><br>"
                f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
            ),
            "x": 0.5, "xanchor": "center"
        },
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
        height=420, margin=dict(t=100, b=40, l=60, r=60), showlegend=False
    )
    return fig


def create_plot_pv(df, title, unit):
    fig = go.Figure()
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")

    fig.add_trace(go.Scatter(
        x=df["time"], y=df["probable_variation_max"],
        mode="markers+lines", name="Probable Variation",
        line=dict(width=4), marker=dict(size=14)
    ))

    if "moving average" in df.columns:
        fig.add_trace(go.Scatter(
            x=df["time"], y=df["moving average"],
            mode="lines", name="Moving Avg",
            line=dict(dash="dot", color="green", width=2)
        ))

    total = df["probable_variation_max"].sum()
    avg   = total / len(df) if len(df) else 0
    y_max = max(
        df["probable_variation_max"].max(),
        df["moving average"].max() if "moving average" in df.columns else 0
    ) * 1.3

    fig.update_layout(
        title={
            "text": (
                f"<b style='font-size:30px'>{title}</b><br>"
                f"<span style='font-size:26px'>Total: {total:.2f} | Avg/Day: {avg:.2f}</span>"
            ),
            "x": 0.5, "xanchor": "center"
        },
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
        height=420, margin=dict(t=100, b=40, l=60, r=60), showlegend=False
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Tabs + unit map
# ─────────────────────────────────────────────────────────────────────────────

TAB_NAMES = [
    "🇮🇳 India", "🇺🇸 US", "🇪🇺 Europe", "🇮🇳 Force Motors",
    "FUEL SUMMARY", "DATA LOSS", "MAIN DASHBOARD", "EXPORT DATA", "📅 TIME RANGE EXPORT"
]

# Persist active tab index across reruns
if "active_tab" not in st.session_state:
    st.session_state.active_tab = 0

# JavaScript: on every load, re-click whichever tab was last active.
# We target the stTabs button list and click by index after a short delay
# so Streamlit has time to render the DOM first.
_active = st.session_state.active_tab
st.markdown(
    f"""
    <script>
    (function() {{
        const TARGET_IDX = {_active};
        function clickTab() {{
            const tabs = window.parent.document.querySelectorAll('[data-testid="stTabs"] button[role="tab"]');
            if (tabs.length > TARGET_IDX) {{
                tabs[TARGET_IDX].click();
            }} else {{
                setTimeout(clickTab, 100);
            }}
        }}
        // Small delay so Streamlit DOM is ready
        setTimeout(clickTab, 120);
    }})();
    </script>
    """,
    unsafe_allow_html=True
)

tabs = st.tabs(TAB_NAMES)

# ── Tab-click tracker: inject JS that writes the clicked tab index
# into a hidden st.query_params key so we can read it on next rerun.
# Streamlit re-runs whenever query_params change, but we only update
# session_state here — we do NOT force a rerun from the tracker itself.
_qp = st.query_params.to_dict()
if "tab" in _qp:
    try:
        _idx = int(_qp["tab"])
        if 0 <= _idx < len(TAB_NAMES):
            st.session_state.active_tab = _idx
    except (ValueError, TypeError):
        pass

# Inject click listeners that push tab index into query params
st.markdown(
    f"""
    <script>
    (function() {{
        function attachListeners() {{
            const tabBtns = window.parent.document.querySelectorAll('[data-testid="stTabs"] button[role="tab"]');
            if (tabBtns.length === 0) {{
                setTimeout(attachListeners, 150);
                return;
            }}
            tabBtns.forEach(function(btn, idx) {{
                btn.addEventListener('click', function() {{
                    const url = new URL(window.parent.location.href);
                    url.searchParams.set('tab', idx);
                    window.parent.history.replaceState(null, '', url.toString());
                }});
            }});
        }}
        setTimeout(attachListeners, 300);
    }})();
    </script>
    """,
    unsafe_allow_html=True
)

UNIT_MAP = {
    "IND":  "Liters",
    "NASA": "Gallons",
    "EU":   "Liters",
    "FML":  "Liters",
}

# Matches tv_display.py naming exactly
REGION_DISPLAY_NAMES = {
    "IND":  "🇮🇳 India",
    "NASA": "🇺🇸 US",
    "EU":   "🇪🇺 Europe",
    "FML":  "🇮🇳 Force Motors",
}

# ─────────────────────────────────────────────────────────────────────────────
# Region tabs  (INDIA / NASA / EU / FML)
# ─────────────────────────────────────────────────────────────────────────────
for tab_idx, (tab, region) in enumerate(zip(tabs[:4], REGIONS.keys())):
    with tab:
        st.session_state.active_tab = tab_idx
        region_label = REGION_DISPLAY_NAMES.get(region, region)
        st.header(f"{region_label} Region Analysis")

        st.markdown(
            """
            <div style="
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                padding: 15px 30px; border-radius: 10px; margin-bottom: 20px;
                text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            ">
                <span style="font-size:18px;font-weight:bold;color:#333;margin-right:30px;">Legend:</span>
                <span style="font-size:19px;color:#1e88e5;margin-right:25px;">
                    <span style="display:inline-block;width:40px;height:3px;background:#1e88e5;vertical-align:middle;margin-right:8px;"></span>
                    <strong>Amount / Alert Count</strong>
                </span>
                <span style="font-size:19px;color:#43a047;">
                    <span style="display:inline-block;width:40px;height:3px;background:#43a047;border-top:2px dotted #43a047;vertical-align:middle;margin-right:8px;"></span>
                    <strong>Moving Average</strong>
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

        unit = UNIT_MAP[region]

        fill_daily      = RESULTS[region]["fill_daily"]
        theft_daily     = RESULTS[region]["theft_daily"]
        fill_cev_daily  = RESULTS[region]["fill_cev_daily"]
        theft_cev_daily = RESULTS[region]["theft_cev_daily"]
        fill_usfs       = RESULTS[region]["fill_usfs_daily"]
        theft_usfs      = RESULTS[region]["theft_usfs_daily"]
        fill_pv         = RESULTS[region]["fill_pv_daily"]
        theft_pv        = RESULTS[region]["theft_pv_daily"]
        low_fuel_daily  = RESULTS[region]["low_fuel_daily"]

        st.subheader("Fuel Refill (DPL)")
        if not fill_daily.empty:
            st.plotly_chart(create_plot(fill_daily, f"{region_label} - Refill (DPL)", unit), True)
        else:
            st.info("No refill data")

        st.subheader("Fuel Theft (DPL)")
        if not theft_daily.empty:
            st.plotly_chart(create_plot(theft_daily, f"{region_label} - Theft (DPL)", unit), True)
        else:
            st.info("No theft data")

        st.markdown("---")
        st.subheader("Fuel Refill (CEV/Off-Highway)")
        if not fill_cev_daily.empty:
            st.plotly_chart(create_plot(fill_cev_daily, f"{region_label} - Refill (CEV)", unit), True)
        else:
            st.info("No CEV refill data")

        st.subheader("Fuel Theft (CEV/Off-Highway)")
        if not theft_cev_daily.empty:
            st.plotly_chart(create_plot(theft_cev_daily, f"{region_label} - Theft (CEV)", unit), True)
        else:
            st.info("No CEV theft data")

        st.markdown("---")
        st.subheader("USFS Refill")
        if not fill_usfs.empty:
            st.plotly_chart(create_plot_usfs(fill_usfs, f"{region_label} - USFS Refill", unit), True)
        else:
            st.info("No USFS refill data")

        st.subheader("USFS Theft")
        if not theft_usfs.empty:
            st.plotly_chart(create_plot_usfs(theft_usfs, f"{region_label} - USFS Theft", unit), True)
        else:
            st.info("No USFS theft data")

        st.markdown("---")
        st.subheader("Probable Variation – Refill")
        if not fill_pv.empty:
            st.plotly_chart(create_plot_pv(fill_pv, f"{region_label} - PV Refill", unit), True)
        else:
            st.info("No PV refill data")

        st.subheader("Probable Variation – Theft")
        if not theft_pv.empty:
            st.plotly_chart(create_plot_pv(theft_pv, f"{region_label} - PV Theft", unit), True)
        else:
            st.info("No PV theft data")

        st.markdown("---")
        st.subheader("Low Fuel Level Alerts")
        if not low_fuel_daily.empty:
            st.plotly_chart(
                create_plot_low_fuel(low_fuel_daily, f"{region_label} - Low Fuel Alerts"),
                use_container_width=True
            )
        else:
            st.info("No low fuel alerts")


# ─────────────────────────────────────────────────────────────────────────────
# FUEL SUMMARY tab
# ─────────────────────────────────────────────────────────────────────────────
with tabs[4]:
    st.session_state.active_tab = 4
    st.markdown("<h2 style='text-align:center;'> Fuel Summary</h2>", unsafe_allow_html=True)
    st.markdown("---")

    for region in ["IND", "NASA", "EU", "FML"]:
        region_label = REGION_DISPLAY_NAMES.get(region, region)
        st.markdown(f"<h4 style='text-align:center;'>{region_label}</h4>", unsafe_allow_html=True)

        data = RESULTS[region]

        dpl_values = build_fuel_summary_values(data["fill_daily"], data["theft_daily"])
        cev_values = build_fuel_summary_values(data["fill_cev_daily"], data["theft_cev_daily"])

        summary_df = pd.DataFrame({
            "Category": [
                f"Total Theft", f"Total Refill",
                f"Moving Average Theft", f"Moving Average Fillings"
            ],
            "DPL":         dpl_values,
            "OFF HIGHWAY": cev_values,
        })
        st.dataframe(summary_df, use_container_width=True, hide_index=True)

        lng_ratio, cng_ratio = build_lng_cng_ratio(data["fill_raw"])
        ratio_lines = []
        if lng_ratio is not None:
            ratio_lines.append(
                f"• Ratio of refill captured in kgs with respect to liters for LNG: <b>{lng_ratio:.2f}%</b>"
            )
        if cng_ratio is not None:
            ratio_lines.append(
                f"• Ratio of refill captured in kgs with respect to liters for CNG: <b>{cng_ratio:.2f}%</b>"
            )
        if ratio_lines:
            st.markdown(
                "<div style='padding:10px 0;'>" + "<br>".join(ratio_lines) + "</div>",
                unsafe_allow_html=True
            )

        st.markdown("---")

        dpl_values = build_tp_fp_table(
            refill_df=data["fill_raw"],
            theft_df=data["theft_raw"],
            ignored_refill_df=data["fill_raw"][data["fill_raw"]["alert_fuel_filling_ignore"] == True]
                if "alert_fuel_filling_ignore" in data["fill_raw"] else pd.DataFrame(),
            ignored_theft_df=data["theft_raw"][data["theft_raw"]["alert_fuel_theft_ignore"] == True]
                if "alert_fuel_theft_ignore" in data["theft_raw"] else pd.DataFrame(),
        )

        cev_values = build_tp_fp_table(
            refill_df=data["fill_cev"],
            theft_df=data["theft_cev"],
            ignored_refill_df=data["fill_cev"][data["fill_cev"]["alert_fuel_filling_ignore"] == True]
                if "alert_fuel_filling_ignore" in data["fill_cev"] and not data["fill_cev"].empty else pd.DataFrame(),
            ignored_theft_df=data["theft_cev"][data["theft_cev"]["alert_fuel_theft_ignore"] == True]
                if "alert_fuel_theft_ignore" in data["theft_cev"] and not data["theft_cev"].empty else pd.DataFrame(),
        )

        rate_df = pd.DataFrame({
            "Metric":      RATE_CATEGORIES,
            "DPL":         dpl_values,
            "OFF HIGHWAY": cev_values,
        })
        st.dataframe(rate_df, use_container_width=True, hide_index=True)
        st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOSS tab
# ─────────────────────────────────────────────────────────────────────────────
with tabs[5]:
    st.session_state.active_tab = 5
    st.markdown("<h2 style='text-align:center;'> Data Loss Summary</h2>", unsafe_allow_html=True)

    for region in REGIONS.keys():
        region_label = REGION_DISPLAY_NAMES.get(region, region)
        summary = RESULTS[region].get("data_loss_summary", pd.DataFrame())
        st.markdown(f"<h4 style='text-align:center;'>{region_label} Region</h4>", unsafe_allow_html=True)
        if not summary.empty:
            st.dataframe(summary, use_container_width=True, hide_index=True)
        else:
            st.info(f"No data loss events for {region_label}")
        st.markdown("---")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN DASHBOARD tab
# ─────────────────────────────────────────────────────────────────────────────
with tabs[6]:
    st.session_state.active_tab = 6
    st.markdown(
        """
        <script>
        window.open('https://intangles-fuel-trends.streamlit.app/', '_blank');
        </script>
        <div style="text-align:center; padding: 60px 20px;">
            <h3>Opening Main Dashboard...</h3>
            <p>If it did not open automatically, 
            <a href="https://intangles-fuel-trends.streamlit.app/" target="_blank" 
               style="font-size:18px; font-weight:bold;">
               click here to open the Main Dashboard
            </a></p>
        </div>
        """,
        unsafe_allow_html=True
    )


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT DATA tab
# ─────────────────────────────────────────────────────────────────────────────
with tabs[7]:
    st.session_state.active_tab = 7   # record we're on this tab
    st.markdown("<h2 style='text-align:center;'>📥 Export Dashboard Data</h2>", unsafe_allow_html=True)
    st.markdown("---")
    st.info(
        "**Export Instructions:** Select a region and data type below to download the raw data as CSV. "
        "All exports respect the selected date range from the dashboard."
    )

    def _set_tab7():
        st.session_state.active_tab = 7

    export_region = st.selectbox(
        "Select Region", options=["IND", "NASA", "EU", "FML"],
        key="export_region_select", on_change=_set_tab7
    )
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🚛 DPL Data (On-Highway)")
        if not RESULTS[export_region]["theft_raw"].empty:
            st.download_button(
                label=f"📥 Download DPL Theft Alerts ({len(RESULTS[export_region]['theft_raw'])} records)",
                data=RESULTS[export_region]["theft_raw"].to_csv(index=False),
                file_name=f"{export_region}_DPL_Theft_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_theft_{export_region}"
            )
        else:
            st.info("No DPL theft data available")

        if not RESULTS[export_region]["fill_raw"].empty:
            st.download_button(
                label=f"📥 Download DPL Filling Alerts ({len(RESULTS[export_region]['fill_raw'])} records)",
                data=RESULTS[export_region]["fill_raw"].to_csv(index=False),
                file_name=f"{export_region}_DPL_Filling_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_fill_{export_region}"
            )
        else:
            st.info("No DPL filling data available")

    with col2:
        st.subheader("🚜 CEV Data (Off-Highway)")
        if not RESULTS[export_region]["theft_cev"].empty:
            st.download_button(
                label=f"📥 Download CEV Theft Alerts ({len(RESULTS[export_region]['theft_cev'])} records)",
                data=RESULTS[export_region]["theft_cev"].to_csv(index=False),
                file_name=f"{export_region}_CEV_Theft_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_theft_cev_{export_region}"
            )
        else:
            st.info("No CEV theft data available")

        if not RESULTS[export_region]["fill_cev"].empty:
            st.download_button(
                label=f"📥 Download CEV Filling Alerts ({len(RESULTS[export_region]['fill_cev'])} records)",
                data=RESULTS[export_region]["fill_cev"].to_csv(index=False),
                file_name=f"{export_region}_CEV_Filling_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_fill_cev_{export_region}"
            )
        else:
            st.info("No CEV filling data available")

    st.markdown("---")
    st.subheader("📊 Probable Variation Data")
    col3, col4 = st.columns(2)

    with col3:
        pv_theft = (
            RESULTS[export_region]["theft_raw"][
                ~RESULTS[export_region]["theft_raw"]["probable_variation_max"].isna()
            ]
            if "probable_variation_max" in RESULTS[export_region]["theft_raw"].columns
            else pd.DataFrame()
        )
        if not pv_theft.empty:
            st.download_button(
                label=f"📥 Download PV Theft ({len(pv_theft)} records)",
                data=pv_theft.to_csv(index=False),
                file_name=f"{export_region}_PV_Theft_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_pv_theft_{export_region}"
            )
        else:
            st.info("No probable variation theft data available")

    with col4:
        pv_fill = (
            RESULTS[export_region]["fill_raw"][
                ~RESULTS[export_region]["fill_raw"]["probable_variation_max"].isna()
            ]
            if "probable_variation_max" in RESULTS[export_region]["fill_raw"].columns
            else pd.DataFrame()
        )
        if not pv_fill.empty:
            st.download_button(
                label=f"📥 Download PV Filling ({len(pv_fill)} records)",
                data=pv_fill.to_csv(index=False),
                file_name=f"{export_region}_PV_Filling_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_pv_fill_{export_region}"
            )
        else:
            st.info("No probable variation filling data available")

    st.markdown("---")
    st.subheader("🏷️ USFS Tagged Data")
    col5, col6 = st.columns(2)

    def _usfs_filter(df):
        if "usfs" not in df.columns or df.empty:
            return pd.DataFrame()
        return df[df["usfs"].apply(
            lambda x: isinstance(x, list) and any(v in ["usfs", "cusfs"] for v in x) if x else False
        )]

    with col5:
        usfs_theft = _usfs_filter(RESULTS[export_region]["theft_raw"])
        if not usfs_theft.empty:
            st.download_button(
                label=f"📥 Download USFS Theft ({len(usfs_theft)} records)",
                data=usfs_theft.to_csv(index=False),
                file_name=f"{export_region}_USFS_Theft_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_usfs_theft_{export_region}"
            )
        else:
            st.info("No USFS theft data available")

    with col6:
        usfs_fill = _usfs_filter(RESULTS[export_region]["fill_raw"])
        if not usfs_fill.empty:
            st.download_button(
                label=f"📥 Download USFS Filling ({len(usfs_fill)} records)",
                data=usfs_fill.to_csv(index=False),
                file_name=f"{export_region}_USFS_Filling_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_usfs_fill_{export_region}"
            )
        else:
            st.info("No USFS filling data available")

    st.markdown("---")
    st.subheader("⚠️ Low Fuel & Data Loss Alert Data")
    col7, col8 = st.columns(2)

    with col7:
        if not RESULTS[export_region]["low_fuel_raw"].empty:
            st.download_button(
                label=f"📥 Download Low Fuel Alerts ({len(RESULTS[export_region]['low_fuel_raw'])} records)",
                data=RESULTS[export_region]["low_fuel_raw"].to_csv(index=False),
                file_name=f"{export_region}_Low_Fuel_Alerts_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_low_fuel_{export_region}"
            )
        else:
            st.info("No low fuel alert data available")

    with col8:
        if not RESULTS[export_region]["data_loss_raw"].empty:
            st.download_button(
                label=f"📥 Download Data Loss Alerts ({len(RESULTS[export_region]['data_loss_raw'])} records)",
                data=RESULTS[export_region]["data_loss_raw"].to_csv(index=False),
                file_name=f"{export_region}_Data_Loss_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"download_data_loss_{export_region}"
            )
        else:
            st.info("No data loss events available")

    st.markdown("---")
    st.subheader("📦 Combined Export")
    st.markdown("Download all available data for the selected region in a single CSV file with a 'Data Type' column.")

    if st.button(f"📦 Generate Combined Export for {export_region}", key=f"combined_export_{export_region}"):
        all_data = []

        def _tag(df, label):
            if not df.empty:
                d = df.copy()
                d["Data_Type"] = label
                all_data.append(d)

        _tag(RESULTS[export_region]["theft_raw"], "DPL_Theft")
        _tag(RESULTS[export_region]["fill_raw"],  "DPL_Filling")
        _tag(RESULTS[export_region]["theft_cev"], "CEV_Theft")
        _tag(RESULTS[export_region]["fill_cev"],  "CEV_Filling")

        if not pv_theft.empty:
            _tag(pv_theft, "PV_Theft")
        if not pv_fill.empty:
            _tag(pv_fill,  "PV_Filling")

        _tag(_usfs_filter(RESULTS[export_region]["theft_raw"]), "USFS_Theft")
        _tag(_usfs_filter(RESULTS[export_region]["fill_raw"]),  "USFS_Filling")
        _tag(RESULTS[export_region]["low_fuel_raw"],  "Low_Fuel_Alert")
        _tag(RESULTS[export_region]["data_loss_raw"], "Data_Loss")

        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True, sort=False)
            cols = ["Data_Type"] + [c for c in combined_df.columns if c != "Data_Type"]
            combined_df = combined_df[cols]

            st.download_button(
                label=f"⬇️ Download {export_region} Combined Export (CSV)",
                data=combined_df.to_csv(index=False),
                file_name=f"{export_region}_Combined_Export_{START_DATE}_{END_DATE}.csv",
                mime="text/csv", key=f"combined_download_{export_region}"
            )
            st.success(f"Combined export ready for {export_region}! Total records: {len(combined_df):,}")
        else:
            st.warning(f"No data available for {export_region} in the selected date range.")


# ─────────────────────────────────────────────────────────────────────────────
# TIME RANGE EXPORT tab  (live fetch, custom date range)
# ─────────────────────────────────────────────────────────────────────────────
with tabs[8]:
    st.session_state.active_tab = 8   # record we're on this tab
    st.markdown("<h2 style='text-align:center;'>📅 Time Range Export</h2>", unsafe_allow_html=True)
    st.info(
        "Select a region, data types, and a **custom date range** then click **Fetch & Export**. "
        "Data is fetched live from the API for that exact window — independent of the dashboard date range above."
    )
    st.markdown("---")

    def _set_tab8():
        st.session_state.active_tab = 8

    # ── Controls row ──────────────────────────────────────────────────────────
    tr_col1, tr_col2, tr_col3, tr_col4 = st.columns([2, 2, 2, 2])

    with tr_col1:
        tr_region = st.selectbox(
            "Region",
            options=["IND", "NASA", "EU", "FML"],
            format_func=lambda r: REGION_DISPLAY_NAMES.get(r, r),
            key="tr_region", on_change=_set_tab8
        )

    with tr_col2:
        tr_start = st.date_input(
            "From Date",
            value=(pd.Timestamp.now() - pd.Timedelta(days=12)).date(),
            key="tr_start", on_change=_set_tab8
        )

    with tr_col3:
        tr_end = st.date_input(
            "To Date",
            value=(pd.Timestamp.now() - pd.Timedelta(days=2)).date(),
            key="tr_end", on_change=_set_tab8
        )

    with tr_col4:
        st.markdown("<br>", unsafe_allow_html=True)   # vertical align with inputs
        tr_fetch = st.button("🚀 Fetch & Export", key="tr_fetch_btn", use_container_width=True, on_click=_set_tab8)

    # ── Data type checkboxes ──────────────────────────────────────────────────
    st.markdown("**Select data types to export:**")

    cb_col1, cb_col2, cb_col3, cb_col4, cb_col5, cb_col6, cb_col7 = st.columns(7)
    with cb_col1:
        cb_theft      = st.checkbox("DPL Theft",    value=True,  key="cb_theft",     on_change=_set_tab8)
    with cb_col2:
        cb_fill       = st.checkbox("DPL Filling",  value=True,  key="cb_fill",      on_change=_set_tab8)
    with cb_col3:
        cb_cev_theft  = st.checkbox("CEV Theft",    value=False, key="cb_cev_theft", on_change=_set_tab8)
    with cb_col4:
        cb_cev_fill   = st.checkbox("CEV Filling",  value=False, key="cb_cev_fill",  on_change=_set_tab8)
    with cb_col5:
        cb_low_fuel   = st.checkbox("Low Fuel",     value=False, key="cb_low_fuel",  on_change=_set_tab8)
    with cb_col6:
        cb_data_loss  = st.checkbox("Data Loss",    value=False, key="cb_data_loss", on_change=_set_tab8)
    with cb_col7:
        cb_combined   = st.checkbox("Combined CSV", value=False, key="cb_combined",
                                    help="Merge all selected types into one file with a Data_Type column",
                                    on_change=_set_tab8)

    st.markdown("---")

    # ── Fetch on button click ─────────────────────────────────────────────────
    if tr_fetch:
        if not any([cb_theft, cb_fill, cb_cev_theft, cb_cev_fill, cb_low_fuel, cb_data_loss]):
            st.warning("Please select at least one data type.")
        elif tr_start > tr_end:
            st.error("'From Date' must be before 'To Date'.")
        else:
            tr_start_ms = int(pd.Timestamp(tr_start).normalize().timestamp() * 1000)
            tr_end_ms   = int((pd.Timestamp(tr_end).normalize() + pd.Timedelta(days=1)).timestamp() * 1000)
            tr_url      = REGIONS[tr_region]
            tr_unit     = UNIT_MAP[tr_region]
            tr_label    = REGION_DISPLAY_NAMES.get(tr_region, tr_region)
            date_tag    = f"{tr_start}_{tr_end}"

            # Import live fetch functions
            from data_fetcher import (
                fetch_batches,
                fetch_low_fuel_batches,
                fetch_data_loss_batches,
                safe_parse_variation,
                ensure_timestamp_consistency,
                clean_common_filters,
                build_cev_df,
                add_usfs_column,
                build_data_loss_summary,
                GALLON_CONVERSION,
                MCE_TYPES,
            )

            needs_theft_fill = cb_theft or cb_fill or cb_cev_theft or cb_cev_fill
            needs_low_fuel   = cb_low_fuel
            needs_data_loss  = cb_data_loss

            theft_df = fill_df = low_fuel_df = data_loss_df = pd.DataFrame()
            theft_cev_df = fill_cev_df = pd.DataFrame()

            # ── Fetch theft + filling ─────────────────────────────────────────
            if needs_theft_fill:
                with st.spinner(f"Fetching theft & filling data for {tr_label} …"):
                    raw_theft, raw_fill = fetch_batches(tr_start_ms, tr_end_ms, tr_url)

                    # probable_variation
                    for df_ref, label in [(raw_theft, "theft"), (raw_fill, "fill")]:
                        if "probable_variation" in df_ref.columns:
                            df_ref["probable_variation_max"] = df_ref["probable_variation"].apply(safe_parse_variation)
                        else:
                            df_ref["probable_variation_max"] = None

                    # NASA gallon conversion
                    if tr_region == "NASA":
                        for df_ref in [raw_theft, raw_fill]:
                            if "amount" in df_ref.columns:
                                df_ref["amount"] *= GALLON_CONVERSION

                    # FML kg override
                    if tr_region == "FML":
                        if "Amount_kgs" in raw_theft.columns:
                            raw_theft["amount"] = raw_theft["Amount_kgs"]
                        if "Amount_kgs" in raw_fill.columns:
                            raw_fill["amount"]  = raw_fill["Amount_kgs"]

                    # Timestamps
                    raw_theft = ensure_timestamp_consistency(raw_theft)
                    raw_fill  = ensure_timestamp_consistency(raw_fill)

                    # CEV split (before DPL filter)
                    theft_cev_df = build_cev_df(raw_theft)
                    fill_cev_df  = build_cev_df(raw_fill)

                    # DPL filter
                    theft_df = clean_common_filters(raw_theft)
                    fill_df  = clean_common_filters(raw_fill)

                    # USFS tags
                    theft_df = add_usfs_column(theft_df)
                    fill_df  = add_usfs_column(fill_df)

                st.success(
                    f"Fetched: **{len(theft_df):,}** DPL theft  |  "
                    f"**{len(fill_df):,}** DPL filling  |  "
                    f"**{len(theft_cev_df):,}** CEV theft  |  "
                    f"**{len(fill_cev_df):,}** CEV filling"
                )

            # ── Fetch low fuel ────────────────────────────────────────────────
            if needs_low_fuel:
                with st.spinner(f"Fetching low fuel alerts for {tr_label} …"):
                    low_fuel_df = fetch_low_fuel_batches(tr_start_ms, tr_end_ms, tr_url)
                    low_fuel_df = ensure_timestamp_consistency(low_fuel_df)
                    low_fuel_df = clean_common_filters(low_fuel_df)
                st.success(f"Fetched: **{len(low_fuel_df):,}** low fuel alerts")

            # ── Fetch data loss ───────────────────────────────────────────────
            if needs_data_loss:
                with st.spinner(f"Fetching data loss events for {tr_label} …"):
                    data_loss_df = fetch_data_loss_batches(tr_start_ms, tr_end_ms, tr_url)
                    data_loss_df = ensure_timestamp_consistency(data_loss_df)
                st.success(f"Fetched: **{len(data_loss_df):,}** data loss events")

            st.markdown("---")

            # Import daily builders for charting
            from data_fetcher import (
                build_daily_df,
                build_daily_alert_count_df,
                build_daily_pv_df,
                build_daily_amount_df,
            )

            # ── Legend ────────────────────────────────────────────────────────
            st.markdown(
                """
                <div style="
                    background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                    padding: 10px 24px; border-radius: 8px; margin-bottom: 14px;
                    text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                ">
                    <span style="font-size:16px;font-weight:bold;color:#333;margin-right:24px;">Legend:</span>
                    <span style="font-size:17px;color:#1e88e5;margin-right:20px;">
                        <span style="display:inline-block;width:32px;height:3px;background:#1e88e5;vertical-align:middle;margin-right:6px;"></span>
                        <strong>Daily Amount / Count</strong>
                    </span>
                    <span style="font-size:17px;color:#43a047;">
                        <span style="display:inline-block;width:32px;height:3px;background:#43a047;border-top:2px dotted #43a047;vertical-align:middle;margin-right:6px;"></span>
                        <strong>Moving Average</strong>
                    </span>
                </div>
                """,
                unsafe_allow_html=True
            )

            # ── Helper: chart + download block ────────────────────────────────
            def _chart_and_download(raw_df, chart_title, dl_label,
                                     filename, dl_key, plot_type="amount"):
                """
                Renders a chart from raw_df and a download button below it.
                plot_type: "amount" | "low_fuel" | "pv"
                """
                if raw_df is None or raw_df.empty:
                    st.info(f"No data available for **{chart_title}**")
                    return

                # Build daily aggregate
                if plot_type == "amount":
                    daily = build_daily_df(raw_df)
                elif plot_type == "low_fuel":
                    daily = build_daily_alert_count_df(raw_df)
                elif plot_type == "pv":
                    pv_df = raw_df[~raw_df["probable_variation_max"].isna()].copy() \
                        if "probable_variation_max" in raw_df.columns else pd.DataFrame()
                    daily = build_daily_pv_df(pv_df)
                else:
                    daily = build_daily_df(raw_df)

                # Draw chart
                if not daily.empty:
                    if plot_type == "low_fuel":
                        fig = create_plot_low_fuel(daily, chart_title)
                    elif plot_type == "pv":
                        fig = create_plot_pv(daily, chart_title, tr_unit)
                    else:
                        fig = create_plot(daily, chart_title, tr_unit)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info(f"No daily data to plot for **{chart_title}**")

                # Download button directly below the chart
                dl_col1, dl_col2, dl_col3 = st.columns([4, 2, 2])
                with dl_col1:
                    st.caption(f"{len(raw_df):,} raw records")
                with dl_col3:
                    st.download_button(
                        label=f"📥 {dl_label}",
                        data=raw_df.to_csv(index=False),
                        file_name=filename,
                        mime="text/csv",
                        key=dl_key,
                        on_click=_set_tab8
                    )
                st.markdown("---")

            # ── Render each selected type ─────────────────────────────────────
            if cb_theft:
                _chart_and_download(
                    theft_df,
                    f"{tr_label} – DPL Theft",
                    "Download DPL Theft CSV",
                    f"{tr_region}_DPL_Theft_{date_tag}.csv",
                    "tr_dl_theft",
                    plot_type="amount"
                )

            if cb_fill:
                _chart_and_download(
                    fill_df,
                    f"{tr_label} – DPL Filling",
                    "Download DPL Filling CSV",
                    f"{tr_region}_DPL_Filling_{date_tag}.csv",
                    "tr_dl_fill",
                    plot_type="amount"
                )

            if cb_cev_theft:
                _chart_and_download(
                    theft_cev_df,
                    f"{tr_label} – CEV Theft",
                    "Download CEV Theft CSV",
                    f"{tr_region}_CEV_Theft_{date_tag}.csv",
                    "tr_dl_cev_theft",
                    plot_type="amount"
                )

            if cb_cev_fill:
                _chart_and_download(
                    fill_cev_df,
                    f"{tr_label} – CEV Filling",
                    "Download CEV Filling CSV",
                    f"{tr_region}_CEV_Filling_{date_tag}.csv",
                    "tr_dl_cev_fill",
                    plot_type="amount"
                )

            if cb_low_fuel:
                _chart_and_download(
                    low_fuel_df,
                    f"{tr_label} – Low Fuel Alerts",
                    "Download Low Fuel CSV",
                    f"{tr_region}_Low_Fuel_{date_tag}.csv",
                    "tr_dl_low_fuel",
                    plot_type="low_fuel"
                )

            if cb_data_loss:
                # Data loss: show summary bar chart + raw download
                if data_loss_df is not None and not data_loss_df.empty:
                    from data_fetcher import build_data_loss_summary
                    dl_summary = build_data_loss_summary(data_loss_df)

                    if not dl_summary.empty:
                        st.subheader(f"{tr_label} – Data Loss Breakdown")
                        bar_fig = go.Figure(data=[
                            go.Bar(
                                x=dl_summary["Data loss type"],
                                y=dl_summary["Count"],
                                marker_color="#667eea",
                                text=dl_summary["Count"],
                                textposition="outside"
                            )
                        ])
                        bar_fig.update_layout(
                            xaxis_title="Loss Type",
                            yaxis_title="Count",
                            height=380,
                            margin=dict(t=40, b=60, l=60, r=40),
                            xaxis=dict(tickfont=dict(size=13)),
                            yaxis=dict(tickfont=dict(size=13))
                        )
                        st.plotly_chart(bar_fig, use_container_width=True)
                        st.dataframe(dl_summary, use_container_width=True, hide_index=True)
                    else:
                        st.info("No data loss type breakdown available.")

                    dl_col1, _, dl_col3 = st.columns([4, 2, 2])
                    with dl_col1:
                        st.caption(f"{len(data_loss_df):,} raw records")
                    with dl_col3:
                        st.download_button(
                            label="📥 Download Data Loss CSV",
                            data=data_loss_df.to_csv(index=False),
                            file_name=f"{tr_region}_Data_Loss_{date_tag}.csv",
                            mime="text/csv",
                            key="tr_dl_data_loss",
                            on_click=_set_tab8
                        )
                    st.markdown("---")
                else:
                    st.info(f"No data loss events for {tr_label}")

            # ── Combined CSV ──────────────────────────────────────────────────
            if cb_combined:
                all_combined = []

                def _tag_and_append(df, label):
                    if df is not None and not df.empty:
                        d = df.copy()
                        d["Data_Type"] = label
                        all_combined.append(d)

                if cb_theft:      _tag_and_append(theft_df,     "DPL_Theft")
                if cb_fill:       _tag_and_append(fill_df,      "DPL_Filling")
                if cb_cev_theft:  _tag_and_append(theft_cev_df, "CEV_Theft")
                if cb_cev_fill:   _tag_and_append(fill_cev_df,  "CEV_Filling")
                if cb_low_fuel:   _tag_and_append(low_fuel_df,  "Low_Fuel_Alert")
                if cb_data_loss:  _tag_and_append(data_loss_df, "Data_Loss")

                if all_combined:
                    combined_tr = pd.concat(all_combined, ignore_index=True, sort=False)
                    cols = ["Data_Type"] + [c for c in combined_tr.columns if c != "Data_Type"]
                    combined_tr = combined_tr[cols]

                    st.download_button(
                        label=f"⬇️ Download Combined CSV — {len(combined_tr):,} total records",
                        data=combined_tr.to_csv(index=False),
                        file_name=f"{tr_region}_Combined_{date_tag}.csv",
                        mime="text/csv",
                        key="tr_dl_combined",
                        on_click=_set_tab8
                    )
                    st.success(f"Combined export ready: **{len(combined_tr):,}** records across {len(all_combined)} data type(s).")
                else:
                    st.warning("No data to combine.")

            # ── API errors (if any) ───────────────────────────────────────────
            tr_errors = get_api_errors()
            if tr_errors:
                with st.expander(f"⚠️ {len(tr_errors)} API error(s) during fetch — click to view"):
                    for err in tr_errors:
                        st.code(err)


st.caption("© Intangles | Fuel Monitoring Dashboard")
