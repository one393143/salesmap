import streamlit as st
import pandas as pd
from datetime import time, datetime, timedelta
import requests
import urllib.parse
import folium
from streamlit_folium import folium_static
from utils import MAPBOX_TOKEN, geocode_single_address

st.title("⏱️ 行程排程")
st.markdown("設定出發時間與預約時段。")

# 防呆提醒
if 'client_data' not in st.session_state:
    st.warning("⚠️ 尚未載入客戶資料！請先至「資料設定」頁面載入或上傳資料。")
    st.stop()

if 'candidate_cart' not in st.session_state or not st.session_state['candidate_cart']:
    st.info("💡 請先至「客戶地圖」頁面篩選並選擇您預計拜訪的客戶到候補名單。")
    st.stop()

df_all = st.session_state['client_data']
selected_ids = st.session_state['candidate_cart']

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

# 臨時插隊功能
st.markdown("#### ➕ 臨時新增客戶")
# 濾除已在候補名單中的客戶
available_clients = df_all[~df_all.index.isin(st.session_state['candidate_cart'])]
options = [f"{idx} - {row[name_col]}" for idx, row in available_clients.iterrows()]
selected_new_client = st.selectbox("從總資料庫拉取新客戶進來排程", ["請選擇客戶..."] + options)

if selected_new_client != "請選擇客戶...":
    new_idx = int(selected_new_client.split(" - ")[0])
    st.session_state['candidate_cart'].append(new_idx)
    st.success(f"已新增客戶 {new_idx}，正在更新表格...")
    st.rerun()

st.markdown("您可以在下方表格中，為特定客戶設定「是否強制預約」與「預約抵達時間」。")

# 準備 data_editor 的資料
display_df = pd.DataFrame({
    'index': df_selected.index,
    '客戶名稱': df_selected[name_col].values,
    '地址': df_selected['清洗後地址'].values if '清洗後地址' in df_selected.columns else df_selected.get('地址', df_selected.columns[0]).values,
    '是否為強制預約': [False] * len(df_selected),
    '預約抵達時間': [None] * len(df_selected),
    '移除此站': [False] * len(df_selected)
})

edited_df = st.data_editor(
    display_df,
    column_config={
        "是否為強制預約": st.column_config.CheckboxColumn(
            help="勾選代表此客戶有預約時間，必須在指定時間抵達"
        ),
        "預約抵達時間": st.column_config.TimeColumn(
            help="選擇預約抵達時間"
        ),
        "移除此站": st.column_config.CheckboxColumn(
            help="勾選此欄位以移除此站"
        )
    },
    use_container_width=True,
    disabled=['index', '客戶名稱', '地址'],
    hide_index=True,
    key="schedule_editor"
)

# 處理單站移除功能
for i, row in edited_df.iterrows():
    if row['移除此站']:
        orig_idx = row['index']
        st.session_state['candidate_cart'].remove(orig_idx)
        st.success(f"已移除站點！正在重新計算...")
        st.rerun()

# 將 index 設回，方便後續邏輯存取
edited_df_indexed = edited_df.set_index('index')

st.markdown("---")
st.markdown("### 3. 計算最佳時間鏈")

def get_optimized_trip_open(coords_list, token):
    if len(coords_list) < 2 or not token: return None, None, None
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
    url = f"https://api.mapbox.com/optimized-trips/v1/mapbox/driving/{coords_str}"
    params = {
        'roundtrip': 'false',
        'source': 'first',
        'destination': 'last',
        'geometries': 'geojson',
        'access_token': token
    }
    try:
        res = requests.get(url, params=params).json()
        if 'trips' in res and len(res['trips']) > 0:
            return res['trips'][0]['geometry'], res['waypoints'], res['trips'][0]['legs']
    except Exception as e:
        print(e)
    return None, None, None

if st.button("🚀 產生最佳時間排程", use_container_width=True, type="primary"):
    # 1. 找出錨點
    anchor_row = None
    anchor_idx = None
    for idx, row in edited_df_indexed.iterrows():
        if row['是否為強制預約'] and row['預約抵達時間'] is not None:
            anchor_row = row
            anchor_idx = idx
            break
            
    # 取得公司座標
    start_lat, start_lon = geocode_single_address(start_addr, MAPBOX_TOKEN)
    if start_lat is None:
        st.error(f"無法解析公司地址：{start_addr}")
        st.stop()
        
    start_datetime = datetime.combine(datetime.today(), start_time)
    
    if anchor_row is None:
        # ==========================================
        # 模式 A：標準 TSP 最佳化 (無強制預約)
        # ==========================================
        st.info("ℹ️ 未設定強制預約客戶，系統將進行**標準最佳化排程**（環狀路線回到公司）。")
        
        client_ids = list(edited_df_indexed.index)
        if not client_ids:
            st.warning("請先在上方表格中選擇想去的客戶！")
            st.stop()
            
        coords = [(start_lat, start_lon)]
        for cid in client_ids:
            coords.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude']))
            
        # 呼叫 API (roundtrip=true)
        coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
        url = f"https://api.mapbox.com/optimized-trips/v1/mapbox/driving/{coords_str}"
        params = {
            'roundtrip': 'true',
            'source': 'first',
            'geometries': 'geojson',
            'access_token': MAPBOX_TOKEN
        }
        res = requests.get(url, params=params).json()
        
        if 'trips' not in res or len(res['trips']) == 0:
            st.error("呼叫 Mapbox API 失敗！")
            st.stop()
            
        geojson = res['trips'][0]['geometry']
        waypoints = res['waypoints']
        legs = res['trips'][0]['legs']
        
        visit_order = [None] * len(waypoints)
        for i, wp in enumerate(waypoints):
            visit_order[wp['waypoint_index']] = i
            
        st.markdown("### 📅 最終排程與地圖")
        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            st.markdown("#### ⏱️ 行程時刻表")
            
            timeline_html = """
<style>
.funliday-list {
display: flex;
flex-direction: column;
gap: 15px;
padding: 10px;
background-color: #f8f9fa;
border-radius: 10px;
}
.funliday-item {
display: flex;
align-items: center;
gap: 10px;
background-color: white;
padding: 12px;
border-radius: 8px;
box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.funliday-pin {
background-color: #ff5a5f;
color: white;
border-radius: 50%;
width: 24px;
height: 24px;
display: flex;
align-items: center;
justify-content: center;
font-weight: bold;
font-size: 14px;
}
.funliday-content {
flex: 1;
}
.funliday-title {
font-weight: bold;
color: #333;
font-size: 14px;
}
.funliday-time {
font-size: 12px;
color: #666;
}
.funliday-transit {
display: flex;
align-items: center;
gap: 8px;
margin-left: 12px;
border-left: 2px dashed #ff5a5f;
padding-left: 20px;
padding-top: 5px;
padding-bottom: 5px;
font-size: 13px;
color: #666;
}
.funliday-transit a {
color: #ff5a5f;
text-decoration: none;
font-weight: bold;
}
.funliday-transit a:hover {
text-decoration: underline;
}
</style>
<div class="funliday-list">
"""
            
            current_time = start_datetime
            # 第一站：公司
            timeline_html += f"""
<div class="funliday-item">
<div class="funliday-pin">起</div>
<div class="funliday-content">
    <div class="funliday-title">🏢 出發點 (公司)</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')} 出發</div>
</div>
</div>
"""
            
            stops_for_map = []
            
            for idx in range(len(legs)):
                leg = legs[idx]
                travel_time = leg['duration'] / 60
                
                if idx == 0:
                    prev_addr = start_addr
                else:
                    prev_input_idx = visit_order[idx]
                    prev_cid = client_ids[prev_input_idx - 1]
                    prev_addr = df_all.loc[prev_cid]['清洗後地址']
                    
                current_time += timedelta(minutes=travel_time)
                
                if idx == len(legs) - 1:
                    dest_addr = start_addr
                    nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}&travelmode=driving"
                    
                    timeline_html += f"""
<div class="funliday-transit">
<span>🚗 車程 {travel_time:.0f} 分鐘</span>
<a href="{nav_url}" target="_blank">🗺️ 導航</a>
</div>
<div class="funliday-item">
<div class="funliday-pin">終</div>
<div class="funliday-content">
    <div class="funliday-title">🏢 抵達公司 (終點)</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')}</div>
</div>
</div>
"""
                else:
                    next_input_idx = visit_order[idx + 1]
                    cid = client_ids[next_input_idx - 1]
                    cname = edited_df_indexed.loc[cid]['客戶名稱']
                    stay_time = default_stay
                    dest_addr = edited_df_indexed.loc[cid]['地址']
                    
                    nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}&travelmode=driving"
                    
                    end_stay_time = current_time + timedelta(minutes=stay_time)
                    
                    timeline_html += f"""
<div class="funliday-transit">
<span>🚗 車程 {travel_time:.0f} 分鐘</span>
<a href="{nav_url}" target="_blank">🗺️ 導航</a>
</div>
<div class="funliday-item">
<div class="funliday-pin">{idx+1}</div>
<div class="funliday-content">
    <div class="funliday-title">📍 {cname}</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')} - {end_stay_time.strftime('%H:%M')} (停留 {stay_time} 分)</div>
</div>
</div>
"""
                    stops_for_map.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude'], cname))
                    current_time = end_stay_time
                    
            timeline_html += "</div>"
            st.markdown(timeline_html, unsafe_allow_html=True)
            
        with col_right:
            st.markdown("#### 🗺️ 視覺化地圖")
            m = folium.Map(location=[start_lat, start_lon], zoom_start=12, tiles=None)
            folium.TileLayer(
                tiles="https://api.mapbox.com/styles/v1/mapbox/light-v10/tiles/{z}/{x}/{y}?access_token=" + MAPBOX_TOKEN,
                attr="Mapbox",
                name="Mapbox Light"
            ).add_to(m)
            
            folium.GeoJson(
                geojson,
                style_function=lambda x: {'color': '#ff5a5f', 'weight': 5, 'opacity': 0.8}
            ).add_to(m)
            
            folium.Marker(
                location=[start_lat, start_lon],
                icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #ff5a5f; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">起</div>'),
                popup="🏢 公司"
            ).add_to(m)
            
            for i, stop in enumerate(stops_for_map):
                folium.Marker(
                    location=[stop[0], stop[1]],
                    icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #ff5a5f; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">{i+1}</div>'),
                    popup=stop[2]
                ).add_to(m)
                
            folium_static(m)
            
    else:
        # ==========================================
        # 模式 B：時間窗切分 (有強制預約)
        # ==========================================
        forced_time = anchor_row['預約抵達時間']
        forced_time_str = forced_time.strftime("%H:%M")
            
        st.info(f"偵測到預約客戶：{anchor_row['客戶名稱']}，預約時間：{forced_time_str}")
        
        forced_datetime = datetime.combine(datetime.today(), forced_time)
        
        if forced_datetime <= start_datetime:
            st.error("預約時間必須晚於出發時間！")
            st.stop()
            
        anchor_lat = df_all.loc[anchor_idx]['Latitude']
        anchor_lon = df_all.loc[anchor_idx]['Longitude']
        
        other_ids = [idx for idx in edited_df_indexed.index if idx != anchor_idx]
        
        morning_ids = other_ids.copy()
        afternoon_ids = []
        
        success = False
        final_morning_legs = []
        final_morning_order = []
        
        while len(morning_ids) >= 0:
            morning_coords = [(start_lat, start_lon)]
            for mid in morning_ids:
                morning_coords.append((df_all.loc[mid]['Latitude'], df_all.loc[mid]['Longitude']))
            morning_coords.append((anchor_lat, anchor_lon))
            
            geojson, waypoints, legs = get_optimized_trip_open(morning_coords, MAPBOX_TOKEN)
            
            if legs is not None:
                visit_order = [None] * len(waypoints)
                for i, wp in enumerate(waypoints):
                    visit_order[wp['waypoint_index']] = i
                    
                current_time = start_datetime
                
                for idx in range(len(legs)):
                    leg = legs[idx]
                    travel_time = leg['duration'] / 60
                    current_time += timedelta(minutes=travel_time)
                    
                    if idx < len(legs) - 1:
                        next_input_idx = visit_order[idx + 1]
                        cid = morning_ids[next_input_idx - 1]
                        stay_time = default_stay
                        current_time += timedelta(minutes=stay_time)
                        
                if current_time <= forced_datetime:
                    success = True
                    final_morning_legs = legs
                    final_morning_order = visit_order
                    break
                else:
                    last_cust_input_idx = visit_order[len(legs) - 1]
                    customer_to_move = morning_ids[last_cust_input_idx - 1]
                    
                    morning_ids.remove(customer_to_move)
                    afternoon_ids.insert(0, customer_to_move)
            else:
                st.error("呼叫 Mapbox API 失敗！")
                st.stop()
                
        if not success:
            st.error("⚠️ 警告：行程過度擁擠！即使直達預約客戶也會遲到。")
        else:
            st.success("✅ 時間窗切分成功！")
            
            st.markdown("### 📅 最終排程與地圖")
            col_left, col_right = st.columns([1, 1])
            
            with col_left:
                st.markdown("#### ⏱️ 行程時刻表")
            
                timeline_html = """
<style>
.funliday-list {
display: flex;
flex-direction: column;
gap: 15px;
padding: 10px;
background-color: #f8f9fa;
border-radius: 10px;
}
.funliday-item {
display: flex;
align-items: center;
gap: 10px;
background-color: white;
padding: 12px;
border-radius: 8px;
box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}
.funliday-pin {
background-color: #ff5a5f;
color: white;
border-radius: 50%;
width: 24px;
height: 24px;
display: flex;
align-items: center;
justify-content: center;
font-weight: bold;
font-size: 14px;
}
.funliday-content {
flex: 1;
}
.funliday-title {
font-weight: bold;
color: #333;
font-size: 14px;
}
.funliday-time {
font-size: 12px;
color: #666;
}
.funliday-transit {
display: flex;
align-items: center;
gap: 8px;
margin-left: 12px;
border-left: 2px dashed #ff5a5f;
padding-left: 20px;
padding-top: 5px;
padding-bottom: 5px;
font-size: 13px;
color: #666;
}
.funliday-transit a {
color: #ff5a5f;
text-decoration: none;
font-weight: bold;
}
.funliday-transit a:hover {
text-decoration: underline;
}
</style>
<div class="funliday-list">
"""
            
                current_time = start_datetime
                # 第一站：公司
                timeline_html += f"""
<div class="funliday-item">
<div class="funliday-pin">起</div>
<div class="funliday-content">
    <div class="funliday-title">🏢 出發點 (公司)</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')} 出發</div>
</div>
</div>
"""
            
                morning_stops = []
                afternoon_stops = []
            
                # 上午場
                for idx in range(len(final_morning_legs)):
                    leg = final_morning_legs[idx]
                    travel_time = leg['duration'] / 60
                    
                    if idx == 0:
                        prev_addr = start_addr
                    else:
                        prev_input_idx = final_morning_order[idx]
                        prev_cid = morning_ids[prev_input_idx - 1]
                        prev_addr = df_all.loc[prev_cid]['清洗後地址']
                        
                    current_time += timedelta(minutes=travel_time)
                    
                    if idx == len(final_morning_legs) - 1:
                        dest_addr = anchor_row['地址']
                        nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}&travelmode=driving"
                        
                        timeline_html += f"""
<div class="funliday-transit">
<span>🚗 車程 {travel_time:.0f} 分鐘</span>
<a href="{nav_url}" target="_blank">🗺️ 導航</a>
</div>
<div class="funliday-item" style="border: 2px solid #ff5a5f;">
<div class="funliday-pin">⭐</div>
<div class="funliday-content">
    <div class="funliday-title">🏁 {anchor_row['客戶名稱']} (錨點)</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')} 抵達</div>
</div>
</div>
"""
                        morning_stops.append((anchor_lat, anchor_lon, f"⭐ {anchor_row['客戶名稱']}"))
                    else:
                        next_input_idx = final_morning_order[idx + 1]
                        cid = morning_ids[next_input_idx - 1]
                        cname = edited_df_indexed.loc[cid]['客戶名稱']
                        stay_time = default_stay
                        dest_addr = edited_df_indexed.loc[cid]['地址']
                        
                        nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}&travelmode=driving"
                        
                        end_stay_time = current_time + timedelta(minutes=stay_time)
                        
                        timeline_html += f"""
<div class="funliday-transit">
<span>🚗 車程 {travel_time:.0f} 分鐘</span>
<a href="{nav_url}" target="_blank">🗺️ 導航</a>
</div>
<div class="funliday-item">
<div class="funliday-pin">{idx+1}</div>
<div class="funliday-content">
    <div class="funliday-title">📍 {cname}</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')} - {end_stay_time.strftime('%H:%M')} (停留 {stay_time} 分)</div>
</div>
</div>
"""
                        morning_stops.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude'], cname))
                        current_time = end_stay_time
                        
                # 下午場
                if afternoon_ids:
                    anchor_stay = default_stay
                    current_time += timedelta(minutes=anchor_stay)
                    
                    timeline_html += f"""
<div style="margin: 15px 0; font-weight: bold; color: #ffa500; font-size: 14px;">🌆 下午場 (預約錨點 ➔ 公司)</div>
"""
                    
                    afternoon_coords = [(anchor_lat, anchor_lon)]
                    for aid in afternoon_ids:
                        afternoon_coords.append((df_all.loc[aid]['Latitude'], df_all.loc[aid]['Longitude']))
                    afternoon_coords.append((start_lat, start_lon))
                    
                    geojson_aft, waypoints_aft, legs_aft = get_optimized_trip_open(afternoon_coords, MAPBOX_TOKEN)
                    
                    if legs_aft:
                        visit_order_aft = [None] * len(waypoints_aft)
                        for i, wp in enumerate(waypoints_aft):
                            visit_order_aft[wp['waypoint_index']] = i
                            
                        for idx in range(len(legs_aft)):
                            leg = legs_aft[idx]
                            travel_time = leg['duration'] / 60
                            
                            if idx == 0:
                                prev_addr = anchor_row['地址']
                            else:
                                prev_input_idx = visit_order_aft[idx]
                                prev_cid = afternoon_ids[prev_input_idx - 1]
                                prev_addr = df_all.loc[prev_cid]['清洗後地址']
                                
                            current_time += timedelta(minutes=travel_time)
                            
                            if idx == len(legs_aft) - 1:
                                dest_addr = start_addr
                                nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}&travelmode=driving"
                                
                                timeline_html += f"""
<div class="funliday-transit" style="border-left-color: #ffa500;">
<span>🚗 車程 {travel_time:.0f} 分鐘</span>
<a href="{nav_url}" target="_blank" style="color: #ffa500;">🗺️ 導航</a>
</div>
<div class="funliday-item">
<div class="funliday-pin" style="background-color: #ffa500;">終</div>
<div class="funliday-content">
    <div class="funliday-title">🏢 抵達公司 (終點)</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')}</div>
</div>
</div>
"""
                            else:
                                next_input_idx = visit_order_aft[idx + 1]
                                cid = afternoon_ids[next_input_idx - 1]
                                cname = edited_df_indexed.loc[cid]['客戶名稱']
                                stay_time = default_stay
                                dest_addr = edited_df_indexed.loc[cid]['地址']
                                
                                nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}&travelmode=driving"
                                
                                end_stay_time = current_time + timedelta(minutes=stay_time)
                                
                                timeline_html += f"""
<div class="funliday-transit" style="border-left-color: #ffa500;">
<span>🚗 車程 {travel_time:.0f} 分鐘</span>
<a href="{nav_url}" target="_blank" style="color: #ffa500;">🗺️ 導航</a>
</div>
<div class="funliday-item">
<div class="funliday-pin">{len(morning_stops)+1+idx}</div>
<div class="funliday-content">
    <div class="funliday-title">📍 {cname}</div>
    <div class="funliday-time">{current_time.strftime('%H:%M')} - {end_stay_time.strftime('%H:%M')} (停留 {stay_time} 分)</div>
</div>
</div>
"""
                                afternoon_stops.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude'], cname))
                                current_time = end_stay_time
                                
                timeline_html += "</div>"
                st.markdown(timeline_html, unsafe_allow_html=True)
                
            with col_right:
                st.markdown("#### 🗺️ 視覺化地圖")
                m = folium.Map(location=[start_lat, start_lon], zoom_start=12, tiles=None)
                folium.TileLayer(
                    tiles="https://api.mapbox.com/styles/v1/mapbox/light-v10/tiles/{z}/{x}/{y}?access_token=" + MAPBOX_TOKEN,
                    attr="Mapbox",
                    name="Mapbox Light"
                ).add_to(m)
                
                if 'geojson' in locals() and geojson:
                    folium.GeoJson(
                        geojson,
                        name="上午場路線",
                        style_function=lambda x: {'color': '#ff5a5f', 'weight': 5, 'opacity': 0.8}
                    ).add_to(m)
                    
                if 'geojson_aft' in locals() and geojson_aft:
                    folium.GeoJson(
                        geojson_aft,
                        name="下午場路線",
                        style_function=lambda x: {'color': '#ffa500', 'weight': 5, 'opacity': 0.8}
                    ).add_to(m)
                    
                folium.Marker(
                    location=[start_lat, start_lon],
                    icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #007bff; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">起</div>'),
                    popup="🏢 出發點 (公司)"
                ).add_to(m)
                
                for i, stop in enumerate(morning_stops):
                    folium.Marker(
                        location=[stop[0], stop[1]],
                        icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #007bff; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">{i+1}</div>'),
                        popup=stop[2]
                    ).add_to(m)
                    
                folium.Marker(
                    location=[anchor_lat, anchor_lon],
                    icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #ff0000; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">⭐</div>'),
                    popup=f"⭐ {anchor_row['客戶名稱']} (錨點)"
                ).add_to(m)
                
                for i, stop in enumerate(afternoon_stops):
                    folium.Marker(
                        location=[stop[0], stop[1]],
                        icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #ffa500; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">{len(morning_stops)+1+i}</div>'),
                        popup=stop[2]
                    ).add_to(m)
                    
                folium_static(m)
