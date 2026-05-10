import pandas as pd
import re

def clean_taiwan_address(address):
    if pd.isna(address) or not isinstance(address, str):
        return address
    addr = re.sub(r'\(.*?\)|（.*?）|\[.*?\]|【.*?】', '', address)
    addr = re.sub(r'[a-eA-Eg-zG-Z]', '', addr)
    addr = addr.strip()
    match = re.search(r'(.*?號)(?:.*?)(之\s*\d+)?', addr)
    if match:
        base = match.group(1).strip()
        sub_num = match.group(2).strip() if match.group(2) else ""
        base = re.split(r'樓|F|f|室', base)[0]
        return base + sub_num
    else:
        addr = re.split(r'樓|F|f|室', addr)[0]
        return addr.strip()

df = pd.read_csv('客戶_供應商基本資料 Customer _ Supplier Master Data_20260510T160059+0800.csv')
addrs = df['發票地址'].dropna().head(20).tolist()
for a in addrs:
    print(f"Original: {a}")
    print(f"Cleaned : {clean_taiwan_address(a)}")
    print("-" * 30)
