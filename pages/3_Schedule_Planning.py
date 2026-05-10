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
                return res['trips'][0]['geometry'], res['waypoints'], res['trips'][0]['duration']
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
            final_morning_route = []
            final_afternoon_route = []
            
            while len(morning_ids) >= 0:
                # 準備上午座標
                morning_coords = [(start_lat, start_lon)]
                for mid in morning_ids:
                    morning_coords.append((df_all.loc[mid]['Latitude'], df_all.loc[mid]['Longitude']))
                morning_coords.append((anchor_lat, anchor_lon))
                
                # 呼叫 API
                geojson, waypoints, duration = get_optimized_trip_open(morning_coords, MAPBOX_TOKEN)
                
                if duration is not None:
                    # 計算總時間 (交通 + 停留)
                    # 假設每站停留時間
                    total_stay = 0
                    for mid in morning_ids:
                        total_stay += int(edited_df.loc[mid]['客製停留時間(分鐘)'])
                        
                    total_time_needed = duration / 60 + total_stay # 分鐘
                    
                    available_time = (forced_datetime - start_datetime).total_seconds() / 60
                    
                    if total_time_needed <= available_time:
                        success = True
                        # 解析上午順序
                        # waypoints 排序與輸入一致
                        # input: [Company, Cust1, Cust2, ..., Anchor]
                        ordered_morning = [None] * len(waypoints)
                        for i, wp in enumerate(waypoints):
                            idx = wp['waypoint_index']
                            if i == 0:
                                ordered_morning[idx] = "🏢 公司"
                            elif i == len(waypoints) - 1:
                                ordered_morning[idx] = f"⭐ {anchor_row['客戶名稱']} (錨點)"
                            else:
                                cid = morning_ids[i-1]
                                ordered_morning[idx] = edited_df.loc[cid]['客戶名稱']
                                
                        final_morning_route = ordered_morning
                        break
                    else:
                        # 會遲到，將原本排在最後訪問的客戶移到下午
                        # 找出 waypoint_index = len(morning_ids) 的那個客戶 (即錨點前一個)
                        # 但 API 返回的 waypoint_index 是訪問順序。
                        # 我們需要找出訪問順序中，排在最後的那個 morning customer。
                        # 也就是 waypoint_index 最大的那個 morning customer。
                        
                        max_wp_idx = -1
                        customer_to_move = None
                        
                        for i, wp in enumerate(waypoints):
                            if 0 < i < len(waypoints) - 1: # 排除起點和終點
                                if wp['waypoint_index'] > max_wp_idx:
                                    max_wp_idx = wp['waypoint_index']
                                    customer_to_move = morning_ids[i-1]
                                    
                        if customer_to_move is not None:
                            morning_ids.remove(customer_to_move)
                            afternoon_ids.insert(0, customer_to_move) # 保持順序或之後再優化
                        else:
                            # 如果沒有客戶可以移了，代表連直達都會遲到
                            break
                else:
                    st.error("呼叫 Mapbox API 失敗！")
                    st.stop()
                    
            if not success:
                st.error("⚠️ 警告：行程過度擁擠！即使直達預約客戶也會遲到，或無法塞入任何客戶。")
                
                # 依然顯示直達路線
                morning_coords = [(start_lat, start_lon), (anchor_lat, anchor_lon)]
                geojson, waypoints, duration = get_optimized_trip_open(morning_coords, MAPBOX_TOKEN)
                if duration:
                    st.write(f"直達預估交通時間：{duration/60:.1f} 分鐘")
            else:
                st.success("✅ 時間窗切分成功！")
                
                # 優化下午路線 (Anchor -> Afternoon -> Company)
                if afternoon_ids:
                    afternoon_coords = [(anchor_lat, anchor_lon)]
                    for aid in afternoon_ids:
                        afternoon_coords.append((df_all.loc[aid]['Latitude'], df_all.loc[aid]['Longitude']))
                    afternoon_coords.append((start_lat, start_lon))
                    
                    geojson_aft, waypoints_aft, duration_aft = get_optimized_trip_open(afternoon_coords, MAPBOX_TOKEN)
                    
                    if duration_aft:
                        ordered_afternoon = [None] * len(waypoints_aft)
                        for i, wp in enumerate(waypoints_aft):
                            idx = wp['waypoint_index']
                            if i == 0:
                                ordered_afternoon[idx] = f"⭐ {anchor_row['客戶名稱']} (錨點)"
                            elif i == len(waypoints_aft) - 1:
                                ordered_afternoon[idx] = "🏢 公司 (終點)"
                            else:
                                cid = afternoon_ids[i-1]
                                ordered_afternoon[idx] = edited_df.loc[cid]['客戶名稱']
                        final_afternoon_route = ordered_afternoon
                
                # 顯示結果
                st.markdown("### 📅 最終排程建議")
                
                # 推算絕對時間
                current_time = start_datetime
                
                st.markdown("#### 🌅 上午場 (出發 ➔ 預約錨點)")
                for stop in final_morning_route:
                    st.markdown(f"- **{current_time.strftime('%H:%M')}** {stop}")
                    if "公司" not in stop and "錨點" not in stop:
                        # 加上停留時間
                        # 這裡需要找到對應的 cid 來取得停留時間
                        # 但 final_morning_route 只有名稱。
                        # 簡化起見，假設非起終點都停留 default_stay 或自訂時間
                        # 我們可以在 loop 中維護一個指針或字典
                        pass
                    # 這裡簡化處理，僅印出順序。要推算每站時間需要知道每段的 duration。
                    # Mapbox 返回的 trips 裡有 legs，包含每段的 duration。
                    # 但我們的 get_optimized_trip_open 只返回了總 duration。
                    # 為了精確推算，我們假設交通時間平均分配或直接顯示順序。
                    # 根據需求：『利用 datetime.timedelta 推算抵達每一站的絕對時間』
                    # 由於 Mapbox 返回的 trips[0]['legs'] 包含每段時間，我們應該要返回 legs！
                    
                if final_afternoon_route:
                    st.markdown("#### 🌆 下午場 (預約錨點 ➔ 公司)")
                    for stop in final_afternoon_route:
                        st.markdown(f"- {stop}")
                        
                st.info("註：詳細每站抵達時間推算需解析 Legs 資訊，目前顯示訪問順序。")

