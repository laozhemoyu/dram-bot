# main.py
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
# 🔑 从 GitHub 环境变量读取配置 (安全！)
# ==========================================
# 后面会在 GitHub 网页上设置这两个变量
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")

def send_dingtalk_markdown(title, content):
    """发送消息到钉钉"""
    if not WEBHOOK or not SECRET:
        print("❌ 错误: 未检测到钉钉配置，请在 GitHub Secrets 中设置！")
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
        requests.post(url, headers=headers, json=data, timeout=10)
        print("✅ 推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def generate_report(data_list):
    """生成漂亮的卡片报告"""
    if not data_list: return "暂无数据"
    
    # 解析数据
    parsed = []
    for item in data_list:
        try:
            parts = item.split("|")
            # 提取涨跌数值用于排序
            val_str = parts[2].replace("涨跌:", "").replace("%", "").strip()
            val = float(val_str) if val_str not in ["", "-"] else 0
            parsed.append({"raw": item, "val": val})
        except: continue

    # 排序：涨的在前，跌的在后
    up = sorted([x for x in parsed if x['val'] > 0], key=lambda x: x['val'], reverse=True)
    down = sorted([x for x in parsed if x['val'] < 0], key=lambda x: x['val'])
    flat = [x for x in parsed if x['val'] == 0]

    lines = [f"## 📊 DRAM 行情 (GitHub云端)", f"> 更新: {time.strftime('%H:%M')}", "---"]
    
    # 辅助显示函数
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
        for x in flat[:10]: # 只显示前10个防止太长
            parts = x['raw'].split("|")
            lines.append(f"- {parts[0].strip()}")
            
    return "\n".join(lines)

def scrape_data():
    """Chrome 爬虫引擎"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # GitHub Actions 自带 Chrome 和 Driver，无需指定路径
    driver = webdriver.Chrome(options=options)
    
    try:
        print("🌐 访问 TrendForce...")
        driver.get("https://www.trendforce.cn/price")
        time.sleep(5)
        
        # 尝试点击 DRAM
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'DRAM')]")))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except: pass
        
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
        print(f"Error: {e}")
        return []
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 云端爬虫启动...")
    data = scrape_data()
    if data:
        print(f"✅ 抓取到 {len(data)} 条数据")
        report = generate_report(data)
        send_dingtalk_markdown("DRAM日报", report)
    else:
        print("❌ 未抓取到数据")