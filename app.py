import streamlit as st
import pandas as pd
import re
import os
import requests
import time
import numpy as np
from dotenv import load_dotenv
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from haversine import haversine, Unit
import itertools
from datetime import datetime, time, timedelta

# 載入環境變數 (加上明確路徑與 override，確保 Streamlit 能熱重載)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path, override=True)
MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY")

def geocode_single_address(address, token):
    if not address or not token: return None, None
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{address}.json"
    params = {'access_token': token, 'country': 'TW', 'limit': 1}
    try:
        res = requests.get(url, params=params).json()
        if 'features' in res and len(res['features']) > 0:
            lon, lat = res['features'][0]['geometry']['coordinates']
            return lat, lon
    except:
        pass
    return None

def get_optimized_trip(coords_list, token):
    if len(coords_list) < 2 or not token: return None, None
    coords_str = ";".join([f"{lon},{lat}" for lat, lon in coords_list])
    url = f"https://api.mapbox.com/optimized-trips/v1/mapbox/driving/{coords_str}"
    params = {
        'roundtrip': 'true',
        'source': 'first',
        'geometries': 'geojson',
        'access_token': token
    }
    try:
        res = requests.get(url, params=params).json()
        if 'trips' in res and len(res['trips']) > 0:
            return res['trips'][0]['geometry'], res['waypoints']
    except Exception as e:
        print(e)
    return None, None

import urllib.parse

def generate_gmaps_url(ordered_address_list):
    if len(ordered_address_list) < 2: return ""
    origin = urllib.parse.quote(str(ordered_address_list[0]))
    destination = urllib.parse.quote(str(ordered_address_list[-1]))
    waypoints = ""
    if len(ordered_address_list) > 2:
        waypoints = "&waypoints=" + urllib.parse.quote("|".join([str(addr) for addr in ordered_address_list[1:-1]]))
    return f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}{waypoints}"


def clean_taiwan_address(address):
    """
    清洗台灣地址的函數
    1. 移除括號及其內容
    2. 移除英文字母
    3. 保留到「號」或「之 X」，捨棄樓層資訊
    """
    if pd.isna(address) or not isinstance(address, str):
        return address
        
    # 0. 判斷是否為國外地址 (如果含有超過 10 個英文字母，直接保留原樣)
    if len(re.findall(r'[A-Za-z]', address)) > 10:
        return address.strip()

    # 1. 移除括號及其內容 (全形與半形)
    addr = re.sub(r'\(.*?\)|（.*?）|\[.*?\]|【.*?】', '', address)
    
    # 移除英文字母 (保留 F/f 作為後續判斷樓層用)
    addr = re.sub(r'[a-eA-Eg-zG-Z]', '', addr)
    
    # 2. 清理多餘空白
    addr = addr.strip()
    
    # 3. 提取到「號」以及可能的「之 X」
    # 先抓取開頭到「號」為止
    match_hao = re.search(r'^(.*?號)', addr)
    if match_hao:
        base = match_hao.group(1).strip()
        # 確保 base 裡面沒有混入奇怪的樓層字眼
        base = re.split(r'樓|F|f|室', base)[0]
        
        # 接著看「號」後面的字串，是否包含「之 X」
        after_hao = addr[match_hao.end():]
        match_zhi = re.search(r'(之\s*\d+)', after_hao)
        if match_zhi:
            sub_num = match_zhi.group(1).strip()
            return base + sub_num
        else:
            return base
    else:
        # 如果沒有「號」，則截斷「樓/F/室」後面的字串
        addr = re.split(r'樓|F|f|室', addr)[0]
        return addr.strip()

def geocode_address(address):
    """呼叫 Mapbox API 取得經緯度"""
    if not isinstance(address, str) or not address.strip():
        return np.nan, np.nan
        
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{address}.json"
    params = {
        "access_token": MAPBOX_TOKEN,
        "country": "tw", # 限制台灣
        "limit": 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('features'):
                coords = data['features'][0]['center']
                return coords[1], coords[0] # 返回 [緯度, 經度]
    except Exception as e:
        print(f"API 發生錯誤: {e}")
        
    return np.nan, np.nan

def batch_geocode(df, address_col, cache_file="geocoded_cache.csv", use_api=False):
    """批次轉換地址為經緯度，並實作快取機制"""
    if 'Latitude' not in df.columns:
        df['Latitude'] = np.nan
    if 'Longitude' not in df.columns:
        df['Longitude'] = np.nan
        
    # 讀取快取 (包含曾經失敗被標記為 NaN 的紀錄)
    cache_dict = {}
    if os.path.exists(cache_file):
        try:
            cache_df = pd.read_csv(cache_file)
            # 確保 Address 唯一，否則 to_dict('index') 會失敗引發 ValueError
            cache_df = cache_df.drop_duplicates(subset=['Address'], keep='last')
            cache_dict = cache_df.set_index('Address').to_dict('index')
        except Exception as e:
            print(f"載入快取失敗: {e}")
            
    new_cache_entries = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(df)
    for i, row in df.iterrows():
        address = row[address_col]
        
        if isinstance(address, str) and address.strip():
            # 1. 比對快取
            if address in cache_dict:
                df.at[i, 'Latitude'] = cache_dict[address]['Latitude']
                df.at[i, 'Longitude'] = cache_dict[address]['Longitude']
            elif use_api:
                # 2. 如果允許呼叫 API 且快取沒有這筆資料
                lat, lon = geocode_address(address)
                df.at[i, 'Latitude'] = lat
                df.at[i, 'Longitude'] = lon
                
                # 3. 存入快取列表 (即使失敗也存入 NaN，避免下次又重複查)
                new_cache_entries.append({'Address': address, 'Latitude': lat, 'Longitude': lon})
                
                # 避免超過 API 速率限制
                time.sleep(0.05)
        
        # 更新進度條
        if i % 5 == 0 or i == total - 1:
            progress_bar.progress((i + 1) / total)
            status_text.text(f"轉換進度：{i + 1} / {total}")
            
    # 寫入新的快取資料
    if new_cache_entries:
        new_cache_df = pd.DataFrame(new_cache_entries)
        if os.path.exists(cache_file):
            new_cache_df.to_csv(cache_file, mode='a', header=False, index=False)
        else:
            new_cache_df.to_csv(cache_file, index=False)
            
    status_text.text("轉換完成！")
    return df

# ----- Streamlit 介面 -----
st.set_page_config(page_title="企業地圖系統", layout="wide", initial_sidebar_state="expanded")

# ----------------------------------------
# 側邊欄 (Sidebar) - 控制面板
# ----------------------------------------
st.sidebar.title("🛠️ 控制面板")
st.sidebar.markdown("""
- **階段一：** 資料清洗與標準化
- **階段二：** Mapbox 地理編碼
- **階段三：** 互動式地圖繪製
- **階段四：** 空間半徑過濾
""")

if not MAPBOX_TOKEN:
    st.sidebar.error("⚠️ 未設定 MAPBOX_API_KEY！")

try:
    uploaded_file = st.sidebar.file_uploader("📤 上傳客戶資料 (CSV)", type=["csv"])
    
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
        st.sidebar.success("已成功讀取上傳資料！")
        
        # 自動尋找可能是地址的欄位 (address 或 地址)
        address_cols = [col for col in df.columns if any(k in str(col).lower() for k in ['地址', 'address', 'addr'])]
        target_col = st.sidebar.selectbox(
            "📍 選擇地址欄位", 
            df.columns, 
            index=df.columns.get_loc(address_cols[0]) if address_cols else 0
        )
        
        st.sidebar.markdown("---")
        
        # 步驟 1
        if st.sidebar.button("🚀 1. 開始清洗資料", use_container_width=True):
            with st.spinner("資料清洗中..."):
                df['清洗後地址'] = df[target_col].apply(clean_taiwan_address)
                st.session_state['cleaned_df'] = df
                st.session_state['target_col'] = target_col
                st.session_state['show_map'] = False # 重置地圖視角
            st.sidebar.success("清洗完成！")

    # 步驟 2
    if 'cleaned_df' in st.session_state:
        st.sidebar.markdown("---")
        st.sidebar.write("### 📍 2. 地理編碼")
        
        load_cache_btn = st.sidebar.button("📥 載入本地快取 (不耗 API)", use_container_width=True)
        force_recalc_btn = st.sidebar.button("🔄 API 轉換未解析地址", use_container_width=True)

        if load_cache_btn or force_recalc_btn:
            if force_recalc_btn and not MAPBOX_TOKEN:
                st.sidebar.error("請先設定 API Key！")
            else:
                use_api = force_recalc_btn
                msg = "查詢經緯度中..." if use_api else "載入快取中..."
                
                with st.spinner(msg):
                    df_to_geocode = st.session_state['cleaned_df']
                    geocoded_df = batch_geocode(df_to_geocode, '清洗後地址', use_api=use_api)
                    st.session_state['geocoded_df'] = geocoded_df
                    st.session_state['show_map'] = False # 重置地圖視角
                
                st.sidebar.success("地理編碼完成！")

    # 步驟 3
    if 'geocoded_df' in st.session_state:
        st.sidebar.markdown("---")
        if st.sidebar.button("🗺️ 3. 繪製全台客戶分佈", use_container_width=True, type="primary"):
            st.session_state['show_map'] = True
            st.session_state['filter_mode'] = False

    # 步驟 4
    if 'geocoded_df' in st.session_state:
        st.sidebar.markdown("---")
        st.sidebar.write("### 🎯 4. 空間半徑過濾")
        
        df_valid = st.session_state['geocoded_df'].dropna(subset=['Latitude', 'Longitude'])
        name_cols = [col for col in df_valid.columns if '名稱' in col or 'name' in col.lower()]
        name_col = name_cols[0] if name_cols else df_valid.columns[0]
        
        # 建立選項: index - 客戶名稱 (方便反查)
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
                
    # 步驟 5
    if st.session_state.get('filter_mode', False) and 'anchor_idx' in st.session_state:
        st.sidebar.markdown("---")
        st.sidebar.write("### 🚗 5. 智慧路線推薦")
        
        default_start_address = "台北市松山區南京東路五段202號"
        start_address_input = st.sidebar.text_input("出發與結束地址 (公司)", value=default_start_address)
        
        # 取得目前過濾範圍內的客戶
        df_valid = st.session_state['geocoded_df'].dropna(subset=['Latitude', 'Longitude']).copy()
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
                    name_cols = [col for col in df_valid.columns if '名稱' in col or 'name' in col.lower()]
                    name_col = name_cols[0] if name_cols else df_valid.columns[0]
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


    # ----------------------------------------
    # 主畫面區塊 (Main Area)
    # ----------------------------------------
    st.title("🗺️ 企業客戶分佈地圖")
    
    # 狀態 3: 顯示地圖
    if st.session_state.get('show_map', False):
        df_map = st.session_state['geocoded_df'].dropna(subset=['Latitude', 'Longitude']).copy()
        saved_target_col = st.session_state.get('target_col', target_col)
        
        # 若為過濾模式，執行空間半徑過濾
        anchor_row = None
        if st.session_state.get('filter_mode', False) and 'anchor_idx' in st.session_state:
            anchor_idx = st.session_state['anchor_idx']
            radius_km = st.session_state['radius_km']
            
            if anchor_idx in df_map.index:
                anchor_row = df_map.loc[anchor_idx]
                anchor_coords = (anchor_row['Latitude'], anchor_row['Longitude'])
                
                # 計算與錨點的距離
                distances = []
                for idx, row in df_map.iterrows():
                    coords = (row['Latitude'], row['Longitude'])
                    dist = haversine(anchor_coords, coords, unit=Unit.KILOMETERS)
                    distances.append(dist)
                    
                df_map['Distance'] = distances
                
                # 過濾出小於半徑的點
                df_map = df_map[df_map['Distance'] <= radius_km]
                
        # --- 智慧路線推薦邏輯 ---
        if st.session_state.get('run_recommendation', False):
            st.write("### 💡 最佳拜訪順序推薦")
            
            # 若按下了計算按鈕，才觸發 API 呼叫，並將結果存入 session_state
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
                            
                            name_cols = [col for col in df_map.columns if '名稱' in col or 'name' in col.lower()]
                            name_col = name_cols[0] if name_cols else df_map.columns[0]
                            
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

            # 若已有最佳化結果，將其渲染至畫面上
            if st.session_state.get('opt_ordered'):
                ordered = st.session_state['opt_ordered']
                ordered_addrs = st.session_state['opt_ordered_addrs']
                
                st.success("✅ 路線規劃完成！最佳順序如下：")
                st.markdown(" ➔ ".join(ordered))
                
                st.sidebar.success("✅ **最佳順序**")
                for i, name in enumerate(ordered):
                    st.sidebar.text(f"{i}. {name}")
                    
                # Google Maps 導航 URL
                gmaps_url = generate_gmaps_url(ordered_addrs)
                if gmaps_url:
                    st.markdown(f"### [🚀 開啟 Google Maps 手機導航]({gmaps_url})", unsafe_allow_html=True)
                    
        # --- 推薦邏輯結束 ---
        
        if df_map.empty:
            st.warning("⚠️ 範圍內沒有可用的座標資料來繪製地圖。")
        else:
            with st.spinner("正在產生高流暢度的互動式地圖..."):
                # 使用 CartoDB positron 讓底圖更乾淨專業
                m = folium.Map(location=[23.5, 121.0], zoom_start=7, tiles='CartoDB positron')
                
                # 如果有錨點，必須「最先」畫出半徑輔助圓，確保它的 SVG z-index 在最底層，才不會遮擋圖釘！
                if anchor_row is not None:
                    folium.Circle(
                        location=[anchor_row['Latitude'], anchor_row['Longitude']],
                        radius=radius_km * 1000, # 轉換為公尺
                        color='gray',
                        fill=True,
                        fill_opacity=0.2,
                        interactive=False # 重要：讓點擊事件可以穿透
                    ).add_to(m)
                
                # 建立 MarkerCluster (關閉 spiderfy 蜘蛛網展開，確保標記在精確的 GPS 位置上)
                marker_cluster = MarkerCluster(
                    maxClusterRadius=40, 
                    disableClusteringAtZoom=15,
                    spiderfyOnMaxZoom=False
                ).add_to(m)
                
                # 如果有預覽路線，將其畫在地圖上
                if st.session_state.get('preview_route_geojson'):
                    folium.GeoJson(
                        st.session_state['preview_route_geojson'],
                        name="推薦路線預覽",
                        style_function=lambda x: {
                            'color': '#ff5a5f', # 顯眼的紅橘色
                            'weight': 6,
                            'opacity': 0.8
                        }
                    ).add_to(m)
                
                # 抓取視窗自動縮放邊界 Bounds
                if st.session_state.get('run_recommendation') and 'route_bounds' in st.session_state:
                    m.fit_bounds(st.session_state['route_bounds'])
                else:
                    sw = df_map[['Latitude', 'Longitude']].min().values.tolist()
                    ne = df_map[['Latitude', 'Longitude']].max().values.tolist()
                    if sw == ne:
                        m.fit_bounds([sw, ne], max_zoom=14)
                    else:
                        m.fit_bounds([sw, ne])
                
                # 嘗試抓取客戶名稱的欄位
                name_cols = [col for col in df_map.columns if '名稱' in col or 'name' in col.lower()]
                name_col = name_cols[0] if name_cols else None
                
                # 將具有相同座標的客戶進行合併處理
                # 這樣能保證座標 100% 準確 (不使用蜘蛛網分散)，且能同時看到同大樓的多筆客戶
                grouped = df_map.groupby(['Latitude', 'Longitude'])
                
                for (lat, lon), group in grouped:
                    has_anchor = False
                    tooltip_names = []
                    popup_sections = []
                    
                    for idx, row in group.iterrows():
                        customer_name = row[name_col] if name_col and pd.notna(row[name_col]) else f"客戶 {idx}"
                        original_addr = row[saved_target_col]
                        cleaned_addr = row['清洗後地址']
                        
                        is_anchor = (anchor_row is not None and idx == anchor_row.name)
                        if is_anchor:
                            has_anchor = True
                            tooltip_names.insert(0, f"⭐ {customer_name} (錨點)")
                            popup_sections.insert(0, f"<b>【錨點客戶】</b><br><b>名稱:</b> {customer_name}<br><b>原始地址:</b> {original_addr}<br><b>清洗後地址:</b> {cleaned_addr}")
                        else:
                            tooltip_names.append(str(customer_name))
                            dist_str = f"<br><b>距離:</b> {row['Distance']:.2f} km" if 'Distance' in row else ""
                            popup_sections.append(f"<b>名稱:</b> {customer_name}<br><b>原始地址:</b> {original_addr}<br><b>清洗後地址:</b> {cleaned_addr}{dist_str}")
                    
                    # 組合多筆客戶的顯示資訊
                    final_tooltip = " / ".join(tooltip_names)
                    if len(group) > 1:
                        final_tooltip = f"({len(group)}家客戶) " + final_tooltip
                        
                    final_popup_html = "<hr>".join(popup_sections)
                    
                    if has_anchor:
                        folium.Marker(
                            location=[lat, lon],
                            icon=folium.Icon(color='red', icon='star'),
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
                
            st.success("地圖繪製完成！您可以隨意縮放或點擊圖釘。")
            st_data = st_folium(m, use_container_width=True, height=700)
            
    # 狀態 2: 顯示地理編碼結果
    elif 'geocoded_df' in st.session_state:
        geocoded_df = st.session_state['geocoded_df']
        saved_target_col = st.session_state.get('target_col', target_col)
        
        st.write("### 🌍 座標轉換結果")
        failed_df = geocoded_df[geocoded_df['Latitude'].isna()]
        if not failed_df.empty:
            st.warning(f"⚠️ 發現 {len(failed_df)} 筆無法解析的地址：")
            st.dataframe(failed_df[[saved_target_col, '清洗後地址', 'Latitude', 'Longitude']])
        else:
            st.success("🎉 所有地址皆具備經緯度！")
            
        st.dataframe(geocoded_df[[saved_target_col, '清洗後地址', 'Latitude', 'Longitude']], use_container_width=True)
        
        csv_data = geocoded_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載完整資料 (CSV)", data=csv_data, file_name='geocoded_customers.csv', mime='text/csv')

    # 狀態 1: 顯示清洗結果
    elif 'cleaned_df' in st.session_state:
        cleaned_df = st.session_state['cleaned_df']
        saved_target_col = st.session_state.get('target_col', target_col)
        
        st.write("### ✨ 清洗前後對比 (預覽)")
        st.dataframe(cleaned_df[[saved_target_col, '清洗後地址']], use_container_width=True)
        
    else:
        st.info("👈 請從左側控制面板開始操作，第一步先進行「資料清洗」。")
        
except Exception as e:
    st.error(f"發生錯誤: {e}")
