import os
import time
import datetime
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

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False 

def upload_image_stable(file_path):
    """
    📤 稳定版上传函数 (双图床轮询)
    优先使用 Catbox，失败自动切换 vim-cn
    """
    print("📤 正在上传图片...")
    
    # --- 方案 A: Catbox (非常稳定) ---
    try:
        print("   正在尝试图床 A (Catbox)...")
        with open(file_path, 'rb') as f:
            data = {'reqtype': 'fileupload', 'userhash': ''}
            files = {'fileToUpload': f}
            response = requests.post('https://catbox.moe/user/api.php', data=data, files=files, timeout=30)
            if response.status_code == 200:
                url = response.text.strip()
                print(f"✅ 上传成功: {url}")
                return url
    except Exception as e:
        print(f"⚠️ 图床 A 失败: {e}")

    # --- 方案 B: Vim-cn (备用) ---
    try:
        print("   正在尝试图床 B (Vim-cn)...")
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post('https://img.vim-cn.com/', files=files, timeout=30)
            if response.status_code == 200:
                url = response.text.strip().replace('http://', 'https://')
                print(f"✅ 上传成功: {url}")
                return url
    except Exception as e:
        print(f"⚠️ 图床 B 失败: {e}")

    print("❌ 所有图床均上传失败")
    return None

def draw_summary_report(data_list):
    """
    🎨 绘制【市场分布汇总报告】
    """
    if not data_list: return None
    print("🎨 正在绘制汇总报告...")

    # 1. 数据分类
    rising = []
    falling = []
    flat = []

    for item in data_list:
        name = item[0]
        short_name = name.replace("DDR", "D") 
        if len(short_name) > 25: short_name = short_name[:22] + "..."
        change = item[6]
        display_str = f"• {short_name}, {change}"
        
        if "-" in change and change != "-":
             falling.append(display_str)
        elif "0%" in change or change == "-":
             flat.append(display_str)
        else:
             rising.append(display_str)

    # 2. 准备表格内容
    MAX_SHOW = 12 
    def format_list(lst):
        if not lst: return "-"
        if len(lst) > MAX_SHOW:
            return "\n".join(lst[:MAX_SHOW]) + f"\n... (Total {len(lst)})"
        return "\n".join(lst)

    rows_data = [
        ["⬆ Rising (涨)", len(rising), format_list(rising), "Positive"],
        ["⬇ Falling (跌)", len(falling), format_list(falling), "Negative"],
        ["➡ Unchanged\n(平)", len(flat), format_list(flat), "Neutral"]
    ]
    
    col_labels = ["Market Trend", "Product Count", "Product List (Examples)", "Status"]
    row_colors = ['#d62728', '#2ca02c', '#555555']

    # 3. 动态计算高度
    line_counts = [r[2].count('\n') + 1 for r in rows_data]
    total_text_lines = sum(line_counts) + 3 
    fig_height = max(5, total_text_lines * 0.4)
    
    fig, ax = plt.subplots(figsize=(12, fig_height))
    ax.axis('off')

    # 4. 绘制表格
    table = ax.table(
        cellText=rows_data, colLabels=col_labels, cellLoc='left', loc='center',
        colWidths=[0.15, 0.12, 0.58, 0.15]
    )

    table.auto_set_font_size(False)
    table.set_fontsize(11)
    cells = table.get_celld()
    header_ratio = 2 / total_text_lines 
    
    for j in range(4):
        cell = cells[(0, j)]
        cell.set_height(header_ratio)
        cell.set_text_props(weight='bold')
        cell.set_facecolor('#f0f0f0')
        cell._loc = 'center'

    for i, line_count in enumerate(line_counts):
        row_idx = i + 1
        row_ratio = line_count / total_text_lines
        for j in range(4):
            cell = cells[(row_idx, j)]
            cell.set_height(row_ratio)
            if j == 0: cell.set_text_props(color=row_colors[i], weight='bold', ha='center', size=12)
            if j == 1: cell.set_text_props(ha='center', size=12)
            if j == 2: cell.get_text().set_x(0.02) 
            if j == 3: cell.set_text_props(ha='center')

    total_count = len(data_list)
    sentiment = "Mixed"
    if len(rising) > len(falling): sentiment = "Bullish (Upward)"
    elif len(falling) > len(rising): sentiment = "Bearish (Downward)"
    
    plt.title(f"DRAM Market Distribution Report ({total_count} Products)", fontsize=16, weight='bold', y=0.98)
    footer_text = f"Total Products: {total_count}  |  Overall Sentiment: {sentiment}"
    plt.figtext(0.5, 0.02, footer_text, ha="center", fontsize=12, bbox={"facecolor":"#e6f4ff", "edgecolor":"none", "pad":8, "alpha":0.5})
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
    plt.figtext(0.95, 0.01, f"Last Update: {timestamp}", ha="right", fontsize=9, color="grey")

    filename = "summary_report.png"
    plt.savefig(filename, bbox_inches='tight', dpi=150, pad_inches=0.2)
    plt.close()
    print("✅ 汇总表格图片已生成")
    return filename

def send_dingtalk_smart(title, text_backup, img_url=None):
    """
    🧠 智能发送函数
    有图发图，图床挂了就发文字，绝不哑火
    """
    if not WEBHOOK or not SECRET: return
    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    
    # 构建内容
    content = f"### 📊 {title}\n> 更新时间: {time.strftime('%H:%M')}\n\n"
    
    if img_url:
        content += f"![行情表]({img_url})"
    else:
        # 降级模式：发送文字
        content += "⚠️ (图片上传失败，转为文字版)\n\n" + text_backup

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    
    try:
        requests.post(url, headers=headers, json=data, timeout=15)
        print("✅ 推送成功")
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
    print("🚀 启动任务...")
    data = scrape_data()
    if data:
        print(f"✅ 抓取到 {len(data)} 条数据")
        
        # 1. 尝试生成图片
        img_url = None
        try:
            chart_path = draw_summary_report(data)
            if chart_path:
                img_url = upload_image_stable(chart_path)
        except Exception as e:
            print(f"⚠️ 绘图模块报错: {e}")

        # 2. 准备文字备份 (以防图片失败)
        # 简单提取前10条数据作为备份
        backup_text = ""
        for item in data[:10]:
            backup_text += f"- {item[0]}: {item[5]} ({item[6]})\n"

        # 3. 发送 (智能判断)
        send_dingtalk_smart("DRAM 市场分布报告", backup_text, img_url)
    else:
        print("❌ 未抓取到数据")
