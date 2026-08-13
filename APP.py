import os
import sys
import webbrowser
from datetime import datetime
import pandas as pd
import yfinance as yf
import traceback
import uuid  # 用來生成每一筆回測的唯一 ID，達成多視窗獨立讀取
from flask import Flask, request, render_template_string, redirect, url_for

app = Flask(__name__)

# 記憶體資料庫：用來存放多個視窗各自的回測報告結果
reports_storage = {}

# --- 前端網頁：溫和莫蘭迪深藍灰、柔亮護眼參數輸入表單 ---
INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>策略回測系統 - 參數輸入</title>
    <style>
        body { font-family: 'Microsoft JhengHei', sans-serif; background-color: #2b323f; margin: 0; padding: 40px; color: #e9ecef; }
        .container { max-width: 650px; margin: 0 auto; background: #353d4e; padding: 30px; border-radius: 12px; box-shadow: 0 8px 25px rgba(0,0,0,0.2); border: 1px solid #414b5f; }
        h1 { text-align: center; color: #5dade2; margin-bottom: 30px; font-size: 1.8rem; letter-spacing: 1px; }
        .section-title { border-left: 5px solid #5dade2; padding-left: 10px; margin: 25px 0 15px 0; color: #85c1e9; font-weight: bold; font-size: 1.05rem; }
        .form-group { display: flex; margin-bottom: 15px; align-items: center; }
        .form-group label { width: 250px; font-weight: bold; color: #cbd5e1; font-size: 0.95rem; }
        .form-group input { flex: 1; padding: 10px 14px; background-color: #2b323f; border: 1px solid #4a5568; border-radius: 6px; font-size: 0.95rem; color: #fff; transition: border 0.2s; }
        .form-group input:focus { border-color: #5dade2; outline: none; box-shadow: 0 0 5px rgba(93,173,226,0.3); }
        button { width: 100%; padding: 14px; background-color: #4a90e2; color: white; border: none; border-radius: 6px; font-size: 1.1rem; font-weight: bold; cursor: pointer; margin-top: 25px; transition: background 0.2s, transform 0.1s; }
        button:hover { background-color: #357abd; }
        button:active { transform: scale(0.99); }
        .hint { text-align: center; font-size: 0.8rem; color: #94a3b8; margin-top: 10px; }
    </style>
</head>
<body>
<div class="container">
    <h1>📊 策略回測系統 (參數設定)</h1>
    <form action="/run" method="POST" target="_blank">
        <div class="section-title">基本標的與時間</div>
        <div class="form-group">
            <label>[A欄位] A股市代號：</label>
            <input type="text" name="ticker_A" value="00631L" required>
        </div>
        <div class="form-group">
            <label>[B欄位] B股市代號 (0為現金)：</label>
            <input type="text" name="ticker_B_in" value="0050" required>
        </div>
        <div class="form-group">
            <label>[C欄位] 回測起始日：</label>
            <input type="date" name="start_date" value="2021-01-01" required>
        </div>
        <div class="form-group">
            <label>[D欄位] 回測結束日：</label>
            <input type="date" name="end_date" value="2025-12-31" required>
        </div>

        <div class="section-title">初始資金配置</div>
        <div class="form-group">
            <label>[E欄位] 初始投入 A 資金 (萬元)：</label>
            <input type="number" name="init_A_wan" value="200" step="any" required>
        </div>
        <div class="form-group">
            <label>[F欄位] 初始投入 B 資金 (萬元)：</label>
            <input type="number" name="init_B_wan" value="200" step="any" required>
        </div>

        <div class="section-title">網格與動態鎖利參數</div>
        <div class="form-group">
            <label>[H欄位] 波段高點下跌買入距 (%)：</label>
            <input type="number" name="pct_H" value="7" step="any" required>
        </div>
        <div class="form-group">
            <label>[J欄位] 每次動用 B 資金比例 (%)：</label>
            <input type="number" name="pct_J" value="15" step="any" required>
        </div>
        <div class="form-group">
            <label>[K欄位] 波段低點反彈賣出距 (%)：</label>
            <input type="number" name="pct_K" value="15" step="any" required>
        </div>
        <div class="form-group">
            <label>[L欄位] A溢價動態鎖利門檻 (%)：</label>
            <input type="number" name="pct_L" value="20" step="any" required>
        </div>
        <div class="form-group">
            <label>[M欄位] 獲利轉出 B 股比例 (%)：</label>
            <input type="number" name="pct_M" value="50" step="any" required>
        </div>

        <button type="submit">🚀 開始執行策略回測 (新視窗開啟)</button>
        <div class="hint">※ 點擊後將彈出新網頁，本頁面可保留繼續修改不同數據進行比對</div>
    </form>
</div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/run', methods=['POST'])
def run_backtest_logic():
    global reports_storage
    try:
        # 接收網頁前端表單傳入的參數
        ticker_A_raw = request.form.get("ticker_A", "00631L").strip().upper()
        ticker_B_raw = request.form.get("ticker_B_in", "0050").strip().upper()
        start_date = request.form.get("start_date", "2021-01-01")
        end_date = request.form.get("end_date", "2025-12-31")
        
        init_A_wan = float(request.form.get("init_A_wan", 200))
        init_B_wan = float(request.form.get("init_B_wan", 200))
        
        pct_H = float(request.form.get("pct_H", 7)) / 100.0
        pct_J = float(request.form.get("pct_J", 15)) / 100.0
        pct_K = float(request.form.get("pct_K", 15)) / 100.0
        pct_L = float(request.form.get("pct_L", 20)) / 100.0
        pct_M = float(request.form.get("pct_M", 50)) / 100.0

        ticker_A = ticker_A_raw if ticker_A_raw.endswith(".TW") else ticker_A_raw + ".TW"
        if ticker_B_raw != "0" and not ticker_B_raw.endswith(".TW"):
            ticker_B_in = ticker_B_raw + ".TW"
        else:
            ticker_B_in = ticker_B_raw
            
        init_A = init_A_wan * 10000
        init_B = init_B_wan * 10000
        total_init_capital = init_A + init_B

        # 下載歷史數據 (考慮200MA往前多抓1年)
        start_dt_obj = datetime.strptime(start_date, "%Y-%m-%d")
        extended_start_date = (start_dt_obj - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
        
        data_A = yf.download(ticker_A, start=extended_start_date, end=end_date, progress=False)
        if ticker_B_in != "0":
            data_B = yf.download(ticker_B_in, start=extended_start_date, end=end_date, progress=False)
        else:
            data_B = pd.DataFrame()
            
        data_0050 = yf.download("0050.TW", start=extended_start_date, end=end_date, progress=False)
            
        if data_A.empty or data_0050.empty:
            return "<h2 style='color:#f1948a; text-align:center; padding-top:50px;'>❌ 錯誤：找不到歷史數據。請檢查標的代號或網路連線。</h2>"

        for d in [data_A, data_B, data_0050]:
            if not d.empty and isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.droplevel(1)

        data_0050['5MA'] = data_0050['Close'].rolling(window=5).mean()
        data_0050['200MA'] = data_0050['Close'].rolling(window=200).mean()

        df = pd.DataFrame(index=data_A.loc[start_date:end_date].index)
        df['A_Close'] = data_A.loc[start_date:end_date, 'Close']
        
        if ticker_B_in != "0" and not data_B.empty:
            df['B_Close'] = data_B.loc[start_date:end_date, 'Close']
        else:
            df['B_Close'] = 1.0
            
        df['0050_5MA'] = data_0050.loc[start_date:end_date, '5MA']
        df['0050_200MA'] = data_0050.loc[start_date:end_date, '200MA']
        df = df.dropna()

        if df.empty:
            return "<h2 style='color:#f1948a; text-align:center; padding-top:50px;'>❌ 錯誤：經MA計算過濾後無可用數據，請嘗試將回測起始日前移。</h2>"

        # 初始化變數
        p_A_init = float(df['A_Close'].iloc[0])
        p_B_init = float(df['B_Close'].iloc[0])
        
        shares_A = float(init_A / p_A_init)
        shares_B = float(init_B / p_B_init) if ticker_B_in != "0" else float(init_B)
        adjusted_base_A = float(init_A)
        peak_A = float(p_A_init)
        trough_A = float(p_A_init)
        j_stack = []   
        
        # 策略 3 變數
        strat3_cash = 0.0
        strat3_shares_A = float(total_init_capital / p_A_init)
        strat3_shares_B = 0.0
        strat3_hold_position = "A"
        below_count = 0
        above_count = 0
        
        history_total = []
        history_bh = []  
        history_strat3 = [] 
        history_dates = []
        
        df['Year'] = df.index.year
        yearly_reports = {}
        
        # 細分 B轉A（加碼）與 A轉B（獲利還原）的年度計數器
        yearly_b_to_a_counts = {yr: 0 for yr in df['Year'].unique()}
        yearly_a_to_b_counts = {yr: 0 for yr in df['Year'].unique()}
        yearly_strat3_trades = {yr: 0 for yr in df['Year'].unique()}

        total_days = len(df)
        
        # 時間序列模擬
        for idx, (date, row) in enumerate(df.iterrows()):
            price_A = float(row['A_Close'])
            price_B = float(row['B_Close'])
            ma5 = float(row['0050_5MA'])
            ma200 = float(row['0050_200MA'])
            year = int(row['Year'])
            
            # ✨【移植：回測精良版最高低點邏輯校正】
            if len(j_stack) == 0:
                if price_A > peak_A: peak_A = price_A
            else:
                if price_A < trough_A: trough_A = price_A
                
            current_val_B = float(shares_B * price_B) if ticker_B_in != "0" else float(shares_B)
            drop_trigger = float(peak_A * (1.0 - (len(j_stack) + 1) * pct_H))
            
            # 下跌 H% 觸發加碼 (B 資金轉換成 A 股)
            if price_A <= drop_trigger and len(j_stack) < 10 and current_val_B > 0:
                allocated_cash = float(current_val_B * pct_J)
                if allocated_cash > current_val_B or (10 - len(j_stack) == 1): allocated_cash = current_val_B 
                bought_shares_A = float(allocated_cash / price_A)
                shares_A += bought_shares_A
                if ticker_B_in != "0": shares_B -= float(allocated_cash / price_B)
                else: shares_B -= allocated_cash
                j_stack.append({"shares": bought_shares_A, "cash_val": allocated_cash})
                trough_A = price_A 
                
                # 紀錄 B 轉 A 次數
                yearly_b_to_a_counts[year] += 1
                
            # 反彈 K% 觸發獲利調節 (A 股回填恢復 B 資金)
            elif len(j_stack) > 0:
                rose_trigger = float(trough_A * (1.0 + pct_K))
                if price_A >= rose_trigger:
                    last_j = j_stack.pop()
                    sell_shares_A = float(last_j["shares"])
                    if sell_shares_A > shares_A: sell_shares_A = shares_A
                    return_cash = float(sell_shares_A * price_A)
                    shares_A -= sell_shares_A
                    if ticker_B_in != "0": shares_B += float(return_cash / price_B)
                    else: shares_B += return_cash
                    if len(j_stack) == 0: peak_A = price_A 
                    else: trough_A = price_A
                    
                    # 紀錄 A 轉 B 次數
                    yearly_a_to_b_counts[year] += 1

            # 動態鎖利機制
            current_val_A = float(shares_A * price_A)
            if current_val_A >= adjusted_base_A * (1.0 + pct_L):
                profit_A = current_val_A - adjusted_base_A
                transfer_cash = float(profit_A * pct_M)
                if transfer_cash > current_val_A: transfer_cash = current_val_A
                shares_to_sell_A = float(transfer_cash / price_A)
                shares_A -= shares_to_sell_A
                if ticker_B_in != "0": shares_B += float(transfer_cash / price_B)
                else: shares_B += transfer_cash
                adjusted_base_A = adjusted_base_A + transfer_cash
                j_stack = []
                peak_A = price_A
                trough_A = price_A
                current_val_A = float(shares_A * price_A)

            current_val_B = float(shares_B * price_B) if ticker_B_in != "0" else float(shares_B)
            day_total = current_val_A + current_val_B

            # 策略 3 邏輯
            if ma5 < ma200:
                below_count += 1
                above_count = 0
            elif ma5 > ma200:
                above_count += 1
                below_count = 0
            else:
                below_count = 0
                above_count = 0

            if below_count > 7 and strat3_hold_position == "A":
                cash_from_A = strat3_shares_A * price_A
                strat3_shares_A = 0.0
                if ticker_B_in != "0": strat3_shares_B = cash_from_A / price_B
                else: strat3_cash = cash_from_A
                strat3_hold_position = "B"
                yearly_strat3_trades[year] += 1
            elif above_count > 7 and strat3_hold_position == "B":
                cash_from_B = (strat3_shares_B * price_B) if ticker_B_in != "0" else strat3_cash
                strat3_shares_B = 0.0; strat3_cash = 0.0
                strat3_shares_A = cash_from_B / price_A
                strat3_hold_position = "A"
                yearly_strat3_trades[year] += 1

            if strat3_hold_position == "A":
                day_total_strat3 = strat3_shares_A * price_A
            else:
                day_total_strat3 = (strat3_shares_B * price_B) if ticker_B_in != "0" else strat3_cash

            history_total.append(day_total)
            history_strat3.append(day_total_strat3)
            history_dates.append(date.strftime('%Y-%m-%d'))
            bh_val = float((total_init_capital / p_A_init) * price_A)
            history_bh.append(bh_val)
            
            is_last_day_of_data = (idx == total_days - 1)
            is_end_of_year = False
            if is_last_day_of_data: is_end_of_year = True
            else:
                try:
                    if df['Year'].iloc[idx + 1] != year: is_end_of_year = True
                except IndexError: is_end_of_year = True
                    
            if is_end_of_year:
                yearly_reports[year] = {
                    "A_val": current_val_A, "B_val": current_val_B,
                    "Total_val": day_total, "BH_val": bh_val, "Strat3_val": day_total_strat3
                }

        # 計算指標
        final_total = history_total[-1]
        total_return_pct = ((final_total - total_init_capital) / total_init_capital) * 100
        bh_final_val = history_bh[-1]
        bh_return_pct = ((bh_final_val - total_init_capital) / total_init_capital) * 100
        final_strat3_val = history_strat3[-1]
        strat3_return_pct = ((final_strat3_val - total_init_capital) / total_init_capital) * 100

        # 生成 HTML 表格
        table_rows_html = ""
        ticker_A_show = ticker_A_raw.replace(".TW", "")
        ticker_B_show = "現金" if ticker_B_raw == "0" else ticker_B_raw.replace(".TW", "")

        for yr, status in sorted(yearly_reports.items()):
            diff_val = status['Total_val'] - status['BH_val']
            diff_style = "color:#2ecc71; font-weight:bold;" if diff_val >= 0 else "color:#f1948a; font-weight:bold;"
            diff_sign = "+" if diff_val >= 0 else ""
            strategy_cum_return = ((status['Total_val'] - total_init_capital) / total_init_capital) * 100
            bh_cum_return = ((status['BH_val'] - total_init_capital) / total_init_capital) * 100
            strat3_cum_return = ((status['Strat3_val'] - total_init_capital) / total_init_capital) * 100
            
            b_to_a_num = yearly_b_to_a_counts.get(yr, 0)
            a_to_b_num = yearly_a_to_b_counts.get(yr, 0)
            
            # ✨【優化：結合紅綠燈徽章的精緻排版】
            table_rows_html += f"""
            <tr>
                <td><b>{yr} 年底</b></td>
                <td style="text-align: left; padding-left: 20px;">
                    <div class="trade-badge badge-down">🟢 B ➡️ A: {b_to_a_num} 次</div><br>
                    <div class="trade-badge badge-up">🔴 A ➡️ B: {a_to_b_num} 次</div>
                </td>
                <td>${status['A_val']:,.0f}</td><td>${status['B_val']:,.0f}</td>
                <td style="background-color: #384256;"><b>${status['Total_val']:,.0f}</b><br><span style="color:#5dade2; font-size:0.8rem; font-weight:bold;">({strategy_cum_return:+.2f}%)</span></td>
                <td style="background-color: #423d33;"><b>${status['Strat3_val']:,.0f}</b><br><span style="color:#f1c40f; font-size:0.8rem; font-weight:bold;">({strat3_cum_return:+.2f}%)</span><br><span style="font-size:0.75rem; color:#cbd5e1;">({yearly_strat3_trades.get(yr, 0)}次周轉)</span></td>
                <td style="background-color: #443437;"><b>${status['BH_val']:,.0f}</b><br><span style="color:#f1948a; font-size:0.8rem; font-weight:bold;">({bh_cum_return:+.2f}%)</span></td>
                <td style="{diff_style}">{diff_sign}${diff_val:,.0f}</td>
            </tr>
            """

        # 組裝網頁 HTML 報告
        report_html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <title>策略回測報告 - {ticker_A_raw} vs {ticker_B_raw}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: 'Microsoft JhengHei', sans-serif; background-color: #2b323f; margin: 0; padding: 20px; color: #e9ecef; }}
        .container {{ max-width: 1250px; margin: 0 auto; background: #353d4e; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.2); border: 1px solid #414b5f; }}
        h1 {{ text-align: center; color: #5dade2; margin-bottom: 25px; }}
        .grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 30px; }}
        .card {{ background: #2d3545; padding: 12px; border-radius: 8px; border: 1px solid #414b5f; text-align: center; }}
        .card h3 {{ margin: 0 0 5px 0; font-size: 0.85rem; color: #cbd5e1; }}
        .card p {{ margin: 0; font-size: 1.2rem; font-weight: bold; color: #fff; }}
        .highlight {{ color: #5dade2 !important; }}
        .highlight-orange {{ color: #f1c40f !important; }}
        .highlight-red {{ color: #f1948a !important; }}
        .chart-box {{ position: relative; height: 450px; margin-bottom: 40px; background: #2d3545; padding: 15px; border-radius: 8px; border: 1px solid #414b5f; }}
        h2 {{ border-left: 5px solid #5dade2; padding-left: 10px; margin-top: 30px; color: #85c1e9; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; margin-bottom: 30px; font-size: 0.95rem; color: #e9ecef; }}
        th, td {{ padding: 12px; border: 1px solid #414b5f; text-align: left; vertical-align: middle; }}
        th {{ background-color: #2d3545; color: #cbd5e1; }}
        .table-yearly th {{ background-color: #3e485c; color: #85c1e9; text-align: center; }}
        .table-yearly td {{ text-align: center; }}
        .params-snapshot {{ background-color: #2d3545; border: 1px dashed #5dade2; border-radius: 8px; padding: 15px; margin-bottom: 25px; font-size: 0.9rem; }}
        .params-snapshot span {{ display: inline-block; margin-right: 20px; margin-bottom: 5px; color: #cbd5e1; }}
        .params-snapshot strong {{ color: #fff; }}
        
        /* 燈號徽章樣式優化 */
        .trade-badge {{
            display: inline-block;
            white-space: nowrap;
            padding: 4px 12px;
            border-radius: 15px;
            font-size: 0.82rem;
            font-weight: bold;
            margin: 3px 0;
            width: 125px;
            text-align: left;
        }}
        .badge-down {{ background-color: #2c3e35; color: #2ecc71; border: 1px solid #27ae60; }}
        .badge-up {{ background-color: #443437; color: #f1948a; border: 1px solid #c0392b; }}
    </style>
</head>
<body>
<div class="container">
    <h1>📊 策略金字塔加碼、動態鎖利與5MA/200MA策略回測報告</h1>
    
    <div class="params-snapshot">
        <h3 style="margin: 0 0 10px 0; color: #5dade2; font-size: 0.95rem;">📌 本頁回測參數初始設定快照</h3>
        <span>標的A股: <strong>{ticker_A_show}</strong></span>
        <span>標的B股: <strong>{ticker_B_show}</strong></span>
        <span>回測區間: <strong>{start_date} ~ {end_date}</strong></span><br>
        <span>初始A資金: <strong>{init_A_wan} 萬元</strong></span>
        <span>初始B資金: <strong>{init_B_wan} 萬元</strong></span>
        <span>下跌買入距 [H]: <strong>{pct_H*100:.1f}%</strong></span>
        <span>每次動用B比 [J]: <strong>{pct_J*100:.1f}%</strong></span>
        <span>反彈賣出距 [K]: <strong>{pct_K*100:.1f}%</strong></span>
        <span>鎖利門檻 [L]: <strong>{pct_L*100:.1f}%</strong></span>
        <span>獲利轉出B比 [M]: <strong>{pct_M*100:.1f}%</strong></span>
    </div>

    <div class="grid">
        <div class="card"><h3>初始投入總資金</h3><p>${total_init_capital:,.2f}</p></div>
        <div class="card"><h3>原策略最終總資產</h3><p class="highlight">${final_total:,.2f}</p></div>
        <div class="card"><h3>原策略總報酬率</h3><p class="highlight">{total_return_pct:.2f}%</p></div>
        <div class="card"><h3>策略3(5MA/200MA)報酬</h3><p class="highlight-orange">{strat3_return_pct:.2f}%</p></div>
        <div class="card"><h3>純A股買入持有報酬</h3><p class="highlight-red">{bh_return_pct:.2f}%</p></div>
    </div>
    
    <div class="chart-box"><canvas id="resultChart"></canvas></div>
    
    <h2>📅 歷年年底資產精細複盤</h2>
    <table class="table-yearly">
        <thead>
            <tr>
                <th>時間節點</th>
                <th style="width: 180px;">原策略資金轉換明細<br><span style="font-size:0.75rem; color:#cbd5e1; font-weight:normal;">(買入加碼 / 獲利還原)</span></th>
                <th>原策略A：{ticker_A_show} 市值</th>
                <th>原策略B：{ticker_B_show} 市值</th>
                <th style="color: #5dade2;">原策略：資產總淨值</th>
                <th style="color: #f1c40f;">策略3：0050均線交叉總值</th>
                <th style="color: #f1948a;">對照組：純持有 A股:{ticker_A_show}</th>
                <th>原策略與對照組差距</th>
            </tr>
        </thead>
        <tbody>{table_rows_html}</tbody>
    </table>
</div>
<script>
    const ctx = document.getElementById('resultChart').getContext('2d');
    new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: {str(history_dates)},
            datasets: [
                {{ label: '本動態鎖利加碼策略曲線', data: {str([round(x, 2) for x in history_total])}, borderColor: '#5dade2', borderWidth: 2.5, pointRadius: 0, fill: false }},
                {{ label: '策略 3 (0050均線訊號) 曲線', data: {str([round(x, 2) for x in history_strat3])}, borderColor: '#f1c40f', borderWidth: 2.5, pointRadius: 0, fill: false }},
                {{ label: '純持有 A 股對照組曲線', data: {str([round(x, 2) for x in history_bh])}, borderColor: '#f1948a', borderWidth: 1.5, borderDash: [4, 4], pointRadius: 0, fill: false }}
            ]
        }},
        options: {{ 
            responsive: true, 
            maintainAspectRatio: false, 
            interaction: {{ mode: 'index', intersect: false }}, 
            scales: {{ 
                x: {{ grid: {{ color: '#414b5f' }}, ticks: {{ color: '#cbd5e1' }} }},
                y: {{ grid: {{ color: '#414b5f' }}, ticks: {{ color: '#cbd5e1', callback: function(val) {{ return '$' + val.toLocaleString(); }} }} }} 
            }},
            plugins: {{ legend: {{ labels: {{ color: '#e9ecef' }} }} }}
        }}
    }});
</script>
</body>
</html>
"""
        report_id = str(uuid.uuid4())
        reports_storage[report_id] = report_html
        return redirect(url_for('view_report', report_id=report_id))
    except Exception as e:
        return f"<pre style='color:#fff;'>{traceback.format_exc()}</pre>"

@app.route('/report/<report_id>')
def view_report(report_id):
    global reports_storage
    html_content = reports_storage.get(report_id)
    if not html_content:
        return "<h2 style='color:#fff; text-align:center;'>報告已過期或不存在，請重新執行回測。</h2>"
    return render_template_string(html_content)

if __name__ == "__main__":
    print("🚀 正在啟動紅綠燈極致排版版回測系統...")
    webbrowser.open("http://127.0.0.1:5000")
    app.run(port=5000, debug=False)