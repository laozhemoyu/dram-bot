import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import logging
import matplotlib.pyplot as plt
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

# 获取环境变量
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")

def configure_fonts():
    """解决 Linux 环境中文显示为方框的问题"""
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

def get_ai_analysis(data_results):
    """DeepSeek AI 分析逻辑"""
    if not AI_API_KEY:
        return "⚠️ 未检测到 AI_API_KEY，请检查 GitHub Secrets 配置。"

    # 提取数据给 AI
    summary_text = ""
    for cat, content in data_results.items():
        summary_text += f"\n【{cat}】\n"
        for row in content['rows'][:10]: # 传递核心型号数据
            summary_text += " | ".join(row) + "\n"

    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一名存储行业资深分析师。"},
                {"role": "user", "content": f"请分析以下存储价格趋势，给出150字内的简要判断。核心结论请**加粗**显示：\n{summary_text}"}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI 调用异常: {e}")
        return "❌ AI 接口调用失败。"

def scrape_trendforce():
    """加强版爬虫：应对跨境延迟与反爬"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    
    # 隐藏 WebDriver 特征
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    
    results = {}
    try:
        logger.info("📡 正在尝试访问 TrendForce 中国官网...")
        driver.get("https://www.trendforce.cn/price")
        
        # 🔥 关键：增加等待时间至 40 秒，应对海外 IP 访问国内延迟
        wait = WebDriverWait(driver, 40)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 给 JavaScript 填充数据留出缓冲时间
        time.sleep(8)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        tables = soup.find_all('table')
        logger.info(f"✅ 成功加载页面，检测到 {len(tables)} 个表格")
        
        categories = ["DRAM", "NAND Flash", "SSD"]
        for i, table in enumerate(tables):
            if i >= len(categories): break
            headers = [th.text.strip() for th in table.find_all('th')]
            rows = [[td.text.strip() for td in tr.find_all('td')] for tr in table.find_all('tr') if tr.find_all('td')]
            if rows:
                results[categories[i]] = {"headers": headers, "rows": rows}
                
    except Exception as e:
        logger.error(f"❌ 数据抓取深度异常: {e}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    """绘制带红绿涨跌色的精美表格"""
    if not rows: return None
    fig_height = len(rows) * 0.45 + 1.5
    fig, ax = plt.subplots(figsize=(12, fig_height))
    ax.axis('off')
    
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.8)

    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#D6EAF8')
            cell.set_text_props(weight='bold')
        else:
            if i % 2 == 0: cell.set_facecolor('#F9FBFC')
            # 最后一列根据涨跌幅变色
            if j == len(headers) - 1:
                val = rows[i-1][j]
                if '▲' in val or '+' in val: cell.set_text_props(color='#C0392B', weight='bold')
                elif '▼' in val or '-' in val: cell.set_text_props(color='#27AE60', weight='bold')

    plt.title(f"{title} Monitor ({time.strftime('%Y-%m-%d')})", fontsize=14, pad=10, weight='bold')
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=150)
    plt.close()
    return path

def send_dingtalk(img_links, ai_text):
    """钉钉推送逻辑"""
    if not WEBHOOK or not img_links: 
        logger.error("推送失败：WEBHOOK 缺失或数据为空。")
        return
        
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{SECRET}"
    hmac_code = hmac.new(SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    md = f"## 📊 TrendForce 存储价格 深度报告\n\n### 🤖 AI 趋势解读\n{ai_text}\n\n---\n"
    for cat, url in img_links.items():
        md += f"#### {cat} 行情预览\n![{cat}]({url})\n\n"

    url = f"{WEBHOOK}&timestamp={timestamp}&sign={sign}"
    resp = requests.post(url, json={"msgtype": "markdown", "markdown": {"title": "存储行情快报", "text": md}})
    logger.info(f"钉钉推送结果: {resp.text}")

if __name__ == "__main__":
    configure_fonts()
    data = scrape_trendforce()
    if data:
        # 1. AI 分析
        ai_summary = get_ai_analysis(data)
        
        # 2. 绘图并上传图片
        links = {}
        for cat, content in data.items():
            path = draw_table(cat, content['headers'], content['rows'])
            if path:
                # 使用 Catbox 上传生成公网链接
                with open(path, 'rb') as f:
                    r = requests.post('https://catbox.moe/user/api.php', 
                                     data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
                    if r.status_code == 200: 
                        links[cat] = r.text.strip()
                        logger.info(f"已上传图片: {cat}")
                os.remove(path)
        
        # 3. 发送钉钉
        send_dingtalk(links, ai_summary)
    else:
        logger.error("最终未抓取到有效数据，任务终止。")
