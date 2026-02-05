import streamlit as st
import pandas as pd
import numpy as np
import datetime
import os

# --- 設定 ---
DATA_FILE = 'my_run_log.csv'

# --- 1. データ管理機能 (CSV) ---
def load_data():
    if not os.path.exists(DATA_FILE):
        # 初回起動時は空のデータフレームを作成
        return pd.DataFrame(columns=['Date', 'RHR', 'Distance', 'RPE', 'Type'])
    return pd.read_csv(DATA_FILE)

def save_entry(date, rhr, dist, rpe, session_type):
    df = load_data()
    new_data = pd.DataFrame({
        'Date': [date],
        'RHR': [rhr],
        'Distance': [dist],
        'RPE': [rpe],
        'Type': [session_type]
    })
    # 日付は文字列として保存
    new_data['Date'] = pd.to_datetime(new_data['Date']).dt.strftime('%Y-%m-%d')
    
    # 同じ日付があれば上書き、なければ追加
    df = pd.concat([df, new_data])
    df['Date'] = pd.to_datetime(df['Date']) # 日付型に変換
    df = df.sort_values('Date').drop_duplicates(subset=['Date'], keep='last')
    
    # CSVに書き出し
    df.to_csv(DATA_FILE, index=False)
    return df

# --- 2. 科学的判定ロジック (Colabで実験済みのもの) ---
def analyze_condition(df, today_rhr):
    # 計算用にコピー
    calc_df = df.copy()
    calc_df['Date'] = pd.to_datetime(calc_df['Date'])
    calc_df = calc_df.sort_values('Date')
    
    # 指標計算
    calc_df['Load'] = calc_df['Distance'] * calc_df['RPE']
    calc_df['Acute'] = calc_df['Load'].rolling(7).mean()
    calc_df['Chronic'] = calc_df['Load'].rolling(28).mean()
    
    # ゼロ除算回避
    calc_df['ACWR'] = calc_df.apply(lambda x: x['Acute']/x['Chronic'] if x['Chronic'] > 0 else 0, axis=1)
    
    calc_df['RHR_Mean'] = calc_df['RHR'].rolling(30).mean()
    calc_df['RHR_Std'] = calc_df['RHR'].rolling(30).std()

    # 最新(昨日)のデータ
    if len(calc_df) == 0:
        return 100, "GREEN", ["データがありません。まずは入力を！"], calc_df

    last_log = calc_df.iloc[-1]
    
    score = 100
    warnings = []

    # A. 自律神経監査
    if not np.isnan(last_log['RHR_Std']) and last_log['RHR_Std'] > 0:
        z_score = (today_rhr - last_log['RHR_Mean']) / last_log['RHR_Std']
        if z_score > 2.0:
            score -= 40
            warnings.append(f"⛔ 心拍異常 (+2σ): {today_rhr} (平均 {last_log['RHR_Mean']:.1f})")
        elif z_score > 1.0:
            score -= 20
            warnings.append(f"⚠️ 心拍高め (+1σ): {today_rhr}")

    # B. ACWR監査
    current_acwr = last_log['ACWR']
    if current_acwr > 1.5:
        score -= 30
        warnings.append(f"⛔ 怪我リスク大 (ACWR {current_acwr:.2f})")
    elif current_acwr > 1.3:
        score -= 10
        warnings.append(f"⚠️ 急激な負荷増 (ACWR {current_acwr:.2f})")

    # C. 神経監査
    if last_log['Type'] == 'Anaerobic':
        score -= 10
        warnings.append("💡 CNS回復: 昨日は解糖系でした。ジョグ推奨。")

    # 総合判定
    status = "GREEN"
    if score < 50: status = "RED"
    elif score < 80: status = "YELLOW"

    return score, status, warnings, calc_df

# --- 3. UI構築 (iPhone向け) ---
st.set_page_config(page_title="Run Monitor", page_icon="🏃")
st.title("Run Readiness Monitor")

# タブ切り替え
tab1, tab2 = st.tabs(["今日の判定", "昨日のログ入力"])

# --- TAB 2: データ入力 ---
with tab2:
    st.header("📝 昨日のトレーニング記録")
    with st.form("log_form"):
        date = st.date_input("日付", datetime.date.today() - datetime.timedelta(days=1))
        rhr = st.number_input("その日のRHR", 40, 100, 45)
        dist = st.number_input("距離 (km)", 0.0, 50.0, 10.0)
        rpe = st.slider("きつさ (RPE)", 1, 10, 5)
        type_ = st.selectbox("タイプ", ["Jog", "Long", "Tempo", "Interval", "Anaerobic", "Rest"])
        
        if st.form_submit_button("保存する"):
            save_entry(date, rhr, dist, rpe, type_)
            st.success("保存しました！タブ1に戻って判定してください。")

# --- TAB 1: 判定 ---
with tab1:
    st.header("📊 今日のコンディション")
    
    df = load_data()
    today_rhr = st.number_input("今朝の心拍数 (bpm)", 30, 100, 42)
    
    if st.button("判定スタート", type="primary", use_container_width=True):
        if len(df) < 7:
            st.info(f"データ蓄積中です... (現在 {len(df)}日分)")
            # データ不足でも動くようにダミー表示
            score, status, msgs, res_df = analyze_condition(df, today_rhr)
        else:
            score, status, msgs, res_df = analyze_condition(df, today_rhr)
        
        # 結果表示
        if status == "RED":
            st.error(f"⛔ STOP (Score: {score})")
            st.write("**推奨:** 完全休養")
        elif status == "YELLOW":
            st.warning(f"⚠️ CAUTION (Score: {score})")
            st.write("**推奨:** ジョグのみ")
        else:
            st.success(f"✅ GO (Score: {score})")
            st.write("**推奨:** ポイント練習OK")

        # 理由
        for msg in msgs:
            st.info(msg)
            
        # グラフ (CPA向け可視化)
        if len(df) > 0:
            st.write("---")
            st.caption("トレンド分析")
            chart_data = res_df.set_index('Date')[['RHR', 'ACWR']]
            st.line_chart(chart_data['ACWR'])
            st.line_chart(chart_data['RHR'])
