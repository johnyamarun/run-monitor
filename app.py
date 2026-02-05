import streamlit as st
import pandas as pd
import numpy as np
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import json

# --- 設定: Google Sheets連携 (Chromebook対策版) ---
# Secretsから取得したJSONに混ざった改行コードを強制削除して読み込む
try:
    # 1. Secretsからデータを取得 (TOMLの ''' で囲まれた文字列として取得)
    if "gcp_service_account" not in st.secrets:
        st.error("Secretsの設定が見つかりません。[gcp_service_account] セクションを確認してください。")
        st.stop()

    raw_json = st.secrets["gcp_service_account"]["json_key"]

    # 2. Chromebookが勝手に入れた制御文字(\n, \r)をすべて削除し、きれいな1行のJSONに戻す
    # これで "Invalid control character" エラーを回避します
    clean_json = raw_json.replace('\n', '').replace('\r', '')

    # 3. JSONとして読み込む
    key_dict = json.loads(clean_json)

    # 4. 認証と接続
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    
    # ★★★ 重要: ここをご自身のスプレッドシートURLに書き換えてください！ ★★★
    # 例: SHEET_URL = "https://docs.google.com/spreadsheets/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/edit"
    SHEET_URL = "https://docs.google.com/spreadsheets/d/xxxxxxxxxxxxxxxxxxxxxxxxxxxxx/edit" 
    
    sheet = client.open_by_url(SHEET_URL).sheet1

except json.JSONDecodeError as e:
    st.error(f"JSON解析エラー: キーの貼り付け形式を確認してください。\n詳細: {e}")
    st.stop()
except Exception as e:
    st.error(f"接続エラー: {e}")
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
    try:
        # 文字列変換
        date_str = date.strftime('%Y-%m-%d')
        # 追加する行データ
        row = [date_str, rhr, dist, rpe, session_type]
        # スプレッドシートの末尾に追加
        sheet.append_row(row)
        st.toast("スプレッドシートに保存しました！")
    except Exception as e:
        st.error(f"保存失敗: {e}")

# --- 2. 科学的判定ロジック ---
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
    
    calc_df['ACWR'] = calc_df.apply(lambda x
