import pandas as pd
import re

def clean_taiwan_address(address):
    if pd.isna(address) or not isinstance(address, str):
        return address
        
    # 判斷是否為國外地址 (英文超過 10 個字母)
    if len(re.findall(r'[A-Za-z]', address)) > 10:
        return address.strip()

    addr = re.sub(r'\(.*?\)|（.*?）|\[.*?\]|【.*?】', '', address)
    addr = re.sub(r'[a-eA-Eg-zG-Z]', '', addr)
    addr = addr.strip()
    
    match_hao = re.search(r'^(.*?號)', addr)
    if match_hao:
        base = match_hao.group(1).strip()
        base = re.split(r'樓|F|f|室', base)[0]
        
        after_hao = addr[match_hao.end():]
        match_zhi = re.search(r'(之\s*\d+)', after_hao)
        if match_zhi:
            sub_num = match_zhi.group(1).strip()
            return base + sub_num
        else:
            return base
    else:
        addr = re.split(r'樓|F|f|室', addr)[0]
        return addr.strip()

df = pd.read_csv('客戶_供應商基本資料 Customer _ Supplier Master Data_20260510T160059+0800.csv')
addrs = df['發票地址'].dropna().head(20).tolist()
for a in addrs:
    print(f"Original: {a}")
    print(f"Cleaned : {clean_taiwan_address(a)}")
    print("-" * 30)
