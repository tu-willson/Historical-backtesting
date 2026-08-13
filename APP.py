from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

# 頁面基本設定
st.set_page_config(
    page_title="策略回測系統",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 策略金字塔加碼、動態鎖利與 5MA/200MA 策略回測系統")

# ==================== 側邊欄：參數輸入 ====================
st.sidebar.header("⚙️ 策略參數設定")

st.sidebar.subheader("基本標的與時間")
ticker_A_raw = st.sidebar.text_input(
    "[A欄位] A股市代號", value="00631L"
).strip().upper()
ticker_B_raw = (
    st.sidebar.text_input("[B欄位] B股市代號 (輸入 0 代表現金)", value="0050")
    .strip()
    .upper()
)
start_date = st.sidebar.date_input("[C欄位] 回測起始日", datetime(2021, 1, 1))
end_date = st.sidebar.date_input("[D欄位] 回測結束日", datetime(2025, 12, 31))

st.sidebar.subheader("初始資金配置 (萬元)")
init_A_wan = st.sidebar.number_input(
    "[E欄位] 初始投入 A 資金 (萬元)", value=200.0, step=10.0
)
init_B_wan = st.sidebar.number_input(
    "[F欄位] 初始投入 B 資金 (萬元)", value=200.0, step=10.0
)

st.sidebar.subheader("網格與動態鎖利參數 (%)")
pct_H = (
    st.sidebar.number_input(
        "[H欄位] 波段高點下跌買入距 (%)", value=7.0, step=0.5
    )
    / 100.0
)
pct_J = (
    st.sidebar.number_input(
        "[J欄位] 每次動用 B 資金比例 (%)", value=15.0, step=1.0
    )
    / 100.0
)
pct_K = (
    st.sidebar.number_input(
        "[K欄位] 波段低點反彈賣出距 (%)", value=15.0, step=0.5
    )
    / 100.0
)
pct_L = (
    st.sidebar.number_input(
        "[L欄位] A溢價動態鎖利門檻 (%)", value=20.0, step=1.0
    )
    / 100.0
)
pct_M = (
    st.sidebar.number_input(
        "[M欄位] 獲利轉出 B 股比例 (%)", value=50.0, step=5.0
    )
    / 100.0
)

run_button = st.sidebar.button("🚀 開始執行策略回測", type="primary", use_container_width=True)

# ==================== 回測主程式 ====================
if run_button:
  with st.spinner("正在下載股票歷史數據並進行回測運算中..."):
    try:
      # 代號處理 (.TW 補全)
      ticker_A = (
          ticker_A_raw if ticker_A_raw.endswith(".TW") else ticker_A_raw + ".TW"
      )
      if ticker_B_raw != "0" and not ticker_B_raw.endswith(".TW"):
        ticker_B_in = ticker_B_raw + ".TW"
      else:
        ticker_B_in = ticker_B_raw

      init_A = init_A_wan * 10000
      init_B = init_B_wan * 10000
      total_init_capital = init_A + init_B

      # 擴充抓取歷史數據（往前多抓 1 年計算 200MA）
      start_date_str = start_date.strftime("%Y-%m-%d")
      end_date_str = end_date.strftime("%Y-%m-%d")
      extended_start_date = (
          start_date - pd.Timedelta(days=365)
      ).strftime("%Y-%m-%d")

      data_A = yf.download(
          ticker_A,
          start=extended_start_date,
          end=end_date_str,
          progress=False,
      )
      if ticker_B_in != "0":
        data_B = yf.download(
            ticker_B_in,
            start=extended_start_date,
            end=end_date_str,
            progress=False,
        )
      else:
        data_B = pd.DataFrame()

      data_0050 = yf.download(
          "0050.TW",
          start=extended_start_date,
          end=end_date_str,
          progress=False,
      )

      if data_A.empty or data_0050.empty:
        st.error("❌ 錯誤：找不到歷史數據。請檢查標的代號或網路連線。")
        st.stop()

      # 清理 MultiIndex
      for d in [data_A, data_B, data_0050]:
        if not d.empty and isinstance(d.columns, pd.MultiIndex):
          d.columns = d.columns.droplevel(1)

      # 移動平均線計算
      data_0050["5MA"] = data_0050["Close"].rolling(window=5).mean()
      data_0050["200MA"] = data_0050["Close"].rolling(window=200).mean()

      # 對齊回測區間
      df = pd.DataFrame(index=data_A.loc[start_date_str:end_date_str].index)
      df["A_Close"] = data_A.loc[start_date_str:end_date_str, "Close"]

      if ticker_B_in != "0" and not data_B.empty:
        df["B_Close"] = data_B.loc[start_date_str:end_date_str, "Close"]
      else:
        df["B_Close"] = 1.0

      df["0050_5MA"] = data_0050.loc[start_date_str:end_date_str, "5MA"]
      df["0050_200MA"] = data_0050.loc[start_date_str:end_date_str, "200MA"]
      df = df.dropna()

      if df.empty:
        st.error("❌ 錯誤：經 MA 計算過濾後無可用數據，請嘗試將回測起始日前移。")
        st.stop()

      # 初始化變數
      p_A_init = float(df["A_Close"].iloc[0])
      p_B_init = float(df["B_Close"].iloc[0])

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

      df["Year"] = df.index.year
      yearly_reports = {}

      yearly_b_to_a_counts = {yr: 0 for yr in df["Year"].unique()}
      yearly_a_to_b_counts = {yr: 0 for yr in df["Year"].unique()}
      yearly_strat3_trades = {yr: 0 for yr in df["Year"].unique()}

      total_days = len(df)

      # 模擬交易過程
      for idx, (date, row) in enumerate(df.iterrows()):
        price_A = float(row["A_Close"])
        price_B = float(row["B_Close"])
        ma5 = float(row["0050_5MA"])
        ma200 = float(row["0050_200MA"])
        year = int(row["Year"])

        # 波段高低點校正
        if len(j_stack) == 0:
          if price_A > peak_A:
            peak_A = price_A
        else:
          if price_A < trough_A:
            trough_A = price_A

        current_val_B = (
            float(shares_B * price_B) if ticker_B_in != "0" else float(shares_B)
        )
        drop_trigger = float(peak_A * (1.0 - (len(j_stack) + 1) * pct_H))

        # 下跌觸發加碼 (B 轉 A)
        if price_A <= drop_trigger and len(j_stack) < 10 and current_val_B > 0:
          allocated_cash = float(current_val_B * pct_J)
          if allocated_cash > current_val_B or (10 - len(j_stack) == 1):
            allocated_cash = current_val_B
          bought_shares_A = float(allocated_cash / price_A)
          shares_A += bought_shares_A
          if ticker_B_in != "0":
            shares_B -= float(allocated_cash / price_B)
          else:
            shares_B -= allocated_cash
          j_stack.append(
              {"shares": bought_shares_A, "cash_val": allocated_cash}
          )
          trough_A = price_A
          yearly_b_to_a_counts[year] += 1

        # 反彈觸發獲利調節 (A 轉 B)
        elif len(j_stack) > 0:
          rose_trigger = float(trough_A * (1.0 + pct_K))
          if price_A >= rose_trigger:
            last_j = j_stack.pop()
            sell_shares_A = float(last_j["shares"])
            if sell_shares_A > shares_A:
              sell_shares_A = shares_A
            return_cash = float(sell_shares_A * price_A)
            shares_A -= sell_shares_A
            if ticker_B_in != "0":
              shares_B += float(return_cash / price_B)
            else:
              shares_B += return_cash
            if len(j_stack) == 0:
              peak_A = price_A
            else:
              trough_A = price_A
            yearly_a_to_b_counts[year] += 1

        # 動態鎖利機制
        current_val_A = float(shares_A * price_A)
        if current_val_A >= adjusted_base_A * (1.0 + pct_L):
          profit_A = current_val_A - adjusted_base_A
          transfer_cash = float(profit_A * pct_M)
          if transfer_cash > current_val_A:
            transfer_cash = current_val_A
          shares_to_sell_A = float(transfer_cash / price_A)
          shares_A -= shares_to_sell_A
          if ticker_B_in != "0":
            shares_B += float(transfer_cash / price_B)
          else:
            shares_B += transfer_cash
          adjusted_base_A = adjusted_base_A + transfer_cash
          j_stack = []
          peak_A = price_A
          trough_A = price_A
          current_val_A = float(shares_A * price_A)

        current_val_B = (
            float(shares_B * price_B) if ticker_B_in != "0" else float(shares_B)
        )
        day_total = current_val_A + current_val_B

        # 策略 3 (0050 均線交叉) 邏輯
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
          if ticker_B_in != "0":
            strat3_shares_B = cash_from_A / price_B
          else:
            strat3_cash = cash_from_A
          strat3_hold_position = "B"
          yearly_strat3_trades[year] += 1
        elif above_count > 7 and strat3_hold_position == "B":
          cash_from_B = (
              (strat3_shares_B * price_B)
              if ticker_B_in != "0"
              else strat3_cash
          )
          strat3_shares_B = 0.0
          strat3_cash = 0.0
          strat3_shares_A = cash_from_B / price_A
          strat3_hold_position = "A"
          yearly_strat3_trades[year] += 1

        if strat3_hold_position == "A":
          day_total_strat3 = strat3_shares_A * price_A
        else:
          day_total_strat3 = (
              (strat3_shares_B * price_B)
              if ticker_B_in != "0"
              else strat3_cash
          )

        history_total.append(day_total)
        history_strat3.append(day_total_strat3)
        history_dates.append(date)
        bh_val = float((total_init_capital / p_A_init) * price_A)
        history_bh.append(bh_val)

        # 紀錄年底結算
        is_last_day_of_data = idx == total_days - 1
        is_end_of_year = False
        if is_last_day_of_data:
          is_end_of_year = True
        else:
          try:
            if df["Year"].iloc[idx + 1] != year:
              is_end_of_year = True
          except IndexError:
            is_end_of_year = True

        if is_end_of_year:
          yearly_reports[year] = {
              "A_val": current_val_A,
              "B_val": current_val_B,
              "Total_val": day_total,
              "BH_val": bh_val,
              "Strat3_val": day_total_strat3,
          }

      # 計算最終結果指標
      final_total = history_total[-1]
      total_return_pct = (
          (final_total - total_init_capital) / total_init_capital
      ) * 100
      bh_final_val = history_bh[-1]
      bh_return_pct = (
          (bh_final_val - total_init_capital) / total_init_capital
      ) * 100
      final_strat3_val = history_strat3[-1]
      strat3_return_pct = (
          (final_strat3_val - total_init_capital) / total_init_capital
      ) * 100

      # ==================== 畫面顯示：核心數據卡片 ====================
      col1, col2, col3, col4, col5 = st.columns(5)
      col1.metric("初始投入總資金", f"${total_init_capital:,.0f}")
      col2.metric(
          "原策略最終總資產",
          f"${final_total:,.0f}",
          f"{total_return_pct:+.2f}%",
      )
      col3.metric(
          "策略3 (5MA/200MA)",
          f"${final_strat3_val:,.0f}",
          f"{strat3_return_pct:+.2f}%",
      )
      col4.metric(
          "純 A 股買入持有",
          f"${bh_final_val:,.0f}",
          f"{bh_return_pct:+.2f}%",
      )
      diff_val = final_total - bh_final_val
      col5.metric(
          "原策略與對照組差距",
          f"${diff_val:,.0f}",
          f"{(diff_val / bh_final_val) * 100:+.2f}%",
      )

      # ==================== 畫面顯示：Plotly 互動圖表 ====================
      st.subheader("📈 策略資產曲線走勢對照圖")

      fig = go.Figure()
      fig.add_trace(
          go.Scatter(
              x=history_dates,
              y=history_total,
              mode="lines",
              name="本動態鎖利加碼策略",
              line=dict(color="#5DADE2", width=2.5),
          )
      )
      fig.add_trace(
          go.Scatter(
              x=history_dates,
              y=history_strat3,
              mode="lines",
              name="策略 3 (0050 均線訊號)",
              line=dict(color="#F1C40F", width=2.5),
          )
      )
      fig.add_trace(
          go.Scatter(
              x=history_dates,
              y=history_bh,
              mode="lines",
              name="純持有 A 股對照組",
              line=dict(color="#F1948A", width=1.5, dash="dash"),
          )
      )

      fig.update_layout(
          template="plotly_dark",
          height=500,
          margin=dict(l=20, r=20, t=30, b=20),
          hovermode="x unified",
          legend=dict(
              orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1
          ),
          yaxis=dict(tickformat="$,.0f"),
      )
      st.plotly_chart(fig, use_container_width=True)

      # ==================== 畫面顯示：歷年結算表格 ====================
      st.subheader("📅 歷年年底資產精細複盤")

      table_data = []
      ticker_A_show = ticker_A_raw.replace(".TW", "")
      ticker_B_show = (
          "現金" if ticker_B_raw == "0" else ticker_B_raw.replace(".TW", "")
      )

      for yr, status in sorted(yearly_reports.items()):
        diff = status["Total_val"] - status["BH_val"]
        strat_cum = (
            (status["Total_val"] - total_init_capital) / total_init_capital
        ) * 100
        bh_cum = (
            (status["BH_val"] - total_init_capital) / total_init_capital
        ) * 100
        strat3_cum = (
            (status["Strat3_val"] - total_init_capital) / total_init_capital
        ) * 100

        b_to_a = yearly_b_to_a_counts.get(yr, 0)
        a_to_b = yearly_a_to_b_counts.get(yr, 0)

        table_data.append({
            "時間節點": f"{yr} 年底",
            "B ➡️ A 加碼": f"{b_to_a} 次",
            "A ➡️ B 還原": f"{a_to_b} 次",
            f"原策略 A ({ticker_A_show})": f"${status['A_val']:,.0f}",
            f"原策略 B ({ticker_B_show})": f"${status['B_val']:,.0f}",
            "原策略資產總額": (
                f"${status['Total_val']:,.0f} ({strat_cum:+.2f}%)"
            ),
            "策略 3 總額": (
                f"${status['Strat3_val']:,.0f} ({strat3_cum:+.2f}%)"
            ),
            f"純持有 A 股 ({ticker_A_show})": (
                f"${status['BH_val']:,.0f} ({bh_cum:+.2f}%)"
            ),
            "原策略 vs 純持有 差額": f"${diff:,.0f}",
        })

      st.dataframe(pd.DataFrame(table_data), use_container_width=True)

    except Exception as e:
        st.error(f"執行過程中發生錯誤：{e}")
else:
  st.info("👈 請在左側調整回測參數後，點擊「開始執行策略回測」按鈕。")