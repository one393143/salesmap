import streamlit as st

# 首頁內容函數
def show_home():
    st.title("🗺️ 企業客戶分佈地圖與路線系統")
    st.markdown("""
    ### 歡迎使用企業客戶分佈地圖與路線系統！

    這是一個專為外勤業務人員設計的專業路徑規劃與客戶管理系統。請使用左側導覽列切換至不同功能模組：

    1. **📁 資料管理**：
       - 支援從 GitHub 載入預設資料或上傳您自己的 CSV 檔案。
       - 自動清洗台灣複雜地址，去除樓層等雜訊。
       - 整合 Mapbox API 進行高精度地理編碼（經緯度轉換），並具備本地快取機制。

    2. **🗺️ 空間探索**：
       - 互動式地圖視覺化，支援 MarkerCluster 叢集顯示。
       - 設定「錨點客戶」與「搜尋半徑」，瞬間篩選出附近的潛在拜訪點。
       - **智慧路線推薦**：選擇目標客戶，系統將自動計算最佳 TSP 拜訪路徑。
       - **一鍵導航**：產生 Google Maps 多站點導航連結，無縫接軌手機導航。

    3. **⏱️ 行程排程**：
       - 未來擴充功能（如時間窗邏輯等）。

    ---
    👈 **請從左側側邊欄選擇功能頁面開始使用。**
    """)
    
    st.markdown("---")
    st.markdown("### 🚀 快速開始")
    if st.button("📥 一鍵匯入預設已編碼資料", use_container_width=True, type="primary"):
        import pandas as pd
        from utils import clean_taiwan_address
        
        url = "https://raw.githubusercontent.com/one393143/salesmap/main/geocoded_customers.csv"
        try:
            with st.spinner("正在從 GitHub 載入資料..."):
                df = pd.read_csv(url)
                
                target_col = '地址'
                if target_col not in df.columns:
                    addr_cols = [col for col in df.columns if '地址' in col]
                    if addr_cols:
                        target_col = addr_cols[0]
                        
                if '清洗後地址' not in df.columns and target_col in df.columns:
                    df['清洗後地址'] = df[target_col].apply(clean_taiwan_address)
                    
                st.session_state['client_data'] = df
                st.session_state['cleaned_df'] = df
                st.session_state['target_col'] = target_col
                
                st.success("🎉 一鍵匯入完成！資料已載入，請直接前往「🗺️ 空間探索」或「⏱️ 行程排程」頁面。")
        except Exception as e:
            st.error(f"載入失敗: {e}")

# 定義頁面
home_page = st.Page(show_home, title="首頁", icon="🏠")
data_page = st.Page("pages/1_Data_Management.py", title="資料管理", icon="📁")
spatial_page = st.Page("pages/2_Spatial_Exploration.py", title="空間探索", icon="🗺️")
schedule_page = st.Page("pages/3_Schedule_Planning.py", title="行程排程", icon="⏱️")

# 建立導覽
pg = st.navigation([home_page, data_page, spatial_page, schedule_page])

# 設定頁面配置 (必須在 pg.run() 之前或 entrypoint 中設定)
st.set_page_config(page_title="企業客戶分佈地圖", layout="wide")

# 執行導覽
pg.run()
