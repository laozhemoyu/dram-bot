import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import pandas as pd
import seaborn as sns
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

# 设置 Seaborn 风格和字体
sns.set_theme(style="whitegrid")
# 关键：设置中文字体，否则 GitHub 上显示乱码
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False 

def upload_image_stable(file_path):
    """
    📤 稳定版上传 (Catbox -> Vim-cn)
    """
    print("📤 正在上传图片...")
    try:
        with open(file_path, 'rb') as f:
            data = {'reqtype': 'fileupload', 'userhash': ''}
            files = {'fileToUpload': f}
            response = requests.post('https://catbox.moe/user/api.php', data=data, files=files, timeout=30)
            if response.status_code == 200:
                url = response.text.strip()
                print(f"✅ Catbox: {url}")
                return url
    except: pass

    try:
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post('https://img.vim-cn.com/', files=files, timeout=30)
            if response.status_code == 200:
                url = response.text.strip().replace('http://', 'https://')
                print(f"✅ Vim-cn: {url}")
                return url
    except: pass
    return None

def draw_seaborn_chart(data_list):
    """
    🎨 使用 Seaborn 绘制合约价涨跌幅图
    """
    if not data_list: return None
    print("🎨 正在使用 Seaborn 绘图...")

    # 1. 数据清洗 -> 转为 DataFrame
    clean_data = []
    for item in data_list:
        try:
            # item: [名, 高, 低, 均价, 涨跌, ...]
            name = item[0].replace("DDR", "D") # 缩写
            # 如果名字太长，截断一下
            if len(name) > 30: name = name[:28] + ".."
            
            price = item[3]
            change_str = item[4]
            
            val_clean = change_str.replace("涨跌:", "").replace("%", "").strip()
            val = float(val_clean) if val_clean not in ["", "-"] else 0
            
            clean_data.append({"Product": name, "Price": price, "Change": val})
        except: continue
    
    if not clean_data: return None

    # 创建 DataFrame
    df = pd.DataFrame(clean_data)
    
    # 按涨跌幅绝对值排序，取波动最大的前 15 个，避免图表过长
    df['AbsChange'] = df['Change'].abs()
    df = df.sort_values(by='AbsChange', ascending=False).head(15)
    
    # 2. 定义颜色逻辑 (中国习惯: 红涨绿跌)
    # Seaborn 需要一个颜色列表
    colors = []
    for x in df['Change']:
        if x > 0: colors.append("#d62728") # 红
        elif x < 0: colors.append("#2ca02c") # 绿
        else: colors.append("#7f7f7f") # 灰

    # 3. 绘图
    # 动态高度：数据越多图越高
    plt.figure(figsize=(10, len(df) * 0.5 + 2))
    
    # 绘制条形图
    ax = sns.barplot(x="Change", y="Product", data=df, palette=colors, hue="Product", legend=False)
    
    # 标题和标签
    plt.title(f"DRAM Contract Price Change (Top {len(df)})", fontsize=15, pad=20, fontweight='bold')
    plt.xlabel("Price Change (%)", fontsize=12)
    plt.ylabel("") # 隐藏 Y 轴标题
    
    # 添加垂直参考线 (0轴)
    plt.axvline(x=0, color='black', linewidth=1)

    # 4. 在柱子旁添加数值标签
    for i, container in enumerate(ax.containers):
        # ax.containers 包含了所有的柱子
        labels = [f'{val:+.2f}%' if val != 0 else '-' for val in df['Change']]
        ax.bar_label(container, labels=labels, padding=5, fontsize=10, fontweight='bold')

    # 调整布局
    plt.tight_layout()
    
    # 保存
    filename = "seaborn_chart.png"
    plt.savefig(filename, dpi=120)
    plt.close()
    print("✅ Seaborn 图表已生成")
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
    
    content = f"### 📊 {title}\n> 引擎: Seaborn Visualization\n> 更新: {time.strftime('%H:%M')}\n\n"
    if img_url: content += f"![趋势图]({img_url})"
    else: content += text_backup

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    try:
        requests.post(url, headers=headers, json=data, timeout=15)
        print("✅ 推送成功")
    except: pass

def scrape_data():
    """Chrome 爬虫 (合约价 6列)"""
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
        
        # 切换到合约价
        try:
            btn_contract = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '合约')]")))
            driver.execute_script("arguments[0].click();", btn_contract)
            time.sleep(3)
        except: pass

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        raw_rows = []
        rows = soup.select('table tbody tr') or soup.select('table tr')
        for row in rows:
            cols = row.find_all(['th', 'td'])
            if len(cols) < 6: continue
            p_name = cols[0].get_text(strip=True)
            if 'DDR' in p_name.upper():
                row_data = [
                    p_name,
                    cols[1].get_text(strip=True),
                    cols[2].get_text(strip=True),
                    cols[3].get_text(strip=True), # 均价
                    cols[4].get_text(strip=True), # 涨跌
                    cols[5].get_text(strip=True)
                ]
                raw_rows.append(row_data)
        return raw_rows
    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 启动 Seaborn 任务...")
    data = scrape_data()
    if data:
        print(f"✅ 抓取到 {len(data)} 条数据")
        img_url = None
        try:
            chart_path = draw_seaborn_chart(data)
            if chart_path:
                img_url = upload_image_stable(chart_path)
        except Exception as e:
            print(f"⚠️ 绘图失败: {e}")

        # 备份文字
        backup = "\n".join([f"- {i[0]}: {i[4]}" for i in data[:10]])
        send_dingtalk_smart("DRAM 合约价趋势", backup, img_url)
    else:
        print("❌ 无数据")
