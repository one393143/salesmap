import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from haversine import haversine, Unit
import numpy as np
from utils import geocode_single_address, get_optimized_trip, generate_gmaps_url, MAPBOX_TOKEN

st.set_page_config(page_title="空間探索", layout="wide")

st.title("🗺️ 空間探索")
st.markdown("進行半徑過濾與地圖路線規劃。")

if 'geocoded_df' not in st.session_state:
    st.info("👈 請先至「資料管理」頁面載入並轉換資料。")
else:
    df_valid = st.session_state['geocoded_df'].dropna(subset=['Latitude', 'Longitude'])
    
    if df_valid.empty:
        st.warning("⚠️ 沒有具備有效經緯度的客戶資料，請先至「資料管理」進行地理編碼。")
    else:
        # 步驟 4: 空間半徑過濾
        st.sidebar.write("### 🎯 空間半徑過濾")
        
        name_cols = [col for col in df_valid.columns if '名稱' in col or 'name' in col.lower()]
        name_col = name_cols[0] if name_cols else df_valid.columns[0]
        
        anchor_options = [f"{idx} - {row[name_col]}" for idx, row in df_valid.iterrows()]
        
        if anchor_options:
            selected_anchor = st.sidebar.selectbox("📍 選擇錨點客戶", anchor_options)
            
            def on_radius_change():
                st.session_state['run_recommendation'] = False
                
            radius_km = st.sidebar.slider("📏 搜尋半徑 (公里)", min_value=1, max_value=50, value=5, step=1, key="radius_slider", on_change=on_radius_change)
            
            if st.sidebar.button("🔍 繪製半徑過濾地圖", use_container_width=True):
                st.session_state['show_map'] = True
                st.session_state['filter_mode'] = True
                st.session_state['anchor_idx'] = int(selected_anchor.split(" - ")[0])
                st.session_state['radius_km'] = radius_km
                st.session_state['run_recommendation'] = False
                
        # 步驟 5: 智慧路線推薦
        if st.session_state.get('filter_mode', False) and 'anchor_idx' in st.session_state:
            st.sidebar.markdown("---")
            st.sidebar.write("### 🚗 智慧路線推薦")
            
            default_start_address = "台北市松山區南京東路五段202號"
            start_address_input = st.sidebar.text_input("出發與結束地址 (公司)", value=default_start_address)
            
            anchor_idx = st.session_state['anchor_idx']
            radius_km = st.session_state['radius_km']
            
            cand_options = []
            if anchor_idx in df_valid.index:
                anchor_row_tmp = df_valid.loc[anchor_idx]
                anchor_coords_tmp = (anchor_row_tmp['Latitude'], anchor_row_tmp['Longitude'])
                
                for idx, row in df_valid.iterrows():
                    coords = (row['Latitude'], row['Longitude'])
                    dist = haversine(anchor_coords_tmp, coords, unit=Unit.KILOMETERS)
                    if dist <= radius_km:
                        name = row[name_col] if pd.notna(row[name_col]) else f"客戶 {idx}"
                        cand_options.append(f"{idx} - {name}")
                        
            selected_candidates = st.sidebar.multiselect("選擇今日預計拜訪客戶 (至多 5 家)", cand_options)
            
            if len(selected_candidates) > 5:
                st.sidebar.warning("⚠️ 為確保拜訪品質，一日最多安排 5 家客戶")
                st.sidebar.button("💡 計算最佳拜訪路線", disabled=True)
            else:
                if st.sidebar.button("💡 計算最佳拜訪路線", use_container_width=True):
                    st.session_state['run_recommendation'] = True
                    st.session_state['compute_optimization'] = True
                    st.session_state['start_address_input'] = start_address_input
                    st.session_state['selected_candidates'] = [int(x.split(" - ")[0]) for x in selected_candidates]
                    if 'preview_route_geojson' in st.session_state:
                        del st.session_state['preview_route_geojson']
                    if 'route_bounds' in st.session_state:
                        del st.session_state['route_bounds']

        # 主畫面區塊
        if st.session_state.get('show_map', False):
            df_map = df_valid.copy()
            saved_target_col = st.session_state.get('target_col', '地址')
            
            anchor_row = None
            if st.session_state.get('filter_mode', False) and 'anchor_idx' in st.session_state:
                anchor_idx = st.session_state['anchor_idx']
                radius_km = st.session_state['radius_km']
                
                if anchor_idx in df_map.index:
                    anchor_row = df_map.loc[anchor_idx]
                    anchor_coords = (anchor_row['Latitude'], anchor_row['Longitude'])
                    
                    distances = []
                    for idx, row in df_map.iterrows():
                        coords = (row['Latitude'], row['Longitude'])
                        dist = haversine(anchor_coords, coords, unit=Unit.KILOMETERS)
                        distances.append(dist)
                        
                    df_map['Distance'] = distances
                    df_map = df_map[df_map['Distance'] <= radius_km]
                    
            # 智慧路線推薦邏輯
            if st.session_state.get('run_recommendation', False):
                st.write("### 💡 最佳拜訪順序推薦")
                
                if st.session_state.get('compute_optimization', False):
                    st.session_state['compute_optimization'] = False
                    
                    start_addr_str = st.session_state['start_address_input']
                    selected_ids = st.session_state.get('selected_candidates', [])
                    
                    if not selected_ids:
                        st.warning("請先在左側選擇至少 1 家預計拜訪的客戶！")
                        st.session_state['opt_ordered'] = None
                    else:
                        try:
                            with st.spinner("正在將公司地址轉為座標並規劃最佳路線..."):
                                start_lat, start_lon = geocode_single_address(start_addr_str, MAPBOX_TOKEN)
                                
                            if start_lat is None:
                                st.error(f"無法解析公司地址：{start_addr_str}，請確認地址是否正確。")
                                st.session_state['opt_ordered'] = None
                            else:
                                start_coords = (start_lat, start_lon)
                                
                                coords_list = [start_coords]
                                cust_names = ["🏢 公司 (起點)"]
                                cust_addrs = [start_addr_str]
                                
                                for cid in selected_ids:
                                    if cid in df_map.index:
                                        row = df_map.loc[cid]
                                        coords_list.append((row['Latitude'], row['Longitude']))
                                        cname = row[name_col] if pd.notna(row[name_col]) else f"客戶 {cid}"
                                        cust_names.append(cname)
                                        addr = row['清洗後地址'] if '清洗後地址' in row else str(row.get('原始地址', ''))
                                        cust_addrs.append(addr)
                                        
                                if len(coords_list) > 1:
                                    with st.spinner("向 Mapbox Optimization API 請求最佳路徑..."):
                                        geojson, waypoints = get_optimized_trip(coords_list, MAPBOX_TOKEN)
                                        
                                    if geojson and waypoints:
                                        st.session_state['preview_route_geojson'] = geojson
                                        
                                        ordered = [None] * len(waypoints)
                                        ordered_addrs = [None] * len(waypoints)
                                        for i, wp in enumerate(waypoints):
                                            idx = wp['waypoint_index']
                                            ordered[idx] = cust_names[i]
                                            ordered_addrs[idx] = cust_addrs[i]
                                            
                                        ordered.append("🏢 公司 (終點)")
                                        ordered_addrs.append(start_addr_str)
                                        
                                        st.session_state['opt_ordered'] = ordered
                                        st.session_state['opt_ordered_addrs'] = ordered_addrs
                                        
                                        if geojson['type'] == 'LineString':
                                            route_coords = geojson['coordinates']
                                            sw = [min(c[1] for c in route_coords), min(c[0] for c in route_coords)]
                                            ne = [max(c[1] for c in route_coords), max(c[0] for c in route_coords)]
                                            st.session_state['route_bounds'] = [sw, ne]
                                    else:
                                        st.error("規劃路線失敗，請確認網路與 API 額度。")
                                        st.session_state['opt_ordered'] = None
                        except Exception as e:
                            st.error(f"規劃路線時發生未預期錯誤: {e}")
                            st.session_state['opt_ordered'] = None

                if st.session_state.get('opt_ordered'):
                    ordered = st.session_state['opt_ordered']
                    ordered_addrs = st.session_state['opt_ordered_addrs']
                    
                    st.success("✅ 路線規劃完成！最佳順序如下：")
                    st.markdown(" ➔ ".join(ordered))
                    
                    st.sidebar.success("✅ **最佳順序**")
                    for i, name in enumerate(ordered):
                        st.sidebar.text(f"{i}. {name}")
                        
                    gmaps_url = generate_gmaps_url(ordered_addrs)
                    if gmaps_url:
                        st.markdown(f"### [🚀 開啟 Google Maps 手機導航]({gmaps_url})", unsafe_allow_html=True)

            if df_map.empty:
                st.warning("⚠️ 範圍內沒有可用的座標資料來繪製地圖。")
            else:
                with st.spinner("正在產生高流暢度的互動式地圖..."):
                    m = folium.Map(location=[23.5, 121.0], zoom_start=7, tiles='CartoDB positron')
                    
                    if anchor_row is not None:
                        folium.Circle(
                            location=[anchor_row['Latitude'], anchor_row['Longitude']],
                            radius=radius_km * 1000,
                            color='gray',
                            fill=True,
                            fill_opacity=0.2,
                            interactive=False
                        ).add_to(m)
                    
                    marker_cluster = MarkerCluster(
                        maxClusterRadius=40, 
                        disableClusteringAtZoom=15,
                        spiderfyOnMaxZoom=False
                    ).add_to(m)
                    
                    if st.session_state.get('preview_route_geojson'):
                        folium.GeoJson(
                            st.session_state['preview_route_geojson'],
                            name="推薦路線預覽",
                            style_function=lambda x: {
                                'color': '#ff5a5f',
                                'weight': 6,
                                'opacity': 0.8
                            }
                        ).add_to(m)
                    
                    if st.session_state.get('run_recommendation') and 'route_bounds' in st.session_state:
                        m.fit_bounds(st.session_state['route_bounds'])
                    else:
                        sw = df_map[['Latitude', 'Longitude']].min().values.tolist()
                        ne = df_map[['Latitude', 'Longitude']].max().values.tolist()
                        if sw == ne:
                            m.fit_bounds([sw, ne], max_zoom=14)
                        else:
                            m.fit_bounds([sw, ne])
                    
                    grouped = df_map.groupby(['Latitude', 'Longitude'])
                    
                    for (lat, lon), group in grouped:
                        tooltip_names = []
                        popup_sections = []
                        
                        for idx, row in group.iterrows():
                            customer_name = row[name_col] if name_col and pd.notna(row[name_col]) else f"客戶 {idx}"
                            original_addr = row[saved_target_col] if saved_target_col in row else ""
                            cleaned_addr = row['清洗後地址'] if '清洗後地址' in row else ""
                            
                            is_anchor = (anchor_row is not None and idx == anchor_row.name)
                            if is_anchor:
                                tooltip_names.insert(0, f"⭐ {customer_name} (錨點)")
                                popup_sections.insert(0, f"<b>【錨點客戶】</b><br><b>名稱:</b> {customer_name}<br><b>原始地址:</b> {original_addr}<br><b>清洗後地址:</b> {cleaned_addr}")
                            else:
                                tooltip_names.append(str(customer_name))
                                dist_str = f"<br><b>距離:</b> {row['Distance']:.2f} km" if 'Distance' in row else ""
                                popup_sections.append(f"<b>名稱:</b> {customer_name}<br><b>原始地址:</b> {original_addr}<br><b>清洗後地址:</b> {cleaned_addr}{dist_str}")
                                
                        final_tooltip = " | ".join(tooltip_names)
                        final_popup_html = "<hr>".join(popup_sections)
                        
                        is_anchor_group = any(anchor_row is not None and idx == anchor_row.name for idx, _ in group.iterrows())
                        
                        if is_anchor_group:
                            folium.CircleMarker(
                                location=[lat, lon],
                                radius=8,
                                color='red',
                                fill=True,
                                fill_color='red',
                                tooltip=final_tooltip,
                                popup=folium.Popup(final_popup_html, max_width=350),
                                z_index_offset=1000
                            ).add_to(m)
                        else:
                            folium.CircleMarker(
                                location=[lat, lon],
                                radius=6,
                                color='#3186cc',
                                fill=True,
                                fill_color='#3186cc',
                                tooltip=final_tooltip,
                                popup=folium.Popup(final_popup_html, max_width=350)
                            ).add_to(marker_cluster)
                    
                    st_folium(m, use_container_width=True, height=700)
