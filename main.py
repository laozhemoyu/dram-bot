import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# ==========================================
# 🔑 环境变量
# ==========================================
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")

def generate_dos_report(data_list):
    """
    💻 生成 DOS/Terminal 风格的字符报告
    """
    if not data_list: return "NO DATA"

    # 1. 数据清洗与分类
    parsed = []
    for item in data_list:
        try:
            # item 格式: [名, 日高, 日低, 盘高, 盘低, 均价, 涨跌]
            name = item[0].replace("DDR", "D") # 缩写
            price = item[5]
            change_str = item[6]
            
            # 提取数值用于排序
            val_clean = change_str.replace("涨跌:", "").replace("%", "").strip()
            val = float(val_clean) if val_clean not in ["", "-"] else 0
            
            parsed.append({
                "name": name, 
                "price": price, 
                "change_str": change_str, 
                "val": val
            })
        except: continue

    # 排序
    up = sorted([x for x in parsed if x['val'] > 0], key=lambda x: x['val'], reverse=True)
    down = sorted([x for x in parsed if x['val'] < 0], key=lambda x: x['val'])
    flat = [x for x in parsed if x['val'] == 0]

    # 2. 绘制 DOS 界面
    # 定义宽度
    W = 38 
    lines = []
    
    # --- Header ---
    lines.append("=" * W)
    lines.append(f" DRAM MONITOR SYSTEM       {time.strftime('%H:%M')}")
    lines.append("=" * W)
    
    # --- Dashboard ---
    total = len(parsed)
    sentiment = "NEUTRAL"
    if len(up) > len(down): sentiment = "BULLISH (UP)"
    elif len(down) > len(up): sentiment = "BEARISH (DOWN)"
    
    lines.append(f" STATUS: {sentiment}")
    lines.append(f" TOTAL : {total:<4} | UP:{len(up):<2} DOWN:{len(down):<2} FLAT:{len(flat):<2}")
    lines.append("-" * W)

    # --- Section: RISING ---
    if up:
        lines.append(f" [▲ RISING]             Target: {len(up)}")
        for i, item in enumerate(up):
            # 格式:  +3.2% | D5 16G (2Gx8)...
            # 截断过长的名字
            name_display = item['name']
            if len(name_display) > 22: name_display = name_display[:20] + ".."
            
            lines.append(f" {item['change_str']:>7} | {name_display}")
            lines.append(f"           | $ {item['price']}")
        lines.append("-" * W)

    # --- Section: FALLING ---
    if down:
        lines.append(f" [▼ FALLING]            Target: {len(down)}")
        for item in down:
            name_display = item['name']
            if len(name_display) > 22: name_display = name_display[:20] + ".."
            lines.append(f" {item['change_str']:>7} | {name_display}")
            lines.append(f"           | $ {item['price']}")
        lines.append("-" * W)

    # --- Section: FLAT ---
    if flat:
        lines.append(f" [= FLAT]               Target: {len(flat)}")
        # 平盘只显示前5个，节省空间
        for item in flat[:5]:
            name_display = item['name']
            if len(name_display) > 22: name_display = name_display[:20] + ".."
            lines.append(f" {item['change_str']:>7} | {name_display}")
        if len(flat) > 5:
            lines.append(f"           ... {len(flat)-5} more")

    lines.append("=" * W)
    lines.append(" END OF REPORT")
    
    return "\n".join(lines)

def send_dingtalk_dos(report_text):
    """
    发送钉钉消息 (使用代码块包裹，实现等宽字体显示)
    """
    if not WEBHOOK or not SECRET: return

    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    
    # 关键点：把生成的文本放在 ``` ``` 代码块里
    # 这样在手机和电脑上都会以“等宽字体”显示，保证排版不乱
    content = f"### 📟 DRAM 实时终端\n\n```text\n{report_text}\n```"

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": "DRAM DOS Report", "text": content}}
    
    try:
        requests.post(url, headers=headers, json=data, timeout=15)
        print("✅ DOS 报告推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def scrape_data():
    """Chrome 爬虫"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    try:
        print("🌐 访问 TrendForce...")
        driver.get("https://www.trendforce.cn/price")
        time.sleep(5)
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'DRAM')]")))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except: pass
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        raw_rows = []
        rows = soup.select('table tbody tr') or soup.select('table tr')
        for row in rows:
            cols = row.find_all(['th', 'td'])
            if len(cols) < 7: continue
            p_name = cols[0].get_text(strip=True)
            if 'DDR' in p_name.upper():
                row_data = [
                    p_name,
                    cols[1].get_text(strip=True),
                    cols[2].get_text(strip=True),
                    cols[3].get_text(strip=True),
                    cols[4].get_text(strip=True),
                    cols[5].get_text(strip=True),
                    cols[6].get_text(strip=True)
                ]
                raw_rows.append(row_data)
        return raw_rows
    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 启动 DOS 模式任务...")
    data = scrape_data()
    if data:
        print(f"✅ 抓取到 {len(data)} 条数据")
        dos_report = generate_dos_report(data)
        print(dos_report) # 在日志里打印一遍看看效果
        send_dingtalk_dos(dos_report)
    else:
        print("❌ 未抓取到数据")
