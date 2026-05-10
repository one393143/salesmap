import streamlit as st

# 設定頁面配置
st.set_page_config(page_title="耀迅國際 客戶排程系統", layout="wide")

# 初始化全域 Session State
if 'client_data' not in st.session_state:
    st.session_state['client_data'] = None
if 'selected_clients' not in st.session_state:
    st.session_state['selected_clients'] = []

# 頁面標題 (純文字)
st.title("耀迅國際 客戶排程系統")

# 畫面置中只保留一個主要按鈕
st.markdown("<br><br>", unsafe_allow_html=True) # 加上一點垂直間距
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if st.button('進入客戶地圖', type='primary', use_container_width=True):
        st.switch_page("pages/1_Client_Map.py")
