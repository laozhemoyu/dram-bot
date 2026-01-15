import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import logging
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from openai import OpenAI

# ================= 配置日志 =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 从环境变量读取配置
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")

def configure_fonts():
    """配置中文字体，解决 GitHub Actions 环境乱码"""
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

def get_ai_analysis(data_results):
    """调用 AI 接口进行行情总结"""
    if not AI_API_KEY or AI_API_KEY == "":
        return "⚠️ AI 配置缺失，请检查 GitHub Secrets 中的 AI_API_KEY。"

    # 提取核心数据传给 AI
    summary_text = ""
    for cat, content in data_results.items():
        summary_text += f"\n【{cat}】\n"
        # 仅取前8行核心型号，节省 Token 并提高分析效率
        for row in content['rows'][:8]:
            summary_text += " | ".join(row) + "\n"

    prompt = f"""
    你是一名存储行业资深分析师。请根据以下最新的 TrendForce 价格数据（DRAM/NAND/SSD），写一份 150 字以内的专业行情解读。
    要求：总结整体涨跌趋势，点出波动明显的型号，**核心观点需加粗**。使用 Markdown 格式。
    数据：
    {summary_text}
    """

    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的存储行业分析助手。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI 调用失败: {e}")
        return "❌ AI 分析调用超时或失败。"

def draw_table(title, headers, rows):
    """绘制带颜色和斑马纹的精美表格"""
    if not rows: return None
    
    # 根据行数动态调整高度
    fig_height = len(rows) * 0.45 + 1.5
    fig, ax = plt.subplots(figsize=(12, fig_height))
    ax.axis('off')

    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.8)

    # 遍历单元格设置样式
    for (i, j), cell in table.get_celld().items():
        if i == 0: # 表头
            cell.set_facecolor('#D6EAF8')
            cell.set_text_props(weight='bold')
        else:
            # 斑马纹
            if i % 2 == 0:
                cell.set_facecolor('#F9FBFC')
            
            # 最后一列（通常是涨跌幅）红绿着色
            if j == len(headers) - 1:
                val = rows[i-1][j]
                if '▲' in val or '+' in val:
                    cell.set_text_props(color='#C0392B', weight='bold') # 红色
                elif '▼' in val or '-' in val:
                    cell.set_text_props(color='#27AE60', weight='bold') # 绿色

    plt.title(f"{title} Monitor ({time.strftime('%Y-%m-%d')})", fontsize=14, pad=10, weight='bold')
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=150)
    plt.close()
    return path

def scrape_trendforce():
    """精准抓取 DRAM, NAND 和 SSD 表格"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    results = {}
    
    try:
        driver.get("https://www.trendforce.cn/price")
        # 🔥 关键：显式等待页面至少加载 3 个表格
        WebDriverWait(driver, 25).until(lambda d: len(d.find_elements(By.TAG_NAME, "table")) >= 3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        tables = soup.find_all('table')
        categories = ["DRAM", "NAND Flash", "SSD"]
        
        for i, table in enumerate(tables):
            if i >= len(categories): break
            cat_name = categories[i]
            
            headers = [th.text.strip() for th in table.find_all('th')]
            rows = []
            for tr in table.find_all('tr'):
                cols = [td.text.strip() for td in tr.find_all('td')]
                if cols: rows.append(cols)
            
            if rows:
                results[cat_name] = {"headers": headers, "rows": rows}
                logger.info(f"✅ 成功抓取: {cat_name}")
    except Exception as e:
        logger.error(f"抓取异常: {e}")
    finally:
        driver.quit()
    return results

def send_dingtalk(img_map, ai_text):
    """构建 Markdown 并推送到钉钉"""
    if not WEBHOOK: return
    
    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = f'{timestamp}\n{SECRET}'
    hmac_code = hmac.new(secret_enc, string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    md_text = f"## 📊 TrendForce 存储价格 全局报告\n> 更新时间: {time.strftime('%Y-%m-%d %H:%M')}\n\n"
    md_text += f"### 🤖 AI 深度解读\n{ai_text}\n\n---\n"
    
    for cat, url in img_map.items():
        md_text += f"#### {cat}\n![{cat}]({url})\n\n"

    requests.post(f"{WEBHOOK}&timestamp={timestamp}&sign={sign}", 
                  json={"msgtype": "markdown", "markdown": {"title": "存储行情报告", "text": md_text}})

if __name__ == "__main__":
    configure_fonts()
    data = scrape_trendforce()
    
    if data:
        # 1. 执行 AI 分析
        ai_summary = get_ai_analysis(data)
        
        # 2. 绘图并上传图片（此处需安装 requests）
        img_links = {}
        for cat, content in data.items():
            path = draw_table(cat, content['headers'], content['rows'])
            if path:
                # 上传到 Catbox 获取公网 URL
                with open(path, 'rb') as f:
                    resp = requests.post('https://catbox.moe/user/api.php', 
                                         data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
                    if resp.status_code == 200:
                        img_links[cat] = resp.text.strip()
                os.remove(path) # 清理本地文件
        
        # 3. 发送钉钉
        send_dingtalk(img_links, ai_summary)
    else:
        logger.error("数据抓取为空，请检查网络或 TrendForce 页面结构。")
