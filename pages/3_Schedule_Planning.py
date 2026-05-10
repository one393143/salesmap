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
        '是否為強制預約': [False] * len(df_selected),
        '強制抵達時間(可留白)': [''] * len(df_selected),
        '客製停留時間(分鐘)': [default_stay] * len(df_selected)
    }, index=df_selected.index)
    
    edited_df = st.data_editor(
        display_df,
        column_config={
            "是否為強制預約": st.column_config.CheckboxColumn(
                help="勾選代表此客戶有預約時間，必須在指定時間抵達"
            ),
            "強制抵達時間(可留白)": st.column_config.TextColumn(
                help="格式例如: 14:00"
            ),
            "客製停留時間(分鐘)": st.column_config.NumberColumn(
                min_value=10,
                max_value=120,
                step=5,
                format="%d"
            )
        },
        use_container_width=True
    )
    
    st.markdown("---")
    st.markdown("### 3. 計算最佳時間鏈")
    
    def get_optimized_trip_open(coords_list, token):
        import requests
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
        from utils import MAPBOX_TOKEN, geocode_single_address
        from datetime import datetime, timedelta
        
        # 1. 找出錨點
        anchor_row = None
        for idx, row in edited_df.iterrows():
            if row['是否為強制預約'] and str(row['強制抵達時間(可留白)']).strip():
                anchor_row = row
                anchor_idx = idx
                break
                
        if anchor_row is None:
            st.warning("請先在表格中勾選『是否為強制預約』並填寫『強制抵達時間』，系統才能進行時間窗切分。")
        else:
            forced_time_str = str(anchor_row['強制抵達時間(可留白)']).strip()
            try:
                forced_time = datetime.strptime(forced_time_str, "%H:%M").time()
            except:
                st.error(f"時間格式錯誤：{forced_time_str}，請使用 24 小時制，例如 14:00")
                st.stop()
                
            st.info(f"偵測到預約客戶：{anchor_row['客戶名稱']}，預約時間：{forced_time_str}")
            
            # 解析出發時間
            start_datetime = datetime.combine(datetime.today(), start_time)
            forced_datetime = datetime.combine(datetime.today(), forced_time)
            
            if forced_datetime <= start_datetime:
                st.error("預約時間必須晚於出發時間！")
                st.stop()
                
            # 取得公司座標
            start_lat, start_lon = geocode_single_address(start_addr, MAPBOX_TOKEN)
            if start_lat is None:
                st.error(f"無法解析公司地址：{start_addr}")
                st.stop()
                
            # 取得客戶座標
            df_all = st.session_state['client_data']
            anchor_lat = df_all.loc[anchor_idx]['Latitude']
            anchor_lon = df_all.loc[anchor_idx]['Longitude']
            
            other_ids = [idx for idx in edited_df.index if idx != anchor_idx]
            
            # 演算法：自動切分
            morning_ids = other_ids.copy()
            afternoon_ids = []
            
            success = False
            final_morning_legs = []
            final_morning_order = []
            
            while len(morning_ids) >= 0:
                # 準備上午座標
                morning_coords = [(start_lat, start_lon)]
                for mid in morning_ids:
                    morning_coords.append((df_all.loc[mid]['Latitude'], df_all.loc[mid]['Longitude']))
                morning_coords.append((anchor_lat, anchor_lon))
                
                # 呼叫 API
                geojson, waypoints, legs = get_optimized_trip_open(morning_coords, MAPBOX_TOKEN)
                
                if legs is not None:
                    # 建立訪問順序對應到輸入索引的 mapping
                    visit_order = [None] * len(waypoints)
                    for i, wp in enumerate(waypoints):
                        visit_order[wp['waypoint_index']] = i
                        
                    current_time = start_datetime
                    
                    # 遍歷每一段計算抵達時間
                    for idx in range(len(legs)):
                        leg = legs[idx]
                        travel_time = leg['duration'] / 60 # 分鐘
                        
                        current_time += timedelta(minutes=travel_time)
                        
                        if idx < len(legs) - 1:
                            next_input_idx = visit_order[idx + 1]
                            cid = morning_ids[next_input_idx - 1]
                            stay_time = int(edited_df.loc[cid]['客製停留時間(分鐘)'])
                            current_time += timedelta(minutes=stay_time)
                            
                    # 檢查最後抵達錨點的時間是否及時
                    if current_time <= forced_datetime:
                        success = True
                        final_morning_legs = legs
                        final_morning_order = visit_order
                        break
                    else:
                        # 會遲到，移除非錨點的最後一個客戶
                        # 也就是倒數第二個訪問點 (倒數第一個是錨點，索引為 len(legs))
                        # 倒數第二個訪問點的索引為 len(legs) - 1
                        last_cust_input_idx = visit_order[len(legs) - 1]
                        customer_to_move = morning_ids[last_cust_input_idx - 1]
                        
                        morning_ids.remove(customer_to_move)
                        afternoon_ids.insert(0, customer_to_move)
                else:
                    st.error("呼叫 Mapbox API 失敗！")
                    st.stop()
                    
            if not success:
                st.error("⚠️ 警告：行程過度擁擠！即使直達預約客戶也會遲到，或無法塞入任何客戶。")
            else:
                st.success("✅ 時間窗切分成功！")
                
                # 顯示結果
                st.markdown("### 📅 最終排程與地圖")
                
                col_left, col_right = st.columns([1, 1])
                
                with col_left:
                    st.markdown("#### ⏱️ 行程時刻表")
                    
                    # 使用 HTML/CSS 繪製時間軸
                    timeline_html = """
                    <style>
                    .timeline {
                        border-left: 3px solid #007bff;
                        padding-left: 20px;
                        margin-left: 10px;
                        position: relative;
                    }
                    .timeline-item {
                        margin-bottom: 20px;
                        position: relative;
                    }
                    .timeline-item::before {
                        content: '';
                        width: 12px;
                        height: 12px;
                        background-color: #007bff;
                        border-radius: 50%;
                        position: absolute;
                        left: -28px;
                        top: 5px;
                    }
                    .timeline-time {
                        font-weight: bold;
                        color: #007bff;
                    }
                    .timeline-title {
                        font-weight: bold;
                        font-size: 1.1em;
                    }
                    .timeline-desc {
                        color: #666;
                        font-size: 0.9em;
                    }
                    .nav-btn {
                        display: inline-block;
                        background-color: #28a745;
                        color: white;
                        padding: 5px 10px;
                        text-decoration: none;
                        border-radius: 4px;
                        font-size: 0.8em;
                        margin-top: 5px;
                    }
                    </style>
                    <div class="timeline">
                    """
                    
                    # 1. 處理上午場時間軸
                    current_time = start_datetime
                    timeline_html += f"""
                    <div class="timeline-item">
                        <span class="timeline-time">{current_time.strftime('%H:%M')}</span>
                        <div class="timeline-title">🏢 出發點 (公司)</div>
                    </div>
                    """
                    
                    morning_stops = []
                    afternoon_stops = []
                    
                    import urllib.parse
                    
                    for idx in range(len(final_morning_legs)):
                        leg = final_morning_legs[idx]
                        travel_time = leg['duration'] / 60
                        
                        # 記錄上一站地址
                        if idx == 0:
                            prev_addr = start_addr
                        else:
                            prev_input_idx = final_morning_order[idx]
                            prev_cid = morning_ids[prev_input_idx - 1]
                            prev_addr = df_all.loc[prev_cid]['清洗後地址']
                            
                        current_time += timedelta(minutes=travel_time)
                        
                        next_input_idx = final_morning_order[idx + 1]
                        if idx == len(final_morning_legs) - 1:
                            # 抵達錨點
                            dest_addr = anchor_row['地址']
                            nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}"
                            
                            timeline_html += f"""
                            <div class="timeline-item">
                                <span class="timeline-time">{current_time.strftime('%H:%M')}</span>
                                <div class="timeline-title">🏁 ⭐ {anchor_row['客戶名稱']} (錨點)</div>
                                <div class="timeline-desc">🚗 車程: {travel_time:.1f} 分</div>
                                <a href="{nav_url}" target="_blank" class="nav-btn">🗺️ 分段導航</a>
                            </div>
                            """
                            morning_stops.append((anchor_lat, anchor_lon, f"⭐ {anchor_row['客戶名稱']}"))
                        else:
                            cid = morning_ids[next_input_idx - 1]
                            cname = edited_df.loc[cid]['客戶名稱']
                            stay_time = int(edited_df.loc[cid]['客製停留時間(分鐘)'])
                            dest_addr = edited_df.loc[cid]['地址']
                            
                            nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}"
                            
                            timeline_html += f"""
                            <div class="timeline-item">
                                <span class="timeline-time">{current_time.strftime('%H:%M')}</span>
                                <div class="timeline-title">📍 {cname}</div>
                                <div class="timeline-desc">🚗 車程: {travel_time:.1f} 分 | ⏳ 停留 {stay_time} 分鐘</div>
                                <a href="{nav_url}" target="_blank" class="nav-btn">🗺️ 分段導航</a>
                            </div>
                            """
                            morning_stops.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude'], cname))
                            current_time += timedelta(minutes=stay_time)
                            
                    # 2. 處理下午場時間軸
                    if afternoon_ids:
                        anchor_stay = int(anchor_row['客製停留時間(分鐘)'])
                        current_time += timedelta(minutes=anchor_stay)
                        
                        timeline_html += f"""
                        </div> <!-- 結束上午 timeline -->
                        <div style="margin: 20px 0; font-weight: bold; color: #ffa500;">🌆 下午場 (預約錨點 ➔ 公司)</div>
                        <div class="timeline" style="border-left-color: #ffa500;">
                        <div class="timeline-item" style="border-left-color: #ffa500;">
                            <span class="timeline-time">{current_time.strftime('%H:%M')}</span>
                            <div class="timeline-title">⭐ 從錨點出發</div>
                        </div>
                        """
                        
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
                            
                            next_input_idx = visit_order_aft[idx + 1]
                            if idx == len(legs_aft) - 1:
                                dest_addr = start_addr
                                nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}"
                                
                                timeline_html += f"""
                                <div class="timeline-item">
                                    <span class="timeline-time">{current_time.strftime('%H:%M')}</span>
                                    <div class="timeline-title">🏢 抵達公司 (終點)</div>
                                    <div class="timeline-desc">🚗 車程: {travel_time:.1f} 分</div>
                                    <a href="{nav_url}" target="_blank" class="nav-btn">🗺️ 分段導航</a>
                                </div>
                                """
                            else:
                                cid = afternoon_ids[next_input_idx - 1]
                                cname = edited_df.loc[cid]['客戶名稱']
                                stay_time = int(edited_df.loc[cid]['客製停留時間(分鐘)'])
                                dest_addr = edited_df.loc[cid]['地址']
                                
                                nav_url = f"https://www.google.com/maps/dir/?api=1&origin={urllib.parse.quote(str(prev_addr))}&destination={urllib.parse.quote(str(dest_addr))}"
                                
                                timeline_html += f"""
                                <div class="timeline-item">
                                    <span class="timeline-time">{current_time.strftime('%H:%M')}</span>
                                    <div class="timeline-title">📍 {cname}</div>
                                    <div class="timeline-desc">🚗 車程: {travel_time:.1f} 分 | ⏳ 停留 {stay_time} 分鐘</div>
                                    <a href="{nav_url}" target="_blank" class="nav-btn">🗺️ 分段導航</a>
                                </div>
                                """
                                afternoon_stops.append((df_all.loc[cid]['Latitude'], df_all.loc[cid]['Longitude'], cname))
                                current_time += timedelta(minutes=stay_time)
                                
                    timeline_html += "</div>"
                    st.markdown(timeline_html, unsafe_allow_html=True)
                    
                with col_right:
                    st.markdown("#### 🗺️ 視覺化地圖")
                    import folium
                    from streamlit_folium import folium_static
                    
                    m = folium.Map(location=[start_lat, start_lon], zoom_start=12)
                    
                    # 1. 繪製上午軌跡 (藍色)
                    if 'geojson' in locals() and geojson:
                        folium.GeoJson(
                            geojson,
                            style_function=lambda x: {'color': '#007bff', 'weight': 5, 'opacity': 0.8}
                        ).add_to(m)
                        
                        coords = geojson['coordinates']
                        mid_idx = len(coords) // 2
                        mid_coord = coords[mid_idx]
                        folium.Marker(
                            location=[mid_coord[1], mid_coord[0]],
                            icon=folium.DivIcon(html=f'<div style="color: blue; font-weight: bold; background: white; padding: 2px; border-radius: 3px;">🚗 上午場</div>')
                        ).add_to(m)
                        
                    # 2. 繪製下午軌跡 (橘色)
                    if 'geojson_aft' in locals() and geojson_aft:
                        folium.GeoJson(
                            geojson_aft,
                            style_function=lambda x: {'color': '#ffa500', 'weight': 5, 'opacity': 0.8}
                        ).add_to(m)
                        
                        coords = geojson_aft['coordinates']
                        mid_idx = len(coords) // 2
                        mid_coord = coords[mid_idx]
                        folium.Marker(
                            location=[mid_coord[1], mid_coord[0]],
                            icon=folium.DivIcon(html=f'<div style="color: orange; font-weight: bold; background: white; padding: 2px; border-radius: 3px;">🚗 下午場</div>')
                        ).add_to(m)
                        
                    # 3. 繪製帶數字的圖釘
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

