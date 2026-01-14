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

# 设置中文字体 (适配 GitHub Linux 环境)
plt.rcParams['font.sans-serif'] = ['Noto Sans CJK JP', 'SimHei', 'Arial Unicode MS', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False 

def upload_image_stable(file_path):
    """上传图片 (优先 Catbox)"""
    print(f"📤 正在上传: {file_path} ...")
    try:
        with open(file_path, 'rb') as f:
            data = {'reqtype': 'fileupload', 'userhash': ''}
            files = {'fileToUpload': f}
            response = requests.post('https://catbox.moe/user/api.php', data=data, files=files, timeout=30)
            if response.status_code == 200:
                url = response.text.strip()
                print(f"✅ 上传成功: {url}")
                return url
    except: pass
    return None

def draw_generic_table(title, headers, rows):
    """
    🎨 通用绘图函数：根据传入的表头和数据自动调整
    """
    if not rows or not headers: return None
    print(f"🎨 正在绘制 [{title}] ({len(rows)} 行)...")
    
    # 动态计算图表尺寸
    col_count = len(headers)
    row_count = len(rows)
    
    # 宽度：列越多越宽
    fig_width = max(12, col_count * 2.2)
    # 高度：行越多越高
    fig_height = max(4, row_count * 0.6 + 2)
    
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')

    # 绘制表格
    # 动态分配列宽：第一列(产品名)给宽一点，其余平分
    col_widths = []
    if col_count > 0:
        first_col_w = 0.25
        other_col_w = (1.0 - first_col_w) / (col_count - 1)
        col_widths = [first_col_w] + [other_col_w] * (col_count - 1)

    table = ax.table(
        cellText=rows, 
        colLabels=headers, 
        cellLoc='center', 
        loc='center',
        colWidths=col_widths if len(col_widths) == col_count else None
    )

    # 美化表格
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 2)
    
    cells = table.get_celld()
    
    # 定义颜色
    color_header = '#e6f4ff' # 浅蓝表头
    color_even   = '#ffffff' # 白
    color_odd    = '#f9f9f9' # 浅灰 (斑马纹)

    for i in range(row_count + 1):
        for j in range(col_count):
            cell = cells[(i, j)]
            
            # 表头样式
            if i == 0:
                cell.set_facecolor(color_header)
                cell.set_text_props(weight='bold', size=12)
            else:
                # 数据行斑马纹背景
                cell.set_facecolor(color_even if i % 2 == 0 else color_odd)
                
                # 第一列左对齐 + 加粗
                if j == 0:
                    cell.set_text_props(ha='left', weight='bold')
                
                # 尝试根据最后一列(通常是涨跌)变色
                # 如果是最后一列
                if j == col_count - 1:
                    val_text = rows[i-1][j]
                    if "▲" in val_text or "+" in val_text:
                        cell.set_text_props(color='#d62728', weight='bold') # 红
                    elif "▼" in val_text or "-" in val_text:
                        if "0%" not in val_text:
                            cell.set_text_props(color='green', weight='bold') # 绿

    plt.title(f"{title} Monitor ({time.strftime('%Y-%m-%d')})", fontsize=16, weight='bold', y=0.98)
    
    filename = f"table_{title}.png"
    plt.savefig(filename, bbox_inches='tight', dpi=150, pad_inches=0.2)
    plt.close()
    return filename

def send_dingtalk_multi_images(title, image_urls):
    """发送包含多张图片的 Markdown"""
    if not WEBHOOK or not SECRET: return
    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    
    # 构建内容
    content = f"### 📊 {title} 全局报告\n> 更新: {time.strftime('%H:%M')}\n\n"
    
    if not image_urls:
        content += "⚠️ 未获取到任何数据图表。"
    else:
        for category, img_url in image_urls.items():
            content += f"#### {category}\n![{category}]({img_url})\n\n"

    headers = {'Content-Type': 'application/json'}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": content}}
    try:
        requests.post(url, headers=headers, json=data, timeout=20)
        print("✅ 推送成功")
    except: pass

def scrape_trendforce_all():
    """全品类爬虫：DRAM / Flash / SSD"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    
    # 结果容器: {'DRAM': {'headers': [], 'rows': []}, 'NAND Flash': ...}
    results = {}

    try:
        print("🌐 访问 TrendForce...")
        driver.get("https://www.trendforce.cn/price")
        time.sleep(5)
        
        # 定义我们要抓取的类别及其对应的按钮关键词
        # 注意：TrendForce 页面上 SSD 可能没有独立的一级按钮，如果有就抓，没有就跳过
        targets = [
            ("DRAM", "//*[contains(text(), 'DRAM')]"),
            ("NAND Flash", "//*[contains(text(), 'Flash') or contains(text(), 'NAND')]"), 
            ("SSD", "//*[contains(text(), 'SSD')]")
        ]

        for category, xpath in targets:
            print(f"\n🔍 尝试切换到 [{category}] 板块...")
            try:
                # 1. 点击切换标签
                # 查找所有匹配的元素，点击第一个可见的
                btns = driver.find_elements(By.XPATH, xpath)
                clicked = False
                for btn in btns:
                    if btn.is_displayed():
                        driver.execute_script("arguments[0].click();", btn)
                        time.sleep(3) # 等待表格加载
                        clicked = True
                        break
                
                if not clicked:
                    print(f"⚠️ 未找到 [{category}] 的切换按钮，跳过。")
                    continue

                # 2. 解析表格
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                table = soup.select_one('table')
                if not table:
                    print(f"⚠️ [{category}] 页面未发现表格。")
                    continue

                # 3. 获取动态表头
                headers = []
                thead = table.select_one('thead')
                if thead:
                    headers = [th.get_text(strip=True) for th in thead.find_all('th')]
                
                # 如果没抓到表头，尝试用第一行数据反推（只要列数对）
                if not headers:
                    print(f"⚠️ [{category}] 无表头，尝试通用表头...")
                    # 临时占位，后续根据数据列数补齐
                
                # 4. 获取数据行
                rows = []
                data_rows = table.select('tbody tr') or table.select('tr')
                
                for row in data_rows:
                    cols = row.find_all(['td', 'th'])
                    # 过滤掉空行或表头行
                    if not cols or (cols[0].name == 'th' and not headers): 
                        continue
                    
                    row_data = [c.get_text(strip=True) for c in cols]
                    
                    # 简单清洗：如果该行数据太少，可能是无效行
                    if len(row_data) < 3: continue
                    
                    rows.append(row_data)

                print(f"✅ [{category}] 抓取成功: {len(rows)} 行, {len(headers)} 列")
                
                # 如果之前没抓到表头，现在根据第一行数据生成由 Col1, Col2... 组成的假表头
                if not headers and rows:
                    headers = [f"Col {i+1}" for i in range(len(rows[0]))]

                if rows:
                    results[category] = {
                        "headers": headers,
                        "rows": rows
                    }

            except Exception as e:
                print(f"❌ 抓取 [{category}] 时出错: {e}")

        return results

    except Exception as e:
        print(f"Error: {e}")
        return {}
    finally:
        driver.quit()

if __name__ == "__main__":
    print("🚀 启动全品类抓取任务 (DRAM/Flash/SSD)...")
    
    # 1. 抓取
    all_data_map = scrape_trendforce_all()
    
    # 2. 绘图 & 上传
    image_links = {}
    
    if all_data_map:
        for category, data in all_data_map.items():
            # 为每个类别画一张图
            img_path = draw_generic_table(category, data['headers'], data['rows'])
            if img_path:
                url = upload_image_stable(img_path)
                if url:
                    image_links[category] = url
    else:
        print("❌ 未抓取到任何数据")

    # 3. 发送汇总消息
    if image_links:
        send_dingtalk_multi_images("TrendForce 存储价格", image_links)
    else:
        print("❌ 无图片可发送")
