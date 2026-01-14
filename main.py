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

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False 

def upload_image_stable(file_path):
    """上传图片 (Catbox)"""
    print("📤 正在上传图片...")
    try:
        with open(file_path, 'rb') as f:
            data = {'reqtype': 'fileupload', 'userhash': ''}
            files = {'fileToUpload': f}
            response = requests.post('https://catbox.moe/user/api.php', data=data, files=files, timeout=30)
            if response.status_code == 200:
                url = response.text.strip()
                print(f"✅ 上传成功: {url}")
                return url
    except Exception as e:
        print(f"❌ 上传失败: {e}")
    return None

def draw_table_image(data_list):
    """
    🎨 绘制 7 列数据表格
    对应: 项目 | 日高 | 日低 | 盘高 | 盘低 | 均价 | 涨跌
    """
    if not data_list: return None
    print(f"🎨 正在绘制表格 ({len(data_list)} 条数据)...")
    
    columns = ["项目", "日高点", "日低点", "盘高点", "盘低点", "盘平均", "涨跌幅"]
    rows = []
    text_colors = []

    for item in data_list:
        clean_row = [str(x).strip() for x in item]
        rows.append(clean_row)
        
        # 颜色逻辑：看最后一列涨跌
        change = clean_row[6]
        row_color = 'black'
        if "-" in change and change != "-": 
            row_color = 'green'
        elif "0%" in change or change == "-":
            row_color = 'black'
        else:
            row_color = '#d62728' # 红
        
        # 全行变色
        text_colors.append([row_color] * 7)

    # 绘图
    row_height = 0.6
    fig_height = max(4, len(rows) * row_height + 2)
    fig, ax = plt.subplots(figsize=(16, fig_height))
    ax.axis('off')

    table = ax.table(
        cellText=rows, colLabels=columns, cellLoc='center', loc='center',
        colWidths=[0.22, 0.12, 0.12, 0.12, 0.12, 0.13, 0.13]
    )

    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 2)
    
    cells = table.get_celld()
    # 简单的美化
    for i in range(len(rows) + 1):
        for j in range(len(columns)):
            cell = cells[(i, j)]
            if i == 0:
                cell.set_facecolor('#e6f4ff')
                cell.set_text_props(weight='bold')
            else:
                cell.set_text_props(color=text_colors[i-1][j])
                if j == 0: cell.set_text_props(ha='left', weight='bold', color='black')

    plt.title(f"DRAM Spot Price (Raw Data Check)", fontsize=16, weight='bold', y=0.98)
    filename = "raw_table.png"
    plt.savefig(filename, bbox_inches='tight', dpi=150, pad_inches=0.2)
    plt.close()
    return filename

def send_dingtalk_smart(title, text_backup, img_url=None):
    if not WEBHOOK or not SECRET: return
    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    
    content = f"### 📊 {title}\n> 数据核对版\n> 更新: {time.strftime('%H:%M')}\n\n"
    if img_url: content += f"![表格]({img_url})"
    else: content += "⚠️ 图片失败\n\n" + text_backup

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    try:
        requests.post(url, headers=headers, json=data, timeout=15)
        print("✅ 推送成功")
    except: pass

def scrape_data():
    """Chrome 爬虫 (带详细日志打印)"""
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
        
        # 1. 强制点击 DRAM (确保在现货页面)
        try:
            print("🖱️ 正在点击 DRAM 标签...")
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'DRAM')]")))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except Exception as e:
            print(f"⚠️ 点击 DRAM 失败: {e}")

        # 2. 解析
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # --- 🔍 调试：打印表头，确认我们抓对了列 ---
        header_row = soup.select_one('table thead tr')
        if header_row:
            headers = [th.get_text(strip=True) for th in header_row.find_all('th')]
            print(f"🔍 网页表头检测: {headers}")
        else:
            print("⚠️ 未找到表头 (thead)")

        # 3. 抓取数据
        raw_rows = []
        rows = soup.select('table tbody tr') or soup.select('table tr')
        
        print(f"🔍 扫描到 {len(rows)} 行...")
        
        for i, row in enumerate(rows):
            cols = row.find_all(['th', 'td'])
            
            # 必须大于等于7列
            if len(cols) < 7: continue
            
            p_name = cols[0].get_text(strip=True)
            if 'DDR' in p_name.upper():
                # 严格按照现货价 7 列抓取
                # 0:项目, 1:日高, 2:日低, 3:盘高, 4:盘低, 5:均价, 6:涨跌
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
                
                # --- 🔍 调试：打印第一条数据供核对 ---
                if len(raw_rows) == 1:
                    print(f"🔍 首条数据核对: {row_data}")

        return raw_rows
    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 启动核对任务...")
    data = scrape_data()
    if data:
        print(f"✅ 抓取到 {len(data)} 条数据")
        img_url = None
        try:
            chart_path = draw_table_image(data)
            if chart_path:
                img_url = upload_image_stable(chart_path)
        except Exception as e:
            print(f"⚠️ 绘图失败: {e}")

        backup = "\n".join([f"- {i[0]}: {i[5]}" for i in data[:10]])
        send_dingtalk_smart("DRAM 数据核对", backup, img_url)
    else:
        print("❌ 无数据")
