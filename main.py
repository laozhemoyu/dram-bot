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

# 设置绘图字体，优先使用 Noto Sans CJK (GitHub环境)
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False # 解决负号显示问题

def upload_image_to_host(file_path):
    """上传图片到图床 (vim-cn)"""
    try:
        print("📤 正在上传全量表格...")
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post('https://img.vim-cn.com/', files=files, timeout=30)
            if response.status_code == 200:
                img_url = response.text.strip().replace('http://', 'https://')
                print(f"✅ 图片链接: {img_url}")
                return img_url
    except Exception as e:
        print(f"❌ 图片上传失败: {e}")
    return None

def draw_full_table(data_list):
    """
    🎨 绘制包含所有数据的 7 列长表格
    """
    if not data_list: return None
    
    print(f"🎨 正在绘制包含 {len(data_list)} 条数据的表格...")
    
    # 1. 准备表头
    columns = ["项目", "日高点", "日低点", "盘高点", "盘低点", "盘平均", "盘涨跌幅"]
    rows = []
    colors = [] # 存储每一行的文本颜色

    for item in data_list:
        # item 已经是列表格式 [名, 日高, 日低, 盘高, 盘低, 均价, 涨跌]
        clean_row = [str(x).strip() for x in item]
        rows.append(clean_row)
        
        # 判断颜色（根据最后一列涨跌幅）
        change_str = clean_row[-1]
        row_color = 'black' # 默认黑色
        
        if "-" in change_str and change_str != "-": 
            row_color = 'green' # 跌显示绿
        elif "0%" in change_str or change_str == "-":
            row_color = 'black' # 平显示黑
        else:
            row_color = 'red'   # 涨显示红
            
        # 将该行的所有列都设为这个颜色
        colors.append([row_color] * 7)

    # 2. 动态计算图片高度
    # 数据越多，图片越长。每行给 0.5 的高度，基础高度 2
    row_height = 0.5
    fig_height = max(4, len(rows) * row_height + 1.5)
    
    # 创建画布
    fig, ax = plt.subplots(figsize=(15, fig_height)) 
    
    # 隐藏坐标轴
    ax.axis('off')

    # 绘制表格
    table = ax.table(cellText=rows,
                     colLabels=columns,
                     cellLoc='center',
                     loc='center',
                     colColours=['#e6f4ff']*7) # 表头淡蓝色背景

    # 3. 美化表格样式
    table.auto_set_font_size(False)
    table.set_fontsize(10) # 字体大小
    table.scale(1, 2)      # 拉伸行高

    # 设置单元格颜色和字体粗细
    for i, row_colors in enumerate(colors):
        for j, color in enumerate(row_colors):
            # (i+1, j) 对应单元格 (因为第0行是表头)
            cell = table[(i+1, j)]
            cell.get_text().set_color(color)
            
            # 第一列(产品名) 左对齐
            if j == 0:
                cell.set_text_props(ha='left')
                cell.get_text().set_fontweight('bold')

    # 4. 保存图片
    filename = "full_table.png"
    plt.savefig(filename, bbox_inches='tight', dpi=150, pad_inches=0.2)
    plt.close()
    print("✅ 全量表格图片已生成")
    return filename

def send_dingtalk_markdown(title, img_url):
    """发送只包含图片的 Markdown 消息"""
    if not WEBHOOK or not SECRET: 
        print("❌ 未配置钉钉 Secrets")
        return

    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    
    # Markdown 内容：点击图片可放大
    content = f"### 📊 {title}\n> 数据量: 全量监测\n> 更新时间: {time.strftime('%H:%M')}\n\n![行情表]({img_url})"

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    
    try:
        requests.post(url, headers=headers, json=data, timeout=15)
        print("✅ 推送成功")
    except Exception as e:
        print(f"❌ 推送失败: {e}")

def scrape_data():
    """Chrome 爬虫：抓取所有行、所有列"""
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
        
        # 尝试点击 DRAM 按钮
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'DRAM')]")))
            driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except: pass
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        raw_rows = []
        
        # 遍历所有行
        # 寻找 table 下所有的 tr
        rows = soup.select('table tbody tr') or soup.select('table tr')
        print(f"🔍 找到 {len(rows)} 行原始数据")

        for row in rows:
            cols = row.find_all(['th', 'td'])
            
            # 必须满足至少 7 列才抓取
            if len(cols) < 7: continue
            
            # 获取第1列产品名
            p_name = cols[0].get_text(strip=True)
            
            # 只要包含 DDR 就抓取（DDR3/4/5），不再限制数量
            if 'DDR' in p_name.upper():
                row_data = [
                    p_name,                          # 0: 项目
                    cols[1].get_text(strip=True),    # 1: 日高
                    cols[2].get_text(strip=True),    # 2: 日低
                    cols[3].get_text(strip=True),    # 3: 盘高
                    cols[4].get_text(strip=True),    # 4: 盘低
                    cols[5].get_text(strip=True),    # 5: 盘均
                    cols[6].get_text(strip=True)     # 6: 涨跌
                ]
                raw_rows.append(row_data)
        
        return raw_rows
    except Exception as e:
        print(f"Error: {e}")
        return []
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 启动全量抓取任务...")
    
    # 1. 抓取
    all_data = scrape_data()
    
    if all_data:
        print(f"✅ 成功提取 {len(all_data)} 条有效数据")
        
        # 2. 绘图 (生成全量长图)
        img_path = draw_full_table(all_data)
        
        # 3. 上传图床
        if img_path:
            url = upload_image_to_host(img_path)
            
            # 4. 推送
            if url:
                send_dingtalk_markdown("DRAM 全量行情表", url)
            else:
                print("❌ 图片上传失败，无法推送")
    else:
        print("❌ 未抓取到数据")
