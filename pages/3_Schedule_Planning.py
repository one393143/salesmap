import streamlit as st
import pandas as pd
from datetime import time

st.title("⏱️ 行程排程")
st.markdown("設定出發時間、停留時間與預約時段。")

# 防呆提醒
if 'client_data' not in st.session_state:
    st.warning("⚠️ 尚未載入客戶資料！請先至「📁 資料管理」頁面載入或上傳資料。")
elif 'selected_candidates' not in st.session_state or not st.session_state['selected_candidates']:
    st.info("💡 請先至「🗺️ 空間探索」頁面篩選並選擇您預計拜訪的客戶。")
else:
    df_all = st.session_state['client_data']
    selected_ids = st.session_state['selected_candidates']
    
    # 取得選中的客戶資料
    df_selected = df_all.loc[selected_ids].copy()
    
    name_cols = [col for col in df_selected.columns if '名稱' in col or 'name' in col.lower()]
    name_col = name_cols[0] if name_cols else df_selected.columns[0]
    
    st.markdown("### 1. 設定出發情境")
    col1, col2, col3 = st.columns(3)
    with col1:
        start_addr = st.text_input("🏢 出發與結束地址", value="台北市松山區南京東路五段202號")
    with col2:
        start_time = st.time_input("⏰ 今日出發時間", value=time(9, 0))
    with col3:
        default_stay = st.number_input("⏳ 預設每站停留 (分鐘)", min_value=10, max_value=120, value=40, step=5)
        
    st.markdown("---")
    st.markdown("### 2. 客製化客戶拜訪設定")
    st.markdown("您可以在下方表格中，為特定客戶設定「客製停留時間」或「預約抵達時間」。")
    
    # 準備 data_editor 的資料
    # 我們需要顯示名稱、地址，並提供可編輯的欄位
    display_df = pd.DataFrame({
        '客戶名稱': df_selected[name_col].values,
        '地址': df_selected['清洗後地址'].values if '清洗後地址' in df_selected.columns else df_selected.get('地址', df_selected.columns[0]).values,
        '客製停留時間(分鐘)': [default_stay] * len(df_selected),
        '強制抵達時間(可留白)': [''] * len(df_selected)
    }, index=df_selected.index)
    
    edited_df = st.data_editor(
        display_df,
        column_config={
            "客製停留時間(分鐘)": st.column_config.NumberColumn(
                min_value=10,
                max_value=120,
                step=5,
                format="%d"
            ),
            "強制抵達時間(可留白)": st.column_config.TextColumn(
                help="格式例如: 14:00"
            )
        },
        use_container_width=True
    )
    
    st.markdown("---")
    st.markdown("### 3. 計算最佳時間鏈")
    if st.button("🚀 產生最佳時間排程", use_container_width=True, type="primary"):
        st.info("此功能為階段三/四核心，目前僅完成 UI 介面，運算邏輯開發中！")
        
        # 這裡可以先把資料存起來，供未來使用
        st.session_state['schedule_settings'] = {
            'start_addr': start_addr,
            'start_time': start_time,
            'default_stay': default_stay,
            'edited_df': edited_df
        }
        
        st.success("已成功記錄設定！")
        st.dataframe(edited_df)
