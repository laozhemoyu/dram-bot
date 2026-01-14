import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import matplotlib.pyplot as plt
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

# 设置绘图风格，避免中文乱码（GitHub环境通常只有英文字体）
plt.style.use('ggplot') 

def upload_image_to_host(file_path):
    """
    📤 将本地图片上传到免费图床 (vim-cn)，获取公网 URL
    这是为了让钉钉能显示图片
    """
    try:
        print("📤 正在上传图片到图床...")
        with open(file_path, 'rb') as f:
            # vim-cn 是一个免费、无需注册的图床，适合脚本使用
            files = {'file': f}
            response = requests.post('https://img.vim-cn.com/', files=files, timeout=30)
            if response.status_code == 200:
                img_url = response.text.strip().replace('http://', 'https://')
                print(f"✅ 图片链接: {img_url}")
                return img_url
    except Exception as e:
        print(f"❌ 图片上传失败: {e}")
    return None

def draw_trend_chart(data_list):
    """
    🎨 使用 Matplotlib 绘制涨跌幅柱状图
    """
    if not data_list: return None
    
    print("🎨 正在绘制趋势图...")
    
    # 1. 准备数据
    names = []
    values = []
    colors = []
    
    # 解析数据
    parsed = []
    for item in data_list:
        try:
            parts = item.split("|")
            name = parts[0].strip().replace("DDR", "D") # 简化名字防止太长
            # 进一步简化名字，只保留规格部分
            if " " in name: name = name.split(" ", 1)[1]
            
            val_str = parts[2].replace("涨跌:", "").replace("%", "").strip()
            val = float(val_str) if val_str not in ["", "-"] else 0
            
            # 只展示有波动的产品，或者前15个
            parsed.append({"name": name, "val": val})
        except: continue

    # 按绝对值大小排序，取波动最大的前 10 个
    parsed.sort(key=lambda x: abs(x['val']), reverse=True)
    top_items = parsed[:10]
    
    # 如果没有波动，就不画了
    if not top_items or all(x['val'] == 0 for x in top_items):
        print("⚠️ 数据无波动，跳过绘图")
        return None

    # 反转列表，让最大的在图表上面
    top_items.reverse()

    for item in top_items:
        names.append(item['name'])
        values.append(item['val'])
        # 涨红跌绿 (Matplotlib里红色是C3/Tab:red, 绿色是C2/Tab:green)
        if item['val'] >= 0:
            colors.append('#d62728') # 红
        else:
            colors.append('#2ca02c') # 绿

    # 2. 绘图
    plt.figure(figsize=(10, 6)) # 设置图片大小
    bars = plt.barh(names, values, color=colors)
    
    plt.title('Top 10 DRAM Price Change (%)', fontsize=14)
    plt.xlabel('Change (%)', fontsize=12)
    plt.grid(True, axis='x', linestyle='--', alpha=0.7)
    
    # 在柱子旁边标注具体数值
    for bar in bars:
        width = bar.get_width()
        label_x_pos = width + (0.05 if width >= 0 else -0.35)
        plt.text(label_x_pos, bar.get_y() + bar.get_height()/2, f'{width:+.2f}%', 
                 va='center', fontsize=10, fontweight='bold')

    plt.tight_layout()
    
    # 3. 保存图片
    filename = "chart.png"
    plt.savefig(filename)
    plt.close()
    print("✅ 图表已保存")
    
    return filename

def send_dingtalk_markdown(title, content, img_url=None):
    """发送 Markdown 消息"""
    if not WEBHOOK or not SECRET:
        print("❌ 错误: 未检测到钉钉配置")
        return

    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    
    # 如果有图片，拼接到 Markdown 内容最后
    final_text = content
    if img_url:
        final_text += f"\n\n![趋势图]({img_url})"

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": final_text}}
    
    try:
        requests.post(url, headers=headers, json=data, timeout=10)
        print("✅ 推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def generate_report(data_list):
    """生成文字报告"""
    if not data_list: return "暂无数据"
    parsed = []
    for item in data_list:
        try:
            parts = item.split("|")
            val = float(parts[2].replace("涨跌:", "").replace("%", "").strip())
            parsed.append({"raw": item, "val": val})
        except: continue
    
    up = sorted([x for x in parsed if x['val'] > 0], key=lambda x: x['val'], reverse=True)
    down = sorted([x for x in parsed if x['val'] < 0], key=lambda x: x['val'])
    flat = [x for x in parsed if x['val'] == 0]
    
    lines = [f"## 📊 DRAM 行情 (图表版)", f"> 更新: {time.strftime('%H:%M')}", "---"]
    
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
        for x in flat[:5]: # 限制显示数量，因为有图了
            parts = x['raw'].split("|")
            lines.append(f"- {parts[0].strip()}")
        if len(flat) > 5:
            lines.append(f"- ... 等共 {len(flat)} 款")
            
    return "\n".join(lines)

def scrape_data():
    """Chrome 爬虫引擎"""
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
        print(f"✅ 抓取成功: {len(data)} 条")
        
        # 1. 尝试绘图并上传
        img_url = None
        try:
            chart_path = draw_trend_chart(data)
            if chart_path:
                img_url = upload_image_to_host(chart_path)
        except Exception as e:
            print(f"⚠️ 绘图/上传环节出错: {e}")
            
        # 2. 生成报告并发送
        report = generate_report(data)
        send_dingtalk_markdown("DRAM日报", report, img_url)
    else:
        print("❌ 未抓取到数据")
