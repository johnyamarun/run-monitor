import streamlit as st
import pandas as pd
import numpy as np
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 設定: Google Sheets連携 ---
# StreamlitのSecretsから鍵情報を取得
# Secretsには [gcp_service_account] の下に json_key = """...""" として保存されている前提
try:
    key_dict = json.loads(st.secrets["gcp_service_account"]["json_key"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    
    # スプレッドシートを開く (シート名またはURL)
    # ※Secretsで指定するか、ハードコードするかですが、ここではURLを直接指定が確実
    # ★重要: Step 1で作ったシートのURLをここに貼ってください
    SHEET_URL = "https://docs.google.com/spreadsheets/d/xxxxxxxxxxxxxxxxx/edit" 
    sheet = client.open_by_url(SHEET_URL).sheet1
except Exception as e:
    st.error(f"Google Sheets接続エラー: {e}")
    st.stop()

# --- 1. データ管理機能 (GSheets版) ---
def load_data():
    try:
        data = sheet.get_all_records()
        if not data:
            return pd.DataFrame(columns=['Date', 'RHR', 'Distance', 'RPE', 'Type'])
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        return pd.DataFrame(columns=['Date', 'RHR', 'Distance', 'RPE', 'Type'])

def save_entry(date, rhr, dist, rpe, session_type):
    # 文字列変換
    date_str = date.strftime('%Y-%m-%d')
    # 追加する行データ
    row = [date_str, rhr, dist, rpe, session_type]
    # スプレッドシートの末尾に追加
    sheet.append_row(row)
    st.toast("スプレッドシートに保存しました！")

# --- 2. 科学的判定ロジック (変更なし) ---
def analyze_condition(df, today_rhr):
    # データフレームが空の場合の処理
    if df.empty:
        return 100, "GREEN", ["データがありません。入力を開始してください。"], df

    calc_df = df.copy()
    calc_df['Date'] = pd.to_datetime(calc_df['Date'])
    calc_df = calc_df.sort_values('Date')
    
    # 型変換（念のため）
    calc_df['Distance'] = pd.to_numeric(calc_df['Distance'])
    calc_df['RPE'] = pd.to_numeric(calc_df['RPE'])
    calc_df['RHR'] = pd.to_numeric(calc_df['RHR'])

    calc_df['Load'] = calc_df['Distance'] * calc_df['RPE']
    calc_df['Acute'] = calc_df['Load'].rolling(7).mean()
    calc_df['Chronic'] = calc_df['Load'].rolling(28).mean()
    
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
st.title("Run Readiness Monitor (Cloud DB)")

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
            # キャッシュクリアしてリロードしないと最新データが反映されないため
            st.cache_data.clear()
            st.success("保存しました！")

with tab1:
    st.header("📊 コンディション判定")
    if st.button("データ読み込み & 判定"):
        st.cache_data.clear() # 最新データを強制取得
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
