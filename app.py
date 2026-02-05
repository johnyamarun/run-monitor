import streamlit as st
import pandas as pd
import numpy as np
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 設定: Google Sheets連携 (Chromebook対策版) ---
try:
    if "gcp_service_account" not in st.secrets:
        st.error("Secretsの設定が見つかりません。")
        st.stop()

    # 改行コード削除処理
    raw_json = st.secrets["gcp_service_account"]["json_key"]
    clean_json = raw_json.replace('\n', '').replace('\r', '')
    key_dict = json.loads(clean_json)

    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    
    # ★★★ ここを書き換える！ ★★★
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1SnWBBSiXkDwvJ0MFs30dTmBk8TVxQl-7sn8ijMdZ6T4/edit?hl=ja&gid=0#gid=0"
    
    sheet = client.open_by_url(SHEET_URL).sheet1

except Exception as e:
    st.error(f"接続エラー: {e}")
    st.stop()

# --- 1. データ管理機能 ---
def load_data():
    try:
        data = sheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=['Date', 'RHR', 'Distance', 'RPE', 'Type'])
        df = pd.DataFrame(data)
        return df
    except:
        return pd.DataFrame(columns=['Date', 'RHR', 'Distance', 'RPE', 'Type'])

def save_entry(date, rhr, dist, rpe, session_type):
    try:
        date_str = date.strftime('%Y-%m-%d')
        row = [date_str, rhr, dist, rpe, session_type]
        sheet.append_row(row)
        st.toast("保存しました！")
    except Exception as e:
        st.error(f"保存失敗: {e}")

# --- 2. 判定ロジック ---
def analyze_condition(df, today_rhr):
    if df.empty:
        return 100, "GREEN", ["データがありません"], df

    calc_df = df.copy()
    calc_df['Date'] = pd.to_datetime(calc_df['Date'])
    calc_df = calc_df.sort_values('Date')
    
    calc_df['Distance'] = pd.to_numeric(calc_df['Distance'])
    calc_df['RPE'] = pd.to_numeric(calc_df['RPE'])
    calc_df['RHR'] = pd.to_numeric(calc_df['RHR'])

    calc_df['Load'] = calc_df['Distance'] * calc_df['RPE']
    calc_df['Acute'] = calc_df['Load'].rolling(7).mean()
    calc_df['Chronic'] = calc_df['Load'].rolling(28).mean()
    
    # ★ ここがエラーだった箇所です！改行せずに1行で貼り付けてください ★
    calc_df['ACWR'] = calc_df.apply(lambda x: x['Acute']/x['Chronic'] if x['Chronic'] > 0 else 0, axis=1)
    
    calc_df['RHR_Mean'] = calc_df['RHR'].rolling(30).mean()
    calc_df['RHR_Std'] = calc_df['RHR'].rolling(30).std()

    last_log = calc_df.iloc[-1]
    score = 100
    warnings = []

    # A. 自律神経
    if not np.isnan(last_log['RHR_Std']) and last_log['RHR_Std'] > 0:
        z_score = (today_rhr - last_log['RHR_Mean']) / last_log['RHR_Std']
        if z_score > 2.0:
            score -= 40
            warnings.append(f"⛔ 心拍異常 (+2σ): {today_rhr}")
        elif z_score > 1.0:
            score -= 20
            warnings.append(f"⚠️ 心拍高め (+1σ): {today_rhr}")

    # B. ACWR
    current_acwr = last_log['ACWR']
    if current_acwr > 1.5:
        score -= 30
        warnings.append(f"⛔ 怪我リスク大 (ACWR {current_acwr:.2f})")
    elif current_acwr > 1.3:
        score -= 10
        warnings.append(f"⚠️ 急激な負荷増 (ACWR {current_acwr:.2f})")

    # C. 神経
    if last_log['Type'] == 'Anaerobic':
        score -= 10
        warnings.append("💡 CNS回復: 昨日は解糖系でした。ジョグ推奨。")

    status = "GREEN"
    if score < 50: status = "RED"
    elif score < 80: status = "YELLOW"

    return score, status, warnings, calc_df

# --- 3. UI構築 ---
st.set_page_config(page_title="Run Monitor", page_icon="🏃")
st.title("Run Readiness Monitor")

tab1, tab2 = st.tabs(["今日の判定", "ログ入力"])

with tab2:
    st.header("📝 ログ登録")
    with st.form("log_form"):
        date = st.date_input("日付", datetime.date.today() - datetime.timedelta(days=1))
        rhr = st.number_input("その日のRHR", 40, 100, 45)
        dist = st.number_input("距離 (km)", 0.0, 50.0, 10.0)
        rpe = st.slider("きつさ (RPE)", 1, 10, 5)
        type_ = st.selectbox("タイプ", ["Jog", "Long", "Tempo", "Interval", "Anaerobic", "Rest"])
        if st.form_submit_button("保存"):
            save_entry(date, rhr, dist, rpe, type_)
            st.cache_data.clear()

with tab1:
    st.header("📊 コンディション判定")
    if st.button("データ読み込み & 判定", type="primary"):
        st.cache_data.clear()
        df = load_data()
        today_rhr = st.number_input("今朝の心拍数", 30, 100, 42)
        score, status, msgs, res_df = analyze_condition(df, today_rhr)
        
        if status == "RED":
            st.error(f"⛔ STOP (Score: {score})")
        elif status == "YELLOW":
            st.warning(f"⚠️ CAUTION (Score: {score})")
        else:
            st.success(f"✅ GO (Score: {score})")
            
        for msg in msgs: st.info(msg)
        
        if not res_df.empty:
            st.line_chart(res_df.set_index('Date')[['ACWR']])
