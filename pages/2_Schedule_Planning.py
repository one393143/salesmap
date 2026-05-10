import streamlit as st
import pandas as pd
from datetime import time, datetime, timedelta
import requests
import urllib.parse
import folium
from streamlit_folium import folium_static
from utils import MAPBOX_TOKEN, geocode_single_address

st.title("⏱️ 行程排程")
st.markdown("設定出發時間、休息時間與預約時段。")

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

st.markdown("### 1. 設定出發與休息情境")
col1, col2, col3 = st.columns(3)
with col1:
    start_addr = st.text_input("🏢 出發與結束地址", value="台北市松山區南京東路五段202號")
    
with col2:
    auto_start = st.checkbox("🤖 自動推算出發時間", help="勾選後，系統將依據您設定的「強制預約時間」自動往回推算最晚出發時間。")
    if auto_start:
        start_time_input = st.time_input("⏰ 今日出發時間 (唯讀)", value=time(9, 0), disabled=True)
    else:
        start_time_input = st.time_input("⏰ 今日出發時間", value=time(9, 0))

with col3:
    default_stay = st.number_input("⏳ 預設每站停留 (分鐘)", min_value=10, max_value=120, value=40, step=5)

# 休息時間設定
st.markdown("#### ☕ 休息時間設定 (例如午休)")
col_r1, col_r2 = st.columns(2)
with col_r1:
    rest_start = st.time_input("休息開始時間", value=time(12, 0), step=1800)
with col_r2:
    rest_end = st.time_input("休息結束時間", value=time(13, 0), step=1800)

st.markdown("---")
st.markdown("### 2. 客製化客戶拜訪設定")

# 臨時插隊功能
st.markdown("#### ➕ 臨時新增客戶")
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
            help="選擇預約抵達時間",
            format="HH:mm",
            step=60
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

if st.button("🚀 產生最佳時間排程", use_container_width=True, type="primary"):
    # 1. 找出錨點 (預約客戶)
    anchor_row = None
    anchor_idx = None
    for idx, row in edited_df_indexed.iterrows():
        if row['是否為強制預約'] and row['預約抵達時間'] is not None:
            anchor_row = row
            anchor_idx = idx
            break
            
    if auto_start and anchor_row is None:
        st.error("⚠️ 勾選了「自動推算出發時間」，但未設定任何強制預約客戶與時間！")
        st.stop()
        
    # 取得公司座標
    start_lat, start_lon = geocode_single_address(start_addr, MAPBOX_TOKEN)
    if start_lat is None:
        st.error(f"無法解析公司地址：{start_addr}")
        st.stop()
        
    # 呼叫 Mapbox API 取得最佳路徑 (環狀路線)
    client_ids = list(edited_df_indexed.index)
    if not client_ids:
        st.warning("請先在上方表格中選擇想去的客戶！")
        st.stop()
        
    coords = [(start_lat, start_lon)]
    for cid in client_ids:
        coords.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude']))
        
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords])
    url = f"https://api.mapbox.com/optimized-trips/v1/mapbox/driving/{coords_str}"
    params = {
        'roundtrip': 'true',
        'source': 'first',
        'geometries': 'geojson',
        'access_token': MAPBOX_TOKEN
    }
    
    try:
        res = requests.get(url, params=params).json()
        if 'trips' not in res or len(res['trips']) == 0:
            st.error("呼叫 Mapbox API 失敗！")
            st.stop()
            
        geojson = res['trips'][0]['geometry']
        waypoints = res['waypoints']
        legs = res['trips'][0]['legs']
    except Exception as e:
        st.error(f"API 發生錯誤: {e}")
        st.stop()
        
    # 取得拜訪順序
    visit_order = [None] * len(waypoints)
    for i, wp in enumerate(waypoints):
        visit_order[wp['waypoint_index']] = i
        
    # 找出錨點在路徑中的位置
    anchor_pos = None
    if anchor_idx is not None:
        for idx in range(1, len(legs)):
            next_input_idx = visit_order[idx]
            cid = client_ids[next_input_idx - 1]
            if cid == anchor_idx:
                anchor_pos = idx
                break

    # 定義時間鏈計算函數 (Forward)
    def calculate_timeline(start_dt):
        current_time = start_dt
        tl = []
        
        rest_dt_start = datetime.combine(datetime.today(), rest_start)
        rest_dt_end = datetime.combine(datetime.today(), rest_end)
        rest_applied = False
        
        # 起點
        tl.append({
            'name': '🏢 出發點 (公司)',
            'time': current_time,
            'type': 'start'
        })
        
        for idx in range(len(legs)):
            leg = legs[idx]
            travel_time = leg['duration'] / 60
            
            # 車程
            current_time += timedelta(minutes=travel_time)
            
            # 檢查是否跨越休息時間
            if not rest_applied and current_time > rest_dt_start:
                current_time += (rest_dt_end - rest_dt_start)
                rest_applied = True
                tl.append({
                    'name': '☕ 休息時間',
                    'time': rest_dt_start,
                    'type': 'rest'
                })
                
            if idx == len(legs) - 1:
                # 回到公司
                tl.append({
                    'name': '🏢 抵達公司 (終點)',
                    'time': current_time,
                    'type': 'end'
                })
            else:
                # 拜訪客戶
                next_input_idx = visit_order[idx + 1]
                cid = client_ids[next_input_idx - 1]
                cname = edited_df_indexed.loc[cid]['客戶名稱']
                stay_time = default_stay
                
                tl.append({
                    'name': f"📍 {cname}",
                    'time': current_time,
                    'type': 'stop',
                    'id': cid
                })
                
                current_time += timedelta(minutes=stay_time)
                
                # 再次檢查停留後是否跨越休息時間
                if not rest_applied and current_time > rest_dt_start:
                    current_time += (rest_dt_end - rest_dt_start)
                    rest_applied = True
                    tl.append({
                        'name': '☕ 休息時間',
                        'time': rest_dt_start,
                        'type': 'rest'
                    })
                    
        return tl

    # 決定出發時間
    if auto_start and anchor_pos is not None:
        forced_time = anchor_row['預約抵達時間']
        if isinstance(forced_time, str):
            forced_time = datetime.strptime(forced_time.split('.')[0], "%H:%M:%S").time()
        forced_dt = datetime.combine(datetime.today(), forced_time)
        
        # 初步推算：不考慮休息時間，計算從公司到預約點的總時間
        total_dur_to_anchor = 0
        for idx in range(anchor_pos):
            total_dur_to_anchor += legs[idx]['duration'] / 60
            if idx > 0:
                total_dur_to_anchor += default_stay
                
        est_start_dt = forced_dt - timedelta(minutes=total_dur_to_anchor)
        
        # 第一次模擬計算
        tl_sim = calculate_timeline(est_start_dt)
        
        # 找出模擬中預約點的抵達時間
        sim_arrival = None
        for item in tl_sim:
            if item.get('id') == anchor_idx:
                sim_arrival = item['time']
                break
                
        # 根據差距進行修正 (通常是因為休息時間被推擠)
        if sim_arrival:
            diff = forced_dt - sim_arrival
            final_start_dt = est_start_dt + diff
        else:
            final_start_dt = est_start_dt
    else:
        # 手動設定出發時間
        final_start_dt = datetime.combine(datetime.today(), start_time_input)

    # 執行最終計算
    final_timeline = calculate_timeline(final_start_dt)
    
    # ---------------------------------------------------------------------------
    # 顯示結果：時刻表與地圖
    # ---------------------------------------------------------------------------
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
</style>
<div class="funliday-list">
"""
        
        stops_for_map = []
        
        for i, item in enumerate(final_timeline):
            t_str = item['time'].strftime('%H:%M')
            
            if item['type'] == 'start':
                timeline_html += f"""
<div class="funliday-item">
    <div class="funliday-pin">起</div>
    <div class="funliday-content">
        <div class="funliday-title">{item['name']}</div>
        <div class="funliday-time">{t_str} 出發</div>
    </div>
</div>
"""
            elif item['type'] == 'end':
                timeline_html += f"""
<div class="funliday-item">
    <div class="funliday-pin">終</div>
    <div class="funliday-content">
        <div class="funliday-title">{item['name']}</div>
        <div class="funliday-time">{t_str} 抵達</div>
    </div>
</div>
"""
            elif item['type'] == 'rest':
                timeline_html += f"""
<div class="funliday-item" style="background-color: #e9ecef;">
    <div class="funliday-pin" style="background-color: #6c757d;">☕</div>
    <div class="funliday-content">
        <div class="funliday-title">{item['name']}</div>
        <div class="funliday-time">{t_str} 開始</div>
    </div>
</div>
"""
            else:
                # 判斷是否為錨點 (標記星號)
                is_anchor = (item.get('id') == anchor_idx)
                pin_bg = "#ff5a5f" if not is_anchor else "#ffc107"
                pin_text = "⭐" if is_anchor else str(i)
                
                timeline_html += f"""
<div class="funliday-item" {'style="border: 2px solid #ffc107;"' if is_anchor else ''}>
    <div class="funliday-pin" style="background-color: {pin_bg};">{pin_text}</div>
    <div class="funliday-content">
        <div class="funliday-title">{item['name']}</div>
        <div class="funliday-time">{t_str} 抵達 (預計停留 {default_stay} 分)</div>
    </div>
</div>
"""
                stops_for_map.append((df_all.loc[item['id']]['Latitude'], df_all.loc[item['id']]['Longitude'], item['name'], pin_bg))

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
        
        # 畫路徑
        folium.GeoJson(
            geojson,
            style_function=lambda x: {'color': '#ff5a5f', 'weight': 5, 'opacity': 0.8}
        ).add_to(m)
        
        # 起點
        folium.Marker(
            location=[start_lat, start_lon],
            icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: #007bff; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">起</div>'),
            popup="🏢 公司"
        ).add_to(m)
        
        # 客戶點
        for i, stop in enumerate(stops_for_map):
            folium.Marker(
                location=[stop[0], stop[1]],
                icon=folium.DivIcon(html=f'<div style="font-size: 10pt; color: white; background-color: {stop[3]}; border-radius: 50%; width: 25px; height: 25px; display: flex; align-items: center; justify-content: center;">{i+1}</div>'),
                popup=stop[2]
            ).add_to(m)
            
        folium_static(m)
