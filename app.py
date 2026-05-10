import streamlit as st

# 設定頁面配置
st.set_page_config(page_title="耀迅國際 客戶排程系統", layout="wide")

# 初始化全域 Session State
if 'client_data' not in st.session_state:
    st.session_state['client_data'] = None
if 'selected_clients' not in st.session_state:
    st.session_state['selected_clients'] = []

# 定義頁面
# 我們先定義頁面，這樣在 show_home 裡面才能引用 client_map
client_map = st.Page("pages/1_Client_Map.py", title="客戶地圖", icon="🗺️")
schedule_planning = st.Page("pages/2_Schedule_Planning.py", title="行程排程", icon="⏱️")
data_settings = st.Page("pages/3_Data_Settings.py", title="資料設定", icon="⚙️")

# 定義首頁內容函數
def show_home():
    st.title("耀迅國際 客戶排程系統")
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button('進入客戶地圖', type='primary', use_container_width=True):
            st.switch_page(client_map)

home_page = st.Page(show_home, title="首頁", icon="🏠")

# 建立導覽
pg = st.navigation([home_page, client_map, schedule_planning, data_settings])

# 執行導覽
pg.run()
