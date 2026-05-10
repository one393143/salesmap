import streamlit as st
import pandas as pd
from utils import clean_taiwan_address, batch_geocode, MAPBOX_TOKEN


st.title("📁 資料管理")
st.markdown("上傳 CSV 資料、清洗地址與座標轉換。")

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
        st.success(f"已成功載入: {selected_file}")
    except Exception as e:
        st.error(f"載入失敗: {e}")
else:
    uploaded_file = st.file_uploader("📤 上傳客戶資料 (CSV)", type=["csv"])
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        st.success("已成功讀取上傳資料！")
        
if df is not None:
    address_cols = [col for col in df.columns if any(k in str(col).lower() for k in ['地址', 'address', 'addr'])]
    target_col = st.selectbox(
        "📍 選擇地址欄位", 
        df.columns, 
        index=df.columns.get_loc(address_cols[0]) if address_cols else 0
    )
    
    st.markdown("---")
    
    if st.button("🚀 1. 開始清洗資料", use_container_width=True):
        with st.spinner("資料清洗中..."):
            df['清洗後地址'] = df[target_col].apply(clean_taiwan_address)
            st.session_state['cleaned_df'] = df
            st.session_state['target_col'] = target_col
            st.session_state['show_map'] = False
        st.success("清洗完成！")

    if 'cleaned_df' in st.session_state:
        st.markdown("---")
        st.write("### 📍 2. 地理編碼")
        
        load_cache_btn = st.button("📥 載入本地快取 (不耗 API)", use_container_width=True)
        force_recalc_btn = st.button("🔄 API 轉換未解析地址", use_container_width=True)

        if load_cache_btn or force_recalc_btn:
            if force_recalc_btn and not MAPBOX_TOKEN:
                st.error("請先設定 API Key！")
            else:
                use_api = force_recalc_btn
                msg = "查詢經緯度中..." if use_api else "載入快取中..."
                
                with st.spinner(msg):
                    df_to_geocode = st.session_state['cleaned_df']
                    geocoded_df = batch_geocode(df_to_geocode, '清洗後地址', use_api=use_api)
                    st.session_state['geocoded_df'] = geocoded_df
                    st.session_state['show_map'] = False
                
                st.success("地理編碼完成！")

if 'geocoded_df' in st.session_state:
    geocoded_df = st.session_state['geocoded_df']
    saved_target_col = st.session_state.get('target_col', '地址')
    
    st.write("### 🌍 座標轉換結果")
    failed_df = geocoded_df[geocoded_df['Latitude'].isna()]
    if not failed_df.empty:
        st.warning(f"⚠️ 發現 {len(failed_df)} 筆無法解析的地址：")
        st.dataframe(failed_df[[saved_target_col, '清洗後地址', 'Latitude', 'Longitude']])
    else:
        st.success("🎉 所有地址皆具備經緯度！")
        
    st.dataframe(geocoded_df[[saved_target_col, '清洗後地址', 'Latitude', 'Longitude']], use_container_width=True)
    
    csv_data = geocoded_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下載完整資料 (CSV)", data=csv_data, file_name='geocoded_customers.csv', mime='text/csv')

elif 'cleaned_df' in st.session_state:
    cleaned_df = st.session_state['cleaned_df']
    saved_target_col = st.session_state.get('target_col', '地址')
    
    st.write("### ✨ 清洗前後對比 (預覽)")
    st.dataframe(cleaned_df[[saved_target_col, '清洗後地址']], use_container_width=True)
else:
    st.info("👈 請先選擇資料來源並進行「資料清洗」。")
