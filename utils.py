import streamlit as st
import pandas as pd
import re
import os
import requests
import time
import numpy as np
from dotenv import load_dotenv
import urllib.parse

# 載入環境變數
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(dotenv_path=env_path, override=True)
MAPBOX_TOKEN = os.getenv("MAPBOX_API_KEY")

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

@st.cache_data(ttl=86400)
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

def batch_geocode(df, address_col, use_api=False):
    """批次轉換地址為經緯度，利用 st.cache_data 進行快取"""
    if 'Latitude' not in df.columns:
        df['Latitude'] = np.nan
    if 'Longitude' not in df.columns:
        df['Longitude'] = np.nan
        
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(df)
    for i, row in df.iterrows():
        address = row[address_col]
        
        if isinstance(address, str) and address.strip():
            # 直接呼叫 geocode_address，由 Streamlit 處理快取
            lat, lon = geocode_address(address)
            df.at[i, 'Latitude'] = lat
            df.at[i, 'Longitude'] = lon
            
        if i % 5 == 0 or i == total - 1:
            progress_bar.progress((i + 1) / total)
            status_text.text(f"轉換進度：{i + 1} / {total}")
            
    status_text.text("轉換完成！")
    return df

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

def generate_gmaps_url(ordered_address_list):
    if len(ordered_address_list) < 2: return ""
    origin = urllib.parse.quote(str(ordered_address_list[0]))
    destination = urllib.parse.quote(str(ordered_address_list[-1]))
    waypoints = ""
    if len(ordered_address_list) > 2:
        waypoints = "&waypoints=" + urllib.parse.quote("|".join([str(addr) for addr in ordered_address_list[1:-1]]))
    return f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}{waypoints}"
