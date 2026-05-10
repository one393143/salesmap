import streamlit as st
import pandas as pd
from utils import clean_taiwan_address, batch_geocode, MAPBOX_TOKEN


st.title("📁 資料管理")
st.markdown("載入客戶資料、自動清洗地址與座標轉換。")

if not MAPBOX_TOKEN:
    st.error("⚠️ 未設定 MAPBOX_API_KEY！")

data_source = st.radio("選擇資料來源", ["預設專案資料 (GitHub)", "上傳自訂資料 (CSV)"])

df = None
if data_source == "預設專案資料 (GitHub)":
    file_options = {
        "原始客戶資料": "https://raw.githubusercontent.com/one393143/salesmap/main/%E5%AE%A2%E6%88%B6_%E4%BE%9B%E6%87%89%E5%95%86%E5%9F%BA%E6%9C%AC%E8%B3%87%E6%96%99%20Customer%20_%20Supplier%20Master%20Data_20260510T160059%2B0800.csv",
        "已編碼歷史紀錄 (geocoded)": "https://raw.githubusercontent.com/one393143/salesmap/main/geocoded_customers.csv"
    }
    selected_file = st.selectbox("選擇專案檔案", list(file_options.keys()))
    url = file_options[selected_file]
    try:
        df = pd.read_csv(url)
    except Exception as e:
        st.error(f"載入失敗: {e}")
else:
    uploaded_file = st.file_uploader("📤 上傳客戶資料 (CSV)", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)

if df is not None:
    # 尋找地址欄位
    address_cols = [col for col in df.columns if any(k in str(col).lower() for k in ['地址', 'address', 'addr'])]
    target_col = st.selectbox(
        "📍 確認地址欄位", 
        df.columns, 
        index=df.columns.get_loc(address_cols[0]) if address_cols else 0
    )
    
    # 自動流水線
    with st.spinner('雲端座標解析中...'):
        # 1. 清洗地址
        if '清洗後地址' not in df.columns:
            df['清洗後地址'] = df[target_col].apply(clean_taiwan_address)
            
        # 2. 地理編碼 (batch_geocode 會自動略過已有座標的行)
        geocoded_df = batch_geocode(df, '清洗後地址', use_api=True)
        
        # 存入 session_state
        st.session_state['client_data'] = geocoded_df
        
    st.success("🎉 資料處理完成！")
    
    # 顯示成功與失敗清單
    failed_df = geocoded_df[geocoded_df['Latitude'].isna()]
    
    if not failed_df.empty:
        st.warning(f"⚠️ 發現 {len(failed_df)} 筆無法解析的地址：")
        st.dataframe(failed_df[[target_col, '清洗後地址', 'Latitude', 'Longitude']])
    
    st.write("### 🌍 座標轉換結果 (預覽)")
    st.dataframe(geocoded_df[[target_col, '清洗後地址', 'Latitude', 'Longitude']], use_container_width=True)
    
    csv_data = geocoded_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下載完整資料 (CSV)", data=csv_data, file_name='geocoded_customers.csv', mime='text/csv')
