import json
import ast
import requests
import pandas as pd
from pathlib import Path
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache_data"
WINDOW_DAYS = 10

API_ERRORS = []

def get_api_errors():
    return API_ERRORS

def clear_api_errors():
    global API_ERRORS
    API_ERRORS = []

class DashboardQueryLoader:
    def __init__(self, url, query):
        self.url = url
        self.query = query

    def fetch(self):
        response = requests.post(
            self.url,
            data=self.query,
            headers={"Content-Type": "application/json"},
            timeout=60
        )
        response.raise_for_status()
        return response.json()


REGIONS = {
    "IND": "http://internal-apis.intangles.com/dashboard_apis/fetch",
    "NASA": "https://algo-internal-apis.intangles-aws-us-east-1.intangles.us/dashboard_apis/fetch",
    "EU": "http://algo-internal-apis.intangles-aws-eu-north-1.eu.intangles.com:1234/dashboard_apis/fetch",
    "FML": "http://algo-internal-apis.intangles-fml-aws-ap-south-1.fml.intangles.in/dashboard_apis/fetch"
}


BATCH_SIZE_MS = 2 * 3600 * 1000
MAX_WORKERS = 30
GALLON_CONVERSION = 0.264172

MCE_TYPES = [  'yard_hauler','yard_loader','excavator', 'boom_pump', 'motor_grader',
       'backhoe_loader', 'earth_mover', 'construction_equipment','trommel_machine', 'track_loader', 'soil_compactor', 'horizontal_grinder', 'diesel_forklift',
       'rig_cowl','harvester' ]

EXCLUDED_MODELS = [
    "1623 16T-12M BSiV","2523r 6x2 (cargo) BS3","2523R/2823R 6X2 BSIV",
    "3723R/4223R BSIV","3128C tipper 8x4 Bs3","3128C tipper 8x4 BSIV",
    "3118 IL bs3","3118c BS3","3118c Bs4","Captain 4023 U series TT BS3",
    "3518 (tractor/trailor) BS4","4928T BS3","4928T (5528T) 6x4 BsIV",
    "3123R/3523R BSIV","4023 4x2 BS3","2523C 6x4 Transit mixer pto bsiv",
    "3723R BS3","3123R BS3","2441 Super High Deck BSIV","1109 EX2 BS4",
    "4023T 4x2 BSIV 3600 WB","4023t 4x2 Bsiv 3300 WB","Ultra 1918 BS4",
    "2523C/2823C tipper 6x4 BSIV","2523C 6x4  BS3",
    "2523C 6x4 transit mixer  BS3 pto"
]

def run_region_cached_with_range(region, url, start_ms, end_ms):

    all_data = run_region_cached(region, url)
    

    filtered_data = {}
    
    for key, df in all_data.items():
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            filtered_data[key] = df
            continue
        if isinstance(df, pd.DataFrame) and 'time_ms' in df.columns:
            filtered_data[key] = df[
                (df['time_ms'] >= start_ms) & 
                (df['time_ms'] <= end_ms)
            ].copy()
            if key == "theft_daily":
                filtered_data[key] = build_daily_df(filtered_data["theft_raw"])
            elif key == "fill_daily":
                filtered_data[key] = build_daily_df(filtered_data["fill_raw"])

            elif key == "theft_cev_daily":
                filtered_data[key] = build_daily_df(filtered_data["theft_cev"])
            elif key == "fill_cev_daily":
                filtered_data[key] = build_daily_df(filtered_data["fill_cev"])

            elif key == "low_fuel_daily":
                filtered_data[key] = build_daily_alert_count_df(filtered_data["low_fuel_raw"])
            elif key == "theft_usfs_daily":
                usfs_theft = filtered_data["theft_raw"][
                    filtered_data["theft_raw"]["usfs"].apply(contains_usfs)
                ] if "usfs" in filtered_data["theft_raw"].columns else pd.DataFrame()
                filtered_data[key] = build_daily_amount_df(usfs_theft)
            elif key == "fill_usfs_daily":
                usfs_fill = filtered_data["fill_raw"][
                    filtered_data["fill_raw"]["usfs"].apply(contains_usfs)
                ] if "usfs" in filtered_data["fill_raw"].columns else pd.DataFrame()
                filtered_data[key] = build_daily_amount_df(usfs_fill)
            elif key == "theft_pv_daily":
                filtered_data[key] = build_daily_pv_df(
                    filtered_data["theft_raw"][~filtered_data["theft_raw"]["probable_variation_max"].isna()]
                    if "probable_variation_max" in filtered_data["theft_raw"].columns else pd.DataFrame()
                )
            elif key == "fill_pv_daily":
                filtered_data[key] = build_daily_pv_df(
                    filtered_data["fill_raw"][~filtered_data["fill_raw"]["probable_variation_max"].isna()]
                    if "probable_variation_max" in filtered_data["fill_raw"].columns else pd.DataFrame()
                )
            elif key == "data_loss_summary":
                filtered_data[key] = build_data_loss_summary(filtered_data["data_loss_raw"])
        else:
            filtered_data[key] = df
    
    return filtered_data




def safe_parse_variation(x):
    try:
        if isinstance(x, str):
            x = ast.literal_eval(x)
        if isinstance(x, dict):
            return x.get("max")
    except Exception:
        pass
    return None


def clean_common_filters(df):
    df = df.copy()

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.tz_localize(None)

    if "vehicle_type" in df.columns:
        df = df[~df["vehicle_type"].isin(MCE_TYPES)]

    if "model" in df.columns:
        df = df[~df["model"].isin(EXCLUDED_MODELS)]

    if "account_stage" in df.columns:
        df = df[~df["account_stage"].isin(["closed"])]

    return df

def build_cev_df(df):

    df = df.copy()

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.tz_localize(None)


    if "vehicle_type" in df.columns:
        df = df[df["vehicle_type"].isin(MCE_TYPES)]

    if "account_stage" in df.columns:
        df = df[~df["account_stage"].isin(["closed"])]

    return df




def data_loss_query(start, end):
    return json.dumps({
        "report": "default",
        "filter": [
            {
                "alert_data_loss.timestamp": {
                    "gt": start,
                    "lt": end
                }
            }
        ],
        "select": {
            "alert_data_loss.vehicle_id": {"value": True, "as": "vehicle_id"},
            "alert_data_loss.timestamp": {
                "value": True,
                "as": "time",
                "time_format": "epoch_ms"
            },
            "alert_data_loss.account_id": {"value": True, "as": "account_id"},
            "alert_data_loss.loss_meta": {"value": True, "as": "loss_meta"}
        }
    })


def get_data_loss_alerts(start, end, url):
    return DashboardQueryLoader(url, data_loss_query(start, end)).fetch()
def fetch_data_loss_batches(start_ms, end_ms, url):
    ranges = []
    cur = start_ms

    while cur < end_ms:
        nxt = min(cur + BATCH_SIZE_MS, end_ms)
        ranges.append((cur, nxt))
        cur = nxt

    rows = []

    def fetch_one(s, e):
        try:
            res = get_data_loss_alerts(s, e, url)
            return res.get("result", {}).get("output", [])
        except Exception as err:
            print(f" Data loss fetch error {s} → {e}: {err}")
            error_msg = f" Data loss fetch error {s} → {e}: {err}"
            API_ERRORS.append(error_msg)
            return []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for fut in as_completed([ex.submit(fetch_one, s, e) for s, e in ranges]):
            rows.extend(fut.result())

    return pd.DataFrame(rows)

def prepare_data_loss_table(df, region):
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "region",
                "vehicle_id",
                "time",
                "data_loss_type",
                "account_id"
            ]
        )

    df = df.copy()

    df["data_loss_type"] = df["loss_meta"].apply(
        lambda x: x.get("type").replace("_", " ").capitalize()
        if isinstance(x, dict) and x.get("type")
        else "Unknown"
    )

    df["region"] = region

    return df[[
        "region",
        "vehicle_id",
        "time",
        "data_loss_type",
        "account_id"
    ]]

def build_data_loss_summary(df):
    if df is None or df.empty or "loss_meta" not in df.columns:
        return pd.DataFrame(columns=["Data loss type", "Count"])

    df = df.copy()
    df["Data loss type"] = df["loss_meta"].apply(
        lambda x: x.get("type").replace("_", " ").capitalize()
        if isinstance(x, dict) and x.get("type") else "Unknown"
    )

    summary = (
        df["Data loss type"]
        .value_counts()
        .reset_index()
        .rename(columns={"index": "Data loss type", "Data loss type": "Count"})
    )

    return summary

def low_fuel_query(start, end):
    return json.dumps({
        "report": "default",
        "filter": [
            {
                "alert_fuel_low_level.timestamp": {
                    "gt": start,
                    "lt": end
                }
            }
        ],
        "select": {
            "alert_fuel_low_level.id": {"value": True, "as": "id"},
            "alert_fuel_low_level.timestamp": {
                "value": True,
                "as": "time",
                "time_format": "epoch_ms"
            },
            "alert_fuel_low_level.fuel_level": {"value": True, "as": "fuel_level"},
            "alert_fuel_low_level.vehicle_id": {"value": True, "as": "vehicle_id"},
            "alert_fuel_low_level.account_id": {"value": True, "as": "account_id"},
            "alert_fuel_low_level.type": {"value": True, "as": "type"}
        }
    })
def get_low_fuel_alerts(start, end, url):
    return DashboardQueryLoader(url, low_fuel_query(start, end)).fetch()
def fetch_low_fuel_batches(start_ms, end_ms, url):
    ranges = []
    cur = start_ms

    while cur < end_ms:
        nxt = min(cur + BATCH_SIZE_MS, end_ms)
        ranges.append((cur, nxt))
        cur = nxt

    all_rows = []

    def fetch_one(s, e):
        try:
            res = get_low_fuel_alerts(s, e, url)
            return res.get("result", {}).get("output", [])
        except Exception as err:
            print(f" Low fuel fetch error {s} → {e}: {err}")
            error_msg= f" Low fuel fetch error {s} → {e}: {err}"
            API_ERRORS.append(error_msg)
            return []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(fetch_one, s, e) for s, e in ranges]
        for fut in as_completed(futures):
            all_rows.extend(fut.result())

    return pd.DataFrame(all_rows)
def build_daily_alert_count_df(df):
    if df is None or df.empty or "time" not in df.columns:
        return pd.DataFrame(columns=["time", "vehicle_id", "moving average"])

    df = df.copy()

    # Handle both epoch ms (int) AND ISO string with/without timezone
    if pd.api.types.is_numeric_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    else:
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)

    # Strip timezone safely
    df["time"] = df["time"].dt.tz_convert(None)
    df = df.dropna(subset=["time"])

    if df.empty:
        return pd.DataFrame(columns=["time", "vehicle_id", "moving average"])

    daily = (
        df.groupby(pd.Grouper(key="time", freq="D"))["vehicle_id"]
        .count()
        .reset_index()
    )

    daily["moving average"] = daily["vehicle_id"].expanding().mean()
    return daily

def ensure_time_columns(df):
    if df is None or df.empty or "time" not in df.columns:
        return df

    df = df.copy()

    if pd.api.types.is_numeric_dtype(df["time"]):
        df["time_ms"] = df["time"]
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    else:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df["time_ms"] = df["time"].astype("int64") // 10**6

    df["time"] = df["time"].dt.tz_localize(None)
    return df

def normalize_time(df):
    if df is None or df.empty or "time" not in df.columns:
        return df

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    df["time"] = df["time"].dt.tz_localize(None)
    return df

def normalize_time_ms(df):
    if df is None or df.empty or "time" not in df.columns:
        return df

    df = df.copy()

    if pd.api.types.is_numeric_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    else:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")

    df["time"] = df["time"].dt.tz_localize(None)
    return df

def finalize_time_column(df):
    if df is None or df.empty or "time" not in df.columns:
        return df

    df = df.copy()

    if pd.api.types.is_numeric_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    else:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")


    df["time"] = df["time"].dt.tz_localize(None)
    return df

def build_daily_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["time", "amount", "moving average"])

    if "time" not in df.columns or "amount" not in df.columns:
        return pd.DataFrame(columns=["time", "amount", "moving average"])

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"])

    if df.empty:
        return pd.DataFrame(columns=["time", "amount", "moving average"])

    daily = (
        df.groupby(pd.Grouper(key="time", freq="D"))["amount"]
        .sum()
        .reset_index()
    )

    daily["moving average"] = daily["amount"].expanding().mean()
    return daily

def add_usfs_column(df, col1="vehicle tags", col2="spec tags"):
    if df is None or df.empty:
        df = df.copy()
        df["usfs"] = None
        return df

    def detect_flags(row):
        c1 = row[col1] if isinstance(row.get(col1), list) else str(row.get(col1, "")).lower().split()
        c2 = row[col2] if isinstance(row.get(col2), list) else str(row.get(col2, "")).lower().split()

        tags = c1 + c2
        flags = []

        if "usfs" in tags:
            flags.append("usfs")
        if "cusfs" in tags:
            flags.append("cusfs")

        return flags if flags else None

    df = df.copy()
    df["usfs"] = df.apply(detect_flags, axis=1)
    return df


def contains_usfs(x):
    if isinstance(x, list):
        return any(v in ["usfs", "cusfs"] for v in x)
    return x in ["usfs", "cusfs"]


def build_daily_amount_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["time", "amount", "moving average"])

    if "time" not in df.columns or "amount" not in df.columns:
        return pd.DataFrame(columns=["time", "amount", "moving average"])

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["time"])

    if df.empty:
        return pd.DataFrame(columns=["time", "amount", "moving average"])

    daily = (
        df.groupby(pd.Grouper(key="time", freq="D"))["amount"]
        .sum()
        .reset_index()
    )

    daily["moving average"] = daily["amount"].expanding().mean()
    return daily

def build_daily_pv_df(df):
    if df is None or df.empty:
        return pd.DataFrame(columns=["time", "probable_variation_max", "moving average"])

    if "time" not in df.columns or "probable_variation_max" not in df.columns:
        return pd.DataFrame(columns=["time", "probable_variation_max", "moving average"])

    df = df.copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time", "probable_variation_max"])

    if df.empty:
        return pd.DataFrame(columns=["time", "probable_variation_max", "moving average"])

    daily = (
        df.groupby(pd.Grouper(key="time", freq="D"))["probable_variation_max"]
        .sum()
        .reset_index()
    )

    daily["moving average"] = daily["probable_variation_max"].expanding().mean()
    return daily

def read_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_json(path, lines=True)


def write_jsonl(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path, orient="records", lines=True)


def load_checkpoint(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f).get("last_fetched_ms")


def save_checkpoint(path: Path, ts: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"last_fetched_ms": ts}, f)




def theft_query(start, end):
    return json.dumps({
        "report": "default",
        "filter": [
            {
                "alert_fuel_theft.timestamp": {
                    "gt": start,
                    "lt": end
                }
            }
        ],
        "select": {
            "vehicle.id": {"value": True, "as": "vehicle_id"},
            "account.id": {"value": True, "as": "account_id"},
            "vehicle.tag": {"value": True, "as": "tag"},
            "vehicle.vin": {"value": True, "as": "vin"},
            "account.display_name": {"value": True, "as": "account_name"},
            "alert_fuel_theft.ignore": {"value": True, "as": "alert_fuel_theft_ignore"},
            "alert_fuel_theft.ignore_reasons": {"value": True, "as": "ignore_reasons"},
            "alert_fuel_theft.timestamp": {"value": True, "as": "time"},
            "alert_fuel_theft.amount": {"value": True, "as": "amount"},
            "alert_fuel_theft.amount_in_kgs": {"value": True, "as": "amount_in_kgs"},
            "alert_fuel_theft.probable_variation": {"value": True, "as": "probable_variation"},
            "spec.manufacturer": {"value": True, "as": "spec_manufacturer"},
            "spec.model": {"value": True, "as": "model"},
            "spec.fuel_capacity": {"value": True, "as": "fuel_capacity"},
            "spec.id": {"value": True, "as": "spec_id"},
            "spec.vehicle_type": {"value": True, "as": "vehicle_type"},
            "spec.fuel_type": {"value": True, "as": "fuel_type"},
            "spec.emmission_standard": {"value": True, "as": "emission_standard"},
            "spec.max_load_capacity": {"value": True, "as": "max_load_capacity"},
            "account.stage":{"value":True,"as":"account_stage"},
            "vehicle.tags":{"value":True,"as":"vehicle tags"},
            "spec.tags":{"value":True,"as":"spec tags"}
        
        }
    })


def filling_query(start, end):
    return json.dumps({
        "report": "default",
        "filter": [
            {
                "alert_fuel_filling.timestamp": {
                    "gt": start,
                    "lt": end
                }
            }
        ],
        "select": {
            "vehicle.id": {"value": True, "as": "vehicle_id"},
            "account.id": {"value": True, "as": "account_id"},
            "vehicle.tag": {"value": True, "as": "tag"},
            "vehicle.vin": {"value": True, "as": "vin"},
            "account.display_name": {"value": True, "as": "account_name"},
            "alert_fuel_filling.timestamp": {"value": True, "as": "time"},
            "alert_fuel_filling.id": {"value": True, "as": "id"},
            "alert_fuel_filling.amount": {"value": True, "as": "amount"},
            "alert_fuel_filling.amount_in_kgs": {"value": True, "as": "Amount_kgs"},
            "alert_fuel_filling.ignore": {"value": True, "as": "alert_fuel_filling_ignore"},
            "alert_fuel_filling.probable_variation": {"value": True, "as": "probable_variation"},
            "alert_fuel_filling.ignore_reasons": {"value": True, "as": "ignore_reasons"},
            "spec.manufacturer": {"value": True, "as": "manufacturer"},
            "spec.vehicle_type": {"value": True, "as": "vehicle_type"},
            "spec.fuel_type": {"value": True, "as": "fuel_type"},
            "spec.model": {"value": True, "as": "model"},
            "spec.fuel_capacity": {"value": True, "as": "fuel_capacity"},
            "spec.emmission_standard": {"value": True, "as": "emission_standard"},
            "account.stage":{"value":True,"as":"account_stage"},
            "vehicle.tags":{"value":True,"as":"vehicle tags"},
            "spec.tags":{"value":True,"as":"spec tags"}
        }
    })



def get_theft_alerts(start, end, url):
    return DashboardQueryLoader(url, theft_query(start, end)).fetch()


def get_filling_alerts(start, end, url):
    return DashboardQueryLoader(url, filling_query(start, end)).fetch()



def fetch_batches(start_ms, end_ms, url):
    ranges = []
    cur = start_ms

    while cur < end_ms:
        nxt = min(cur + BATCH_SIZE_MS, end_ms)
        ranges.append((cur, nxt))
        cur = nxt

    theft_all, fill_all = [], []

    def fetch_pair(s, e):
        try:
            t = get_theft_alerts(s, e, url)
            f = get_filling_alerts(s, e, url)
            return (
                t.get("result", {}).get("output", []),
                f.get("result", {}).get("output", [])
            )
        except Exception as err:
            print(f" Error fetching {s} → {e}: {err}")
            error_msg = f" Error fetching {s} → {e}: {err}"
            API_ERRORS.append(error_msg)
            return [], []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(fetch_pair, s, e) for s, e in ranges]

        for fut in as_completed(futures):
            t, fl = fut.result()
            theft_all.extend(t)
            fill_all.extend(fl)

    return pd.DataFrame(theft_all), pd.DataFrame(fill_all)


def ensure_timestamp_consistency(df):
    if df is None or df.empty:
        return df
    
    df = df.copy()
    if pd.api.types.is_numeric_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
    else:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df["time"] = df["time"].dt.tz_localize(None)
    df = df.dropna(subset=["time"])
    df["time_ms"] = df["time"].astype("int64") // 10**6
    
    return df

def read_jsonl(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_json(path, lines=True)
        if not df.empty and "time" in df.columns:
            return ensure_timestamp_consistency(df)
        return df
    except ValueError:
        return pd.DataFrame()

def write_jsonl(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        with open(path, 'w') as f: pass 
        return

    df.to_json(path, orient="records", lines=True, date_format="iso")

def load_checkpoint(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f).get("last_fetched_ms")
    except:
        return None

def save_checkpoint(path: Path, ts: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"last_fetched_ms": ts}, f)

def merge_and_deduplicate(old_df, new_df, subset_cols=None):

    combined = pd.concat([old_df, new_df], ignore_index=True)
    
    if combined.empty:
        return combined

    if subset_cols:

        valid_subset = [c for c in subset_cols if c in combined.columns]
        if valid_subset:
            combined = combined.drop_duplicates(subset=valid_subset, keep="last")
        else:
            combined = combined.drop_duplicates(keep="last")
    else:
        combined = combined.drop_duplicates(keep="last")


    if "time_ms" in combined.columns:
        combined = combined.sort_values(by="time_ms")
        
    return combined
def run_region(region, url, start_ms, end_ms):
    theft_df, fill_df = fetch_batches(start_ms, end_ms, url)

    if "probable_variation" in theft_df.columns:
        theft_df["probable_variation_max"] = theft_df["probable_variation"].apply(safe_parse_variation)
    else:
        theft_df["probable_variation_max"] = None

    if "probable_variation" in fill_df.columns:
        fill_df["probable_variation_max"] = fill_df["probable_variation"].apply(safe_parse_variation)
    else:
        fill_df["probable_variation_max"] = None

    if region == "NASA":
        if "amount" in theft_df.columns:
            theft_df["amount"] *= GALLON_CONVERSION
        if "amount" in fill_df.columns:
            fill_df["amount"] *= GALLON_CONVERSION

    if region == "FML":
        if "Amount_kgs" in theft_df.columns:
            theft_df["amount"] = theft_df["Amount_kgs"]
        
        if "Amount_kgs" in fill_df.columns:
            fill_df["amount"] = fill_df["Amount_kgs"] 

    theft_df = ensure_time_columns(theft_df)
    fill_df = ensure_time_columns(fill_df)


    theft_cev = build_cev_df(theft_df)
    fill_cev = build_cev_df(fill_df)

    theft_df = clean_common_filters(theft_df)
    fill_df = clean_common_filters(fill_df)
    
    low_fuel_df = fetch_low_fuel_batches(start_ms, end_ms, url)
    low_fuel_df = ensure_time_columns(low_fuel_df)
    low_fuel_df = clean_common_filters(low_fuel_df)

    theft_df_pv = theft_df[~theft_df["probable_variation_max"].isna()].copy()
    fill_df_pv = fill_df[~fill_df["probable_variation_max"].isna()].copy()

    theft_df_usfs = add_usfs_column(theft_df)
    fill_df_usfs = add_usfs_column(fill_df)

    theft_df_usfs = theft_df_usfs[theft_df_usfs["usfs"].apply(contains_usfs)].copy()
    fill_df_usfs = fill_df_usfs[fill_df_usfs["usfs"].apply(contains_usfs)].copy()

    return {
        "theft_raw": theft_df,
        "fill_raw": fill_df,
        "low_fuel_raw": low_fuel_df,


        "theft_cev": theft_cev,
        "fill_cev": fill_cev,

        "theft_daily": build_daily_df(theft_df),
        "fill_daily": build_daily_df(fill_df),
        "low_fuel_daily": build_daily_alert_count_df(low_fuel_df),


        "theft_cev_daily": build_daily_df(theft_cev),
        "fill_cev_daily": build_daily_df(fill_cev),

        "theft_raw_pv": theft_df_pv,
        "fill_raw_pv": fill_df_pv,
        "theft_pv_daily": build_daily_pv_df(theft_df_pv),
        "fill_pv_daily": build_daily_pv_df(fill_df_pv),

        "theft_raw_usfs": theft_df_usfs,
        "fill_raw_usfs": fill_df_usfs,
        "theft_usfs_daily": build_daily_amount_df(theft_df_usfs),
        "fill_usfs_daily": build_daily_amount_df(fill_df_usfs),
    }
def run_region_cached(region, url):
    from drive_cache import (
        get_drive_service, get_root_folder_id,
        download_jsonl, upload_jsonl,
        download_checkpoint, upload_checkpoint
    )

    service = get_drive_service()
    root_folder_id = get_root_folder_id()

    WINDOW_DAYS = 10
    now = pd.Timestamp.now() - pd.Timedelta(days=2)
    now_ms = int((now.normalize() + pd.Timedelta(days=1)).timestamp() * 1000)
    window_start = now.normalize() - pd.Timedelta(days=WINDOW_DAYS)
    window_start_ms = int(window_start.timestamp() * 1000)

    # ── Download existing cache from Drive ──
    theft_all     = download_jsonl(service, region, "theft.jsonl",     root_folder_id)
    fill_all      = download_jsonl(service, region, "fill.jsonl",      root_folder_id)
    low_fuel_all  = download_jsonl(service, region, "low_fuel.jsonl",  root_folder_id)
    data_loss_all = download_jsonl(service, region, "data_loss.jsonl", root_folder_id)
    theft_cev_all = download_jsonl(service, region, "theft_cev.jsonl", root_folder_id)
    fill_cev_all  = download_jsonl(service, region, "fill_cev.jsonl",  root_folder_id)

    last_fetched_ms = download_checkpoint(service, region, root_folder_id)

    # ── Determine what date range to fetch ──
    fetch_start_ms = (
        last_fetched_ms + 1
        if last_fetched_ms and last_fetched_ms > window_start_ms
        else window_start_ms
    )

    # ── Fetch new delta from APIs ──
    if fetch_start_ms < now_ms:
        print(f"[{region}] Fetching delta: "
              f"{pd.to_datetime(fetch_start_ms, unit='ms')} → Now")

        fresh = run_region(region, url, fetch_start_ms, now_ms)

        theft_all = merge_and_deduplicate(
            ensure_timestamp_consistency(theft_all),
            ensure_timestamp_consistency(fresh["theft_raw"]),
            subset_cols=["vehicle_id", "time_ms"]
        )
        fill_all = merge_and_deduplicate(
            ensure_timestamp_consistency(fill_all),
            ensure_timestamp_consistency(fresh["fill_raw"]),
            subset_cols=["id"]
        )
        low_fuel_all = merge_and_deduplicate(
            ensure_timestamp_consistency(low_fuel_all),
            ensure_timestamp_consistency(fresh["low_fuel_raw"]),
            subset_cols=["id"]
        )
        theft_cev_all = merge_and_deduplicate(
            ensure_timestamp_consistency(theft_cev_all),
            ensure_timestamp_consistency(fresh["theft_cev"]),
            subset_cols=["vehicle_id", "time_ms"]
        )
        fill_cev_all = merge_and_deduplicate(
            ensure_timestamp_consistency(fill_cev_all),
            ensure_timestamp_consistency(fresh["fill_cev"]),
            subset_cols=["id"]
        )

        dl_fresh = fetch_data_loss_batches(fetch_start_ms, now_ms, url)
        dl_fresh = ensure_timestamp_consistency(dl_fresh)
        data_loss_all = merge_and_deduplicate(
            ensure_timestamp_consistency(data_loss_all),
            clean_common_filters(dl_fresh),
            subset_cols=["vehicle_id", "time_ms"]
        )

    # ── Trim to rolling 10-day window (removes oldest day) ──
    def trim(df):
        if df is not None and not df.empty and "time_ms" in df.columns:
            return df[df["time_ms"] >= window_start_ms].copy()
        return df

    theft_all     = trim(theft_all)
    fill_all      = trim(fill_all)
    low_fuel_all  = trim(low_fuel_all)
    data_loss_all = trim(data_loss_all)
    theft_cev_all = trim(theft_cev_all)
    fill_cev_all  = trim(fill_cev_all)

    # ── Upload updated cache back to Drive ──
    if fetch_start_ms < now_ms:
        upload_jsonl(service, theft_all,     region, "theft.jsonl",     root_folder_id)
        upload_jsonl(service, fill_all,      region, "fill.jsonl",      root_folder_id)
        upload_jsonl(service, low_fuel_all,  region, "low_fuel.jsonl",  root_folder_id)
        upload_jsonl(service, data_loss_all, region, "data_loss.jsonl", root_folder_id)
        upload_jsonl(service, theft_cev_all, region, "theft_cev.jsonl", root_folder_id)
        upload_jsonl(service, fill_cev_all,  region, "fill_cev.jsonl",  root_folder_id)
        upload_checkpoint(service, region, now_ms, root_folder_id)

    # ── Add usfs column ──
    if not theft_all.empty: theft_all = add_usfs_column(theft_all)
    if not fill_all.empty:  fill_all  = add_usfs_column(fill_all)

    # ── Build derived dataframes ──
    theft_all_pv = (
        theft_all[~theft_all["probable_variation_max"].isna()].copy()
        if "probable_variation_max" in theft_all.columns else pd.DataFrame()
    )
    fill_all_pv = (
        fill_all[~fill_all["probable_variation_max"].isna()].copy()
        if "probable_variation_max" in fill_all.columns else pd.DataFrame()
    )

    return {
        "theft_raw":       theft_all,
        "fill_raw":        fill_all,
        "low_fuel_raw":    low_fuel_all,
        "data_loss_raw":   data_loss_all,
        "theft_cev":       theft_cev_all,
        "fill_cev":        fill_cev_all,
        "data_loss_table": prepare_data_loss_table(data_loss_all, region),
        "data_loss_summary": build_data_loss_summary(data_loss_all),
        "low_fuel_daily":  build_daily_alert_count_df(low_fuel_all),
        "theft_daily":     build_daily_df(theft_all),
        "fill_daily":      build_daily_df(fill_all),
        "theft_cev_daily": build_daily_df(theft_cev_all),
        "fill_cev_daily":  build_daily_df(fill_cev_all),
        "theft_usfs_daily": build_daily_amount_df(
            theft_all[theft_all["usfs"].apply(contains_usfs)]
            if "usfs" in theft_all.columns and not theft_all.empty
            else pd.DataFrame()
        ),
        "fill_usfs_daily": build_daily_amount_df(
            fill_all[fill_all["usfs"].apply(contains_usfs)]
            if "usfs" in fill_all.columns and not fill_all.empty
            else pd.DataFrame()
        ),
        "theft_pv_daily":  build_daily_pv_df(theft_all_pv),
        "fill_pv_daily":   build_daily_pv_df(fill_all_pv),
    }

if __name__ == "__main__":

    end_time = pd.Timestamp.now() - pd.Timedelta(days=2)
    end_time_ms = int((pd.Timestamp(end_time).normalize() + pd.Timedelta(days=1)).timestamp() * 1000)
    start_time = end_time - pd.Timedelta(days=10)
    start_time_ms = int(pd.Timestamp(start_time).normalize().timestamp() * 1000)

    for region, url in REGIONS.items():
        print(f"Processing {region}...")

        out = run_region_cached(region, url)
        print(f"Result {region}: {len(out['theft_daily'])} theft days, {len(out['fill_daily'])} fill days")

    print(f"{region}Data fetcher OK")
