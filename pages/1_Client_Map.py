import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from haversine import haversine, Unit
import re
from utils import MAPBOX_TOKEN

st.title("🗺️ 客戶地圖與候補名單")

# 檢查資料是否載入
if 'client_data' not in st.session_state or st.session_state['client_data'] is None:
    st.warning("⚠️ 尚未載入客戶資料！請先至「資料設定」頁面載入資料。")
    st.stop()

df = st.session_state['client_data'].copy()

# 確保有經緯度資料
df_valid = df.dropna(subset=['Latitude', 'Longitude'])

if df_valid.empty:
    st.warning("⚠️ 沒有具備有效經緯度的客戶資料，請先至「資料設定」進行地理編碼。")
    st.stop()

# 初始化候補名單
if 'candidate_cart' not in st.session_state:
    st.session_state['candidate_cart'] = []

# ---------------------------------------------------------------------------
# 上半部：多維度篩選器
# ---------------------------------------------------------------------------
st.markdown("### 🔍 多維度篩選")

col1, col2, col3, col4 = st.columns([2, 1, 1.5, 1.5])

with col1:
    search_query = st.text_input("關鍵字搜尋 (統編/名稱)", placeholder="輸入統一編號或客戶名稱")

# 提取縣市函數
def extract_city(addr):
    if pd.isna(addr):
        return "未知"
    addr = str(addr).replace("台灣省", "")
    match = re.search(r'^(.{2,3}[市縣])', addr)
    if match:
        return match.group(1)
    return "其他"

# 新增縣市欄位
addr_col = '清洗後地址' if '清洗後地址' in df_valid.columns else ('地址' if '地址' in df_valid.columns else df_valid.columns[0])
df_valid['縣市'] = df_valid[addr_col].apply(extract_city)

cities = ["全部"] + sorted(list(df_valid['縣市'].unique()))

with col2:
    selected_city = st.selectbox("縣市選單", cities)

with col3:
    name_col = '客戶/供應商名稱' if '客戶/供應商名稱' in df_valid.columns else df_valid.columns[0]
    anchor_options = [f"{idx} - {row[name_col]}" for idx, row in df_valid.iterrows()]
    selected_anchor = st.selectbox("📍 選擇中心點 (半徑過濾)", ["無"] + anchor_options)

with col4:
    radius_km = st.slider("📏 搜尋半徑 (公里)", min_value=1, max_value=100, value=10, step=1)

# 套用篩選
filtered_df = df_valid.copy()

# 1. 關鍵字篩選
if search_query:
    name_condition = filtered_df[name_col].str.contains(search_query, case=False, na=False)
    tax_col = '統一編號' if '統一編號' in filtered_df.columns else None
    if tax_col:
        tax_condition = filtered_df[tax_col].astype(str).str.contains(search_query, case=False, na=False)
        filtered_df = filtered_df[name_condition | tax_condition]
    else:
        filtered_df = filtered_df[name_condition]

# 2. 縣市篩選
if selected_city != "全部":
    filtered_df = filtered_df[filtered_df['縣市'] == selected_city]

# 3. 半徑篩選
if selected_anchor != "無" and radius_km > 0:
    anchor_idx = int(selected_anchor.split(" - ")[0])
    anchor_row = df_valid.loc[anchor_idx]
    anchor_coords = (anchor_row['Latitude'], anchor_row['Longitude'])
    
    distances = []
    for idx, row in filtered_df.iterrows():
        coords = (row['Latitude'], row['Longitude'])
        dist = haversine(anchor_coords, coords, unit=Unit.KILOMETERS)
        distances.append(dist)
        
    filtered_df['Distance'] = distances
    filtered_df = filtered_df[filtered_df['Distance'] <= radius_km]

# ---------------------------------------------------------------------------
# 中間：地圖 (Folium)
# ---------------------------------------------------------------------------
st.markdown("### 🌍 全台客戶地圖")

# 建立地圖
m = folium.Map(location=[23.5, 121.0], zoom_start=7, tiles=None)
folium.TileLayer(
    tiles="https://api.mapbox.com/styles/v1/mapbox/light-v10/tiles/{z}/{x}/{y}?access_token=" + MAPBOX_TOKEN,
    attr="Mapbox",
    name="Mapbox Light"
).add_to(m)

# 使用 MarkerCluster，並設定 disableClusteringAtZoom=15
marker_cluster = MarkerCluster(
    maxClusterRadius=40, 
    disableClusteringAtZoom=15,
    spiderfyOnMaxZoom=False
).add_to(m)

# 如果有中心點，繪製半徑圓圈
if selected_anchor != "無" and radius_km > 0:
    anchor_idx = int(selected_anchor.split(" - ")[0])
    anchor_row = df_valid.loc[anchor_idx]
    folium.Circle(
        location=[anchor_row['Latitude'], anchor_row['Longitude']],
        radius=radius_km * 1000,
        color='gray',
        fill=True,
        fill_opacity=0.1,
        interactive=False
    ).add_to(m)
    
    # 標記中心點
    folium.Marker(
        location=[anchor_row['Latitude'], anchor_row['Longitude']],
        icon=folium.Icon(color='red', icon='info-sign'),
        tooltip=f"中心點: {anchor_row[name_col]}"
    ).add_to(m)

# 新增標記
for idx, row in filtered_df.iterrows():
    # 跳過中心點，避免重複標記
    if selected_anchor != "無" and idx == int(selected_anchor.split(" - ")[0]):
        continue
        
    lat, lon = row['Latitude'], row['Longitude']
    name = row[name_col]
    addr = row['清洗後地址'] if '清洗後地址' in row else ""
    
    popup_html = f"""
    <b>名稱:</b> {name}<br>
    <b>地址:</b> {addr}<br>
    <i>可在下方表格將此客戶加入候補</i>
    """
    
    folium.CircleMarker(
        location=[lat, lon],
        radius=6,
        color='#3186cc',
        fill=True,
        fill_color='#3186cc',
        tooltip=name,
        popup=folium.Popup(popup_html, max_width=350)
    ).add_to(marker_cluster)

# 渲染地圖
st_folium(m, use_container_width=True, height=400)

# ---------------------------------------------------------------------------
# 下半部：客戶資料表 (st.data_editor)
# ---------------------------------------------------------------------------
st.markdown("### 📊 客戶資料表")

display_df = filtered_df.reset_index()

# 標記是否已在候補名單中
display_df['加入候補'] = display_df['index'].apply(lambda x: x in st.session_state['candidate_cart'])

# 準備顯示的欄位
show_cols = ['index', name_col]
if '統一編號' in display_df.columns:
    show_cols.append('統一編號')
show_cols.extend(['清洗後地址', '加入候補'])
if 'Distance' in display_df.columns:
    show_cols.append('Distance')

# 使用 st.data_editor 讓使用者可以勾選
edited_df = st.data_editor(
    display_df[show_cols],
    use_container_width=True,
    disabled=['index', name_col, '統一編號', '清洗後地址', 'Distance'],
    hide_index=True,
    key="cart_editor"
)

# 處理勾選結果，更新 Session State
for i, row in edited_df.iterrows():
    orig_idx = row['index']
    is_checked = row['加入候補']
    
    if is_checked and orig_idx not in st.session_state['candidate_cart']:
        st.session_state['candidate_cart'].append(orig_idx)
    elif not is_checked and orig_idx in st.session_state['candidate_cart']:
        st.session_state['candidate_cart'].remove(orig_idx)

# ---------------------------------------------------------------------------
# 側邊欄：候補名單顯示 (放在最後以確保即時更新)
# ---------------------------------------------------------------------------
st.sidebar.title("🛒 候補購物車")
st.sidebar.markdown("---")

if not st.session_state['candidate_cart']:
    st.sidebar.info("尚未加入任何候補客戶")
else:
    st.sidebar.markdown(f"**已選擇 {len(st.session_state['candidate_cart'])} 家客戶**")
    for cid in st.session_state['candidate_cart']:
        if cid in df_valid.index:
            row = df_valid.loc[cid]
            cname = row[name_col]
            st.sidebar.text(f"• {cname}")
        else:
            st.sidebar.text(f"• 未知客戶 (ID: {cid})")
            
    if st.sidebar.button("清空候補名單"):
        st.session_state['candidate_cart'] = []
        st.rerun()
