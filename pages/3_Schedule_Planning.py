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
                        # 也就是倒數第二個訪問點 (倒數第一個是錨點)
                        last_cust_input_idx = visit_order[len(legs)]
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
                st.markdown("### 📅 最終排程建議")
                
                # 1. 顯示上午場
                st.markdown("#### 🌅 上午場 (出發 ➔ 預約錨點)")
                current_time = start_datetime
                st.markdown(f"- **{current_time.strftime('%H:%M')}** 🏢 出發點 (公司)")
                
                for idx in range(len(final_morning_legs)):
                    leg = final_morning_legs[idx]
                    travel_time = leg['duration'] / 60
                    current_time += timedelta(minutes=travel_time)
                    
                    next_input_idx = final_morning_order[idx + 1]
                    if idx == len(final_morning_legs) - 1:
                        st.markdown(f"- **{current_time.strftime('%H:%M')}** 🏁 ⭐ {anchor_row['客戶名稱']} (錨點) [車程: {travel_time:.1f} 分]")
                    else:
                        cid = morning_ids[next_input_idx - 1]
                        cname = edited_df.loc[cid]['客戶名稱']
                        stay_time = int(edited_df.loc[cid]['客製停留時間(分鐘)'])
                        st.markdown(f"- **{current_time.strftime('%H:%M')}** 📍 {cname} [車程: {travel_time:.1f} 分]")
                        current_time += timedelta(minutes=stay_time)
                        st.markdown(f"  *(停留 {stay_time} 分鐘，預計 {current_time.strftime('%H:%M')} 離開)*")
                
                # 2. 顯示下午場
                if afternoon_ids:
                    st.markdown("---")
                    st.markdown("#### 🌆 下午場 (預約錨點 ➔ 公司)")
                    
                    # 加上錨點停留時間 (假設也是 default_stay)
                    anchor_stay = int(anchor_row['客製停留時間(分鐘)'])
                    current_time += timedelta(minutes=anchor_stay)
                    st.markdown(f"預計 **{current_time.strftime('%H:%M')}** 從錨點出發")
                    
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
                            current_time += timedelta(minutes=travel_time)
                            
                            next_input_idx = visit_order_aft[idx + 1]
                            if idx == len(legs_aft) - 1:
                                st.markdown(f"- **{current_time.strftime('%H:%M')}** 🏢 抵達公司 (終點) [車程: {travel_time:.1f} 分]")
                            else:
                                cid = afternoon_ids[next_input_idx - 1]
                                cname = edited_df.loc[cid]['客戶名稱']
                                stay_time = int(edited_df.loc[cid]['客製停留時間(分鐘)'])
                                st.markdown(f"- **{current_time.strftime('%H:%M')}** 📍 {cname} [車程: {travel_time:.1f} 分]")
                                current_time += timedelta(minutes=stay_time)
                                st.markdown(f"  *(停留 {stay_time} 分鐘，預計 {current_time.strftime('%H:%M')} 離開)*")
                    else:
                        st.error("呼叫 Mapbox API 失敗！")

