import streamlit as st
st.set_page_config(
    page_title="Fuel Monitoring - TV Display",
    layout="wide",
    initial_sidebar_state="collapsed"
)
import pandas as pd
import time
from streamlit_autorefresh import st_autorefresh


try:
    from dashboard_utils import (
        REGIONS, 
        UNIT_MAP,
        LOGO_BASE64,
        load_all_regions,
        create_plot,
        create_plot_usfs,
        create_plot_low_fuel,
        create_plot_pv
    )
except ImportError:
    st.error("Could not import from 'dashboard.py'. Please ensure the file exists and contains required functions.")
    st.stop()



TV_PLOT_CONFIG = {
    "displayModeBar": False,
    "staticPlot": True,
    "responsive": False,
    "scrollZoom": False
}


ROTATION_MINUTES = 1


RESULTS = load_all_regions()

# if st.button("🔄", help="Refresh Data"):
#     from drive_cache import get_drive_service, get_root_folder_id, upload_checkpoint
#     from dashboard_utils import REGIONS
    
#     service = get_drive_service()
#     root_folder_id = get_root_folder_id()
    
#     # Set checkpoint to end of Feb 16 (yesterday-2days)
#     # So it only fetches Feb 17 (the missing day)
#     now = pd.Timestamp.now() - pd.Timedelta(days=2)
#     yesterday = now.normalize()  # start of today-2days = end of previous day
#     yesterday_ms = int(yesterday.timestamp() * 1000) - 1  # end of Feb 16
    
#     for region in REGIONS.keys():
#         upload_checkpoint(service, region, yesterday_ms, root_folder_id)
    
#     st.cache_resource.clear()
#     st.rerun()


if 'rotation_start_time' not in st.session_state:
    st.session_state.rotation_start_time = time.time()
if 'last_view' not in st.session_state:
    st.session_state.last_view = None
if 'show_loading' not in st.session_state:
    st.session_state.show_loading = True


elapsed_seconds = time.time() - st.session_state.rotation_start_time
rotation_seconds = ROTATION_MINUTES * 60
cycle_position = int(elapsed_seconds // rotation_seconds) % 9


VIEW_ORDER = [
    "IND_REFILL", "IND_THEFT",
    "NASA_REFILL", "NASA_THEFT",
    "EU_REFILL", "EU_THEFT",
    "FML_REFILL", "FML_THEFT",
    "LOW_FUEL"
]
current_view = VIEW_ORDER[cycle_position]


if st.session_state.last_view != current_view:
    st.session_state.show_loading = True

st.session_state.last_view = current_view


st_autorefresh(interval=ROTATION_MINUTES * 60 * 1000, key="view_auto_rotate")


st.markdown(
    """
    <style>
    /* Smooth fade-in and slide animation */
    @keyframes fadeInSlide {
        0% { 
            opacity: 0; 
            transform: translateY(30px) scale(0.98);
        }
        100% { 
            opacity: 1; 
            transform: translateY(0) scale(1);
        }
    }
    
    @keyframes fadeOut {
        0% { 
            opacity: 1; 
            transform: scale(1);
        }
        100% { 
            opacity: 0; 
            transform: scale(0.95);
        }
    }
    
    /* Loading spinner animation */
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    
    @keyframes loadingFadeOut {
        0% { opacity: 1; }
        100% { opacity: 0; pointer-events: none; }
    }
    
    .dashboard-container {
        animation: fadeInSlide 1.5s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    .dashboard-container.fade-out {
        animation: fadeOut 0.8s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Hide Streamlit elements for TV */
    footer, header, .stDeployButton {
        visibility: hidden !important;
    }
    
    /* Hide all top controls */
    [data-testid="stHorizontalBlock"]:first-of-type,
    .stTabs,
    [data-testid="column"]:has(> div > div > label),
    # button {
    #     display: none !important;
    # }
    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }

    footer { display: none !important; }
    
    
    /* Force fullscreen mode - remove ALL padding */
    .main {
        padding: 0 !important;
        margin: 0 !important;
    }
    
    /* Optimize for TV display */
    .main .block-container {
        padding: 0.5rem 1rem 0rem 1rem !important;
        max-width: 100% !important;
    }
    
    /* Make all content fill screen */
    # section[data-testid="stAppViewContainer"] {
    #     padding: 0 !important;
    # }
    
    /* Remove top padding */
    .appview-container {
        padding-top: 0 !important;
    }
    
    /* Remove top gap */
    [data-testid="stAppViewBlockContainer"] {
        padding-top: 0 !important;
    }
    
    /* Smooth chart transitions */
    .js-plotly-plot {
        transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Enhanced view header - more compact */
    .view-header {
        animation: fadeInSlide 1s cubic-bezier(0.4, 0, 0.2, 1);
        text-align: center;
        padding: 8px 20px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 8px;
        margin-bottom: 8px;
        box-shadow: 0 8px 30px rgba(102, 126, 234, 0.3);
        position: relative;
        overflow: hidden;
    }
    
    /* Loading overlay */
    .loading-overlay {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(102, 126, 234, 0.95);
        # backdrop-filter: blur(5px);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        animation: loadingFadeOut 0.8s ease-out 1.2s forwards;
        z-index: 10;
    }
    
    .loading-spinner {
        width: 50px;
        height: 50px;
        border: 4px solid rgba(255, 255, 255, 0.3);
        border-top: 4px solid white;
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin-bottom: 15px;
    }
    
    .loading-text {
        color: white;
        font-size: 20px;
        font-weight: bold;
        animation: pulse 1.5s ease-in-out infinite;
    }
    
    .view-title {
        color: white;
        font-size: 36px;
        margin: 0;
        font-weight: bold;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
        # animation: pulse 2s ease-in-out;
    }
    
    .view-subtitle {
        color: #e0e0e0;
        font-size: 16px;
        margin: 4px 0;
    }
    
    /* Enhanced progress bar with glow */
    .progress-container {
        width: 100%;
        height: 4px;
        background: rgba(255,255,255,0.2);
        border-radius: 3px;
        margin-top: 6px;
        overflow: hidden;
        box-shadow: 0 0 10px rgba(79, 172, 254, 0.3);
    }
    
    .progress-bar {
        height: 100%;
        background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
        border-radius: 3px;
        box-shadow: 0 0 15px rgba(79, 172, 254, 0.8);
        animation-name: progress-animation;
        animation-timing-function: linear;
        animation-fill-mode: forwards;
    }
    
    @keyframes progress-animation {
        0% { width: 0%; }
        100% { width: 100%; }
    }
    
    /* Chart row animation with stagger effect */
    .chart-row {
        animation: fadeInSlide 1.5s cubic-bezier(0.4, 0, 0.2, 1);
        margin-bottom: 8px;
    }
    
    .chart-row:nth-child(1) { animation-delay: 0.1s; }
    .chart-row:nth-child(2) { animation-delay: 0.2s; }
    .chart-row:nth-child(3) { animation-delay: 0.3s; }
    .chart-row:nth-child(4) { animation-delay: 0.4s; }
    
    /* Individual chart animation */
    .stPlotlyChart {
        animation: fadeInSlide 1.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    
    /* Countdown timer styling */
    .countdown-timer {
        font-weight: bold;
        color: #4facfe;
        text-shadow: 0 0 10px rgba(79, 172, 254, 0.5);
    }
    
    /* Compact legend for TV */
    .tv-legend {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 6px 20px;
        border-radius: 6px;
        margin-bottom: 6px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    /* Warning banner styling - more compact */
    .data-warning {
        background: linear-gradient(135deg, #fff3cd 0%, #ffc107 50%, #ff9800 100%);
        padding: 8px 20px;
        border-radius: 6px;
        margin-bottom: 8px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(255, 152, 0, 0.3);
        border-left: 5px solid #ff6f00;
        animation: pulse 2s ease-in-out infinite;
    }
    
    .warning-icon {
        font-size: 20px;
        margin-right: 8px;
        vertical-align: middle;
    }
    
    .warning-text {
        color: #663c00;
        font-size: 16px;
        font-weight: bold;
        display: inline-block;
        vertical-align: middle;
    }
    
    /* Reduce bottom spacing */
    .element-container {
        margin-bottom: 0 !important;
    }
    
    /* Compact captions */
    .stCaption {
        margin-top: 4px !important;
        font-size: 12px !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Countdown timer JavaScript
rotation_duration = ROTATION_MINUTES * 60
st.markdown(
    f"""
    <script>
    (function() {{
        const ROTATION_SECONDS = {rotation_duration};
        
        function updateCountdown() {{
            const now = new Date();
            const minutesSinceMidnight = now.getHours() * 60 + now.getMinutes();
            const secondsSinceMidnight = minutesSinceMidnight * 60 + now.getSeconds();
            
            const secondsInCurrentCycle = secondsSinceMidnight % ROTATION_SECONDS;
            const secondsRemaining = ROTATION_SECONDS - secondsInCurrentCycle;
            
            const minutesRemaining = Math.floor(secondsRemaining / 60);
            const secondsRemainingInMinute = secondsRemaining % 60;
            
            const countdownElement = document.querySelector('.countdown-timer');
            if (countdownElement) {{
                countdownElement.textContent = minutesRemaining + ':' + secondsRemainingInMinute.toString().padStart(2, '0');
            }}
            
            if (secondsRemaining <= 2) {{
                const container = document.querySelector('.dashboard-container');
                if (container) {{
                    container.classList.add('fade-out');
                }}
            }}
        }}
        
        setInterval(updateCountdown, 1000);
        updateCountdown();
    }})();
    </script>
    """,
    unsafe_allow_html=True
)

# View display names
next_view = VIEW_ORDER[(cycle_position + 1) % 9]

view_display_names = {
    "IND_REFILL": "🇮🇳 India - Refills",
    "IND_THEFT": "🇮🇳 India - Thefts",
    "NASA_REFILL": "🇺🇸 US - Refills",
    "NASA_THEFT": "🇺🇸 US - Thefts",
    "EU_REFILL": "🇪🇺 Europe - Refills",
    "EU_THEFT": "🇪🇺 Europe - Thefts",
    "FML_REFILL": "🇮🇳 Force Motors - Refills",
    "FML_THEFT": "🇮🇳 Force Motors - Thefts",
    "LOW_FUEL": "⛽ Low Fuel Alerts"
}

region_display_names = {
    "IND": "India",
    "NASA": "US",
    "EU": "Europe",
    "FML": "FML"
}

next_view_display = view_display_names.get(next_view, next_view)

# Loading overlay
if st.session_state.show_loading:
    loading_div = '<div class="loading-overlay"><div class="loading-spinner"></div><div class="loading-text">Loading Data...</div></div>'
else:
    loading_div = ''

# Progress bar
progress_duration = ROTATION_MINUTES * 60
progress_key = f"progress-{current_view}-{cycle_position}"


view_title = view_display_names.get(current_view, current_view)

#calculating bad ------
import streamlit.components.v1 as components



timer_html = f"""
<div style="position: relative; width: 70px; height: 70px; display: inline-block;">
    <svg style="transform: rotate(-90deg); width: 70px; height: 70px;">
        <circle cx="35" cy="35" r="30" fill="none" stroke="rgba(255,255,255,0.3)" stroke-width="4"></circle>
        <circle id="timer-circle-{progress_key}" cx="35" cy="35" r="30" fill="none" stroke="#00D4FF" stroke-width="4" stroke-dasharray="188.4" stroke-dashoffset="188.4" style="animation: countdown-circle-{progress_key} {progress_duration}s linear forwards;"></circle>
    </svg>
    <div id="timer-text-{progress_key}" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 14px; font-weight: bold; color: #00D4FF;">{progress_duration}</div>
</div>
"""


complete_html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
body {{
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
}}

.view-header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 30px 30px;  /* Increased from 20px to 30px */
    border-radius: 10px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    min-height: 120px;  /* Added minimum height */
}}

.view-title {{
    font-size: 28px;
    font-weight: bold;
    margin: 0 0 10px 0;  /* Added bottom margin */
    color: white;
    text-align: center;
}}

.view-subtitle {{
    font-size: 16px;
    color: rgba(255, 255, 255, 0.9);
    margin: 10px 0;  /* Increased margin */
    text-align: center;
}}

.view-subtitle strong {{
    color: white;
    font-weight: 600;
}}

.progress-container {{
    width: 100%;
    height: 6px;  /* Increased from 4px to 6px */
    background: rgba(255, 255, 255, 0.3);
    border-radius: 3px;
    overflow: hidden;
    margin-top: 15px;  /* Increased from 12px to 15px */
}}

.progress-bar {{
    height: 100%;
    background: linear-gradient(90deg, #00D4FF, #ffffff);
    animation: progress-animation 0s linear forwards;
}}

@keyframes progress-animation {{
    from {{ width: 0%; }}
    to {{ width: 100%; }}
}}

@keyframes countdown-circle-{progress_key} {{
  from {{ stroke-dashoffset: 188.4; }}
  to {{ stroke-dashoffset: 0; }}
}}

.countdown-timer {{
    color: #00D4FF;
    font-weight: bold;
}}
</style>
</head>
<body>
<div class="view-header" style="display: flex; justify-content: space-between; align-items: center;">
    <div style="display: flex; justify-content: flex-start; align-items: center; gap: 20px; margin-right: 20px;">
        <img src="data:image/png;base64,{LOGO_BASE64}" style="height: 70px; max-width: 260px; width: auto; image-rendering: -webkit-optimize-contrast; image-rendering: crisp-edges;" />
    </div>
    <div style="flex: 1;">
        <h1 class="view-title">{view_title}</h1>
        <p class="view-subtitle">Next: <strong>{next_view_display}</strong> <span style="margin-left: 15px;"> <span class="countdown-timer">Calculating...</span></span></p>
        <div class="progress-container"><div class="progress-bar {progress_key}" style="animation-duration: {progress_duration}s;"></div></div>
    </div>
    <div style="display: flex; justify-content: flex-end; align-items: center; gap: 20px; margin-left: 20px;">
        {timer_html}
    </div>
</div>

<script>
(function() {{
    let remaining = {progress_duration};
    const timerEl = document.getElementById("timer-text-{progress_key}");
    if (timerEl) {{
        const interval = setInterval(() => {{
            remaining--;
            const minutes = Math.floor(remaining / 60);
            const seconds = remaining % 60;
            timerEl.textContent = minutes + ':' + (seconds < 10 ? '0' : '') + seconds;
            if (remaining <= 0) {{
                clearInterval(interval);
                timerEl.textContent = '0:00';
            }}
        }}, 1000);
    }}
}})();
</script>
</body>
</html>
"""

components.html(complete_html, height=180, scrolling=False) 


# Update loading state
if st.session_state.show_loading:
    st.session_state.show_loading = False

# Dashboard container
# st.markdown('<div class="dashboard-container">', unsafe_allow_html=True)

# LOW FUEL ALERTS VIEW
if current_view == "LOW_FUEL":
    st.markdown(
        """
        <div class="tv-legend">
            <span style="font-size: 25px; font-weight: bold; color: #333; margin-right: 20px;">
                Chart Legend:
            </span>
            <span style="font-size: 28px; color: #1e88e5; margin-right: 18px;">
                <span style="display: inline-block; width: 30px; height:5px; background: #1e88e5; vertical-align: middle; margin-right: 6px;"></span>
                <strong>Alert Count</strong>
            </span>
            <span style="font-size: 28px; color: #d32f2f;">
                <span style="display: inline-block; width: 30px; height: 5px; background: #d32f2f; border-top: 2px dotted #d32f2f; vertical-align: middle; margin-right: 6px;"></span>
                <strong>Moving Average</strong>
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    # Collect low fuel charts from all regions
    low_fuel_charts = []
    missing_regions = []
    
    for region_key in ["IND", "NASA", "EU", "FML"]:
        if region_key in RESULTS:
            low_fuel_data = RESULTS[region_key].get("low_fuel_daily", pd.DataFrame())
            if not low_fuel_data.empty:
                low_fuel_charts.append((region_key, low_fuel_data))
            else:
                missing_regions.append(region_display_names.get(region_key, region_key))
    
    # Show warning if any regions have missing data
    if missing_regions:
        warning_text = f"No Low Fuel Alert data available for: {', '.join(missing_regions)}"
        st.markdown(
            f"""
            <div class="data-warning">
                <span class="warning-icon">⚠️</span>
                <span class="warning-text">{warning_text}</span>
            </div>
            """,
            unsafe_allow_html=True
        )
    
    if len(low_fuel_charts) == 0:
        st.info("No low fuel alerts available for any region")
    elif len(low_fuel_charts) == 1:
        region_key, low_fuel_data = low_fuel_charts[0]
        fig = create_plot_low_fuel(low_fuel_data, f"{region_display_names[region_key]} - Low Fuel Alerts")
        fig.update_layout(height=900)
        st.plotly_chart(fig, use_container_width=True, config=TV_PLOT_CONFIG,key=f"lowfuel_{region_key}")
    elif len(low_fuel_charts) == 2:
        col1, col2 = st.columns(2)
        
        region_key1, low_fuel_data1 = low_fuel_charts[0]
        with col1:
            fig = create_plot_low_fuel(low_fuel_data1, f"{region_display_names[region_key1]} - Low Fuel Alerts")
            fig.update_layout(height=900)
            st.plotly_chart(fig, use_container_width=True, key=f"lowfuel_{region_key1}")
        
        region_key2, low_fuel_data2 = low_fuel_charts[1]
        with col2:
            fig = create_plot_low_fuel(low_fuel_data2, f"{region_display_names[region_key2]} - Low Fuel Alerts")
            fig.update_layout(height=900)
            st.plotly_chart(fig, use_container_width=True, key=f"lowfuel_{region_key2}")
    else:
        num_charts = len(low_fuel_charts)
        num_rows = (num_charts + 1) // 2
        chart_height = 430
        
        chart_index = 0
        for row in range(num_rows):
            st.markdown(f'<div class="chart-row" style="animation-delay: {row * 0.1}s;">', unsafe_allow_html=True)
            
            remaining_charts = num_charts - chart_index
            num_cols = min(2, remaining_charts)
            
            if num_cols == 1:
                region_key, low_fuel_data = low_fuel_charts[chart_index]
                fig = create_plot_low_fuel(low_fuel_data, f"{region_display_names[region_key]} - Low Fuel Alerts")
                fig.update_layout(height=chart_height)
                st.plotly_chart(fig, use_container_width=True, config=TV_PLOT_CONFIG,key=f"lowfuel_{region_key}")
                chart_index += 1
            else:
                cols = st.columns(2)
                
                for col_idx, col in enumerate(cols):
                    if chart_index < num_charts:
                        region_key, low_fuel_data = low_fuel_charts[chart_index]
                        with col:
                            fig = create_plot_low_fuel(low_fuel_data, f"{region_display_names[region_key]} - Low Fuel Alerts")
                            fig.update_layout(height=chart_height)
                            st.plotly_chart(fig, use_container_width=True, config=TV_PLOT_CONFIG,key=f"lowfuel_{region_key}")
                        chart_index += 1
            
            st.markdown('</div>', unsafe_allow_html=True)

# REGIONAL REFILL VIEWS
elif current_view.endswith("_REFILL"):
    region_key = current_view.replace("_REFILL", "")
    region_name = region_display_names.get(region_key, region_key)
    
    st.markdown(
        """
        <div class="tv-legend">
            <span style="font-size: 25px; font-weight: bold; color: #333; margin-right: 20px;">
                Chart Legend:
            </span>
            <span style="font-size: 28px; color: #1e88e5; margin-right: 18px;">
                <span style="display: inline-block; width: 35px; height: 4px; background: #1e88e5; vertical-align: middle; margin-right: 6px;"></span>
                <strong>Daily Amount</strong>
            </span>
            <span style="font-size: 28px; color: #43a047;">
                <span style="display: inline-block; width: 35px; height: 4px; background: #43a047; border-top: 2px dotted #43a047; vertical-align: middle; margin-right: 6px;"></span>
                <strong>Moving Average</strong>
            </span>
        </div>
        """,

        unsafe_allow_html=True
    )
    
    if region_key not in RESULTS:
        st.error(f"Data not available for {region_name}")
    else:
        unit = UNIT_MAP[region_key]
        data = RESULTS[region_key]
        
        # Collect refill charts
        refill_charts = []
        missing_types = []
        
        # DPL Refill
        if not data["fill_daily"].empty:
            refill_charts.append(("DPL Refill", data["fill_daily"], create_plot))
        else:
            missing_types.append("DPL Refill")
        
        # CEV Refill
        if not data["fill_cev_daily"].empty:
            refill_charts.append(("CEV Refill", data["fill_cev_daily"], create_plot))
        else:
            missing_types.append("CEV Refill")
        
        # PV Refill
        if not data["fill_pv_daily"].empty:
            refill_charts.append(("Probable Variation Refill", data["fill_pv_daily"], create_plot_pv))
        else:
            missing_types.append("Probable Variation Refill")
        
        # USFS Refill
        if not data["fill_usfs_daily"].empty:
            refill_charts.append(("USFS Refill", data["fill_usfs_daily"], create_plot_usfs))
        else:
            missing_types.append("USFS Refill")
        
        # Show warning if any refill types are missing
        if missing_types:
            warning_text = f"No data available for {region_name}: {', '.join(missing_types)}"
            st.markdown(
                f"""
                <div class="data-warning">
                    <span class="warning-icon">⚠️</span>
                    <span class="warning-text">{warning_text}</span>
                </div>
                """,
                unsafe_allow_html=True
            )
        
        num_charts = len(refill_charts)
        
        if num_charts == 0:
            st.info(f"No refill data available for {region_name}")
        elif num_charts == 1:
            chart_name, chart_data, plot_func = refill_charts[0]
            fig = plot_func(chart_data, f"{region_name} - {chart_name} Daily", unit)
            fig.update_layout(height=900)
            st.plotly_chart(fig, use_container_width=True, key=f"refill_{region_key}_{chart_name}")
        elif num_charts == 2:
            col1, col2 = st.columns(2)
            
            chart_name1, chart_data1, plot_func1 = refill_charts[0]
            with col1:
                fig = plot_func1(chart_data1, f"{region_name} - {chart_name1} Daily", unit)
                fig.update_layout(height=900)
                st.plotly_chart(fig, use_container_width=True, key=f"refill_{region_key}_{chart_name1}")
            
            chart_name2, chart_data2, plot_func2 = refill_charts[1]
            with col2:
                fig = plot_func2(chart_data2, f"{region_name} - {chart_name2} Daily", unit)
                fig.update_layout(height=900)
                st.plotly_chart(fig, use_container_width=True, key=f"refill_{region_key}_{chart_name2}")
        else:
            num_rows = (num_charts + 1) // 2
            chart_height = 430
            
            chart_index = 0
            for row in range(num_rows):
                st.markdown(f'<div class="chart-row" style="animation-delay: {row * 0.1}s;">', unsafe_allow_html=True)
                
                remaining_charts = num_charts - chart_index
                num_cols = min(2, remaining_charts)
                
                if num_cols == 1:
                    chart_name, chart_data, plot_func = refill_charts[chart_index]
                    fig = plot_func(chart_data, f"{region_name} - {chart_name} Daily", unit)
                    fig.update_layout(height=chart_height)
                    st.plotly_chart(fig, use_container_width=True, key=f"refill_{region_key}_{chart_name}")
                    chart_index += 1
                else:
                    cols = st.columns(2)
                    
                    for col_idx, col in enumerate(cols):
                        if chart_index < num_charts:
                            chart_name, chart_data, plot_func = refill_charts[chart_index]
                            with col:
                                fig = plot_func(chart_data, f"{region_name} - {chart_name} Daily", unit)
                                fig.update_layout(height=chart_height)
                                st.plotly_chart(fig, use_container_width=True, key=f"refill_{region_key}_{chart_name}")
                            chart_index += 1
                
                st.markdown('</div>', unsafe_allow_html=True)

# REGIONAL THEFT VIEWS
elif current_view.endswith("_THEFT"):
    region_key = current_view.replace("_THEFT", "")
    region_name = region_display_names.get(region_key, region_key)
    
    st.markdown(
        """
        <div class="tv-legend" style="text-align: center; display: flex; justify-content: center; align-items: center; flex-wrap: wrap; padding: 10px;">
            <span style="font-size: 25px; font-weight: bold; color: #333; margin-right: 20px;">
                Chart Legend:
            </span>
            <span style="font-size: 28px; color: #1e88e5; margin-right: 18px; display: flex; align-items: center;">
                <span style="display: inline-block; width: 30px; height: 3px; background: #1e88e5; vertical-align: middle; margin-right: 6px;"></span>
                <strong>Daily Amount</strong>
            </span>
            <span style="font-size: 28px; color: #43a047; display: flex; align-items: center;">
                <span style="display: inline-block; width: 30px; height: 3px; background: #43a047; border-top: 2px dotted #43a047; vertical-align: middle; margin-right: 6px;"></span>
                <strong>Moving Average</strong>
            </span>
        </div>
        """,
        unsafe_allow_html=True
    )
    
    if region_key not in RESULTS:
        st.error(f"Data not available for {region_name}")
    else:
        unit = UNIT_MAP[region_key]
        data = RESULTS[region_key]
        
        # Collect theft charts
        theft_charts = []
        missing_types = []
        
        # DPL Theft
        if not data["theft_daily"].empty:
            theft_charts.append(("DPL Theft", data["theft_daily"], create_plot))
        else:
            missing_types.append("DPL Theft")
        
        # CEV Theft
        if not data["theft_cev_daily"].empty:
            theft_charts.append(("CEV Theft", data["theft_cev_daily"], create_plot))
        else:
            missing_types.append("CEV Theft")
        
        # PV Theft
        if not data["theft_pv_daily"].empty:
            theft_charts.append(("Probable Variation Theft", data["theft_pv_daily"], create_plot_pv))
        else:
            missing_types.append("Probable Variation Theft")
        
        # USFS Theft
        if not data["theft_usfs_daily"].empty:
            theft_charts.append(("USFS Theft", data["theft_usfs_daily"], create_plot_usfs))
        else:
            missing_types.append("USFS Theft")
        
        # Show warning if any theft types are missing
        if missing_types:
            warning_text = f"No data available for {region_name}: {', '.join(missing_types)}"
            st.markdown(
                f"""
                <div class="data-warning">
                    <span class="warning-icon">⚠️</span>
                    <span class="warning-text">{warning_text}</span>
                </div>
                """,
                unsafe_allow_html=True
            )
        
        num_charts = len(theft_charts)
        
        if num_charts == 0:
            st.info(f"No theft data available for {region_name}")
        elif num_charts == 1:
            chart_name, chart_data, plot_func = theft_charts[0]
            fig = plot_func(chart_data, f"{region_name} - {chart_name} Daily", unit)
            fig.update_layout(height=900)
            st.plotly_chart(fig, use_container_width=True, key=f"theft_{region_key}_{chart_name}")
        elif num_charts == 2:
            col1, col2 = st.columns(2)
            
            chart_name1, chart_data1, plot_func1 = theft_charts[0]
            with col1:
                fig = plot_func1(chart_data1, f"{region_name} - {chart_name1} Daily", unit)
                fig.update_layout(height=900)
                st.plotly_chart(fig, use_container_width=True, key=f"theft_{region_key}_{chart_name1}")
            
            chart_name2, chart_data2, plot_func2 = theft_charts[1]
            with col2:
                fig = plot_func2(chart_data2, f"{region_name} - {chart_name2} Daily", unit)
                fig.update_layout(height=900)
                st.plotly_chart(fig, use_container_width=True, key=f"theft_{region_key}_{chart_name2}")
        else:
            num_rows = (num_charts + 1) // 2
            chart_height = 430
            
            chart_index = 0
            for row in range(num_rows):
                st.markdown(f'<div class="chart-row" style="animation-delay: {row * 0.1}s;">', unsafe_allow_html=True)
                
                remaining_charts = num_charts - chart_index
                num_cols = min(2, remaining_charts)
                
                if num_cols == 1:
                    chart_name, chart_data, plot_func = theft_charts[chart_index]
                    fig = plot_func(chart_data, f"{region_name} - {chart_name} Daily", unit)
                    fig.update_layout(height=chart_height)
                    st.plotly_chart(fig, use_container_width=True, key=f"theft_{region_key}_{chart_name}")
                    chart_index += 1
                else:
                    cols = st.columns(2)
                    
                    for col_idx, col in enumerate(cols):
                        if chart_index < num_charts:
                            chart_name, chart_data, plot_func = theft_charts[chart_index]
                            with col:
                                fig = plot_func(chart_data, f"{region_name} - {chart_name} Daily", unit)
                                fig.update_layout(height=chart_height)
                                st.plotly_chart(fig, use_container_width=True, key=f"theft_{region_key}_{chart_name}")
                            chart_index += 1
                
                st.markdown('</div>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

st.caption("© Intangles | Fuel Monitoring Dashboard")
