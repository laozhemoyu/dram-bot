# main.py (GitHub 云端专用版)
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options # 👈 改成了 Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# ==========================================
# 🔑 从 GitHub 环境变量读取配置
# ==========================================
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")

def send_dingtalk_markdown(title, content):
    """发送 Markdown 消息"""
    if not WEBHOOK or not SECRET:
        print("❌ 错误: 未读取到钉钉配置，请检查 GitHub Secrets！")
        return

    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"📨 推送响应: {resp.status_code}")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def generate_report(data_list):
    """生成漂亮的卡片报告"""
    if not data_list: return "暂无数据"
    
    parsed = []
    for item in data_list:
        try:
            parts = item.split("|")
            val_str = parts[2].replace("涨跌:", "").replace("%", "").strip()
            val = float(val_str) if val_str not in ["", "-"] else 0
            parsed.append({"raw": item, "val": val})
        except: continue

    # 排序：涨在前，跌在后
    up = sorted([x for x in parsed if x['val'] > 0], key=lambda x: x['val'], reverse=True)
    down = sorted([x for x in parsed if x['val'] < 0], key=lambda x: x['val'])
    flat = [x for x in parsed if x['val'] == 0]

    lines = [f"## 📊 DRAM 行情 (GitHub版)", f"> 时间: {time.strftime('%H:%M')}", "---"]
    
    def add_section(items, title, icon):
        if items:
            lines.append(f"### {icon} {title} ({len(items)})")
            for item in items:
                parts = item['raw'].split("|")
                name = parts[0].strip()
                price = parts[1].replace("均价:", "").strip()
                change = parts[2].replace("涨跌:", "").strip()
                lines.append(f"**{name}**\n- 💰 `{price}` ({change})\n")

    add_section(up, "领涨", "🔴")
    add_section(down, "领跌", "💚")
    
    if flat:
        lines.append(f"### ➖ 持平 ({len(flat)})")
        for x in flat:
            parts = x['raw'].split("|")
            lines.append(f"- {parts[0].strip()}")
            
    return "\n".join(lines)

def scrape_data():
    """Chrome 爬虫引擎 (适配 GitHub Linux 环境)"""
    print("🌐 正在启动 Chrome...")
    options = Options()
    options.add_argument("--headless=new") # 无头模式
    options.add_argument("--no-sandbox")   # Linux 必须参数
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    # 伪装 User-Agent
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # ❌ 注意：这里不需要指定 executable_path，GitHub 会自动处理
    driver = webdriver.Chrome(options=options)
    
    try:
        print("➡️ 访问 TrendForce...")
        driver.get("https://www.trendforce.cn/price")
        time.sleep(5)
        
        # 尝试点击 DRAM
        try:
            print("🖱️ 尝试点击按钮...")
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'DRAM')]")))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except: 
            print("⚠️ 按钮点击跳过")
        
        print("⏳ 解析数据...")
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        res = []
        for row in soup.select('table tbody tr') or soup.select('table tr'):
            cols = row.find_all(['th', 'td'])
            if len(cols) < 7: continue
            name = cols[0].get_text(strip=True)
            if 'DDR' in name.upper():
                try:
                    p = cols[5].get_text(strip=True)
                    c = cols[6].get_text(strip=True)
                    res.append(f"{name} | 均价:{p} | 涨跌:{c}")
                except: continue
        return res
    except Exception as e:
        print(f"❌ 错误详情: {e}")
        return []
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 脚本开始运行...")
    data = scrape_data()
    if data:
        print(f"✅ 抓取成功: {len(data)} 条")
        report = generate_report(data)
        send_dingtalk_markdown("DRAM日报", report)
    else:
        print("❌ 未抓取到数据")
