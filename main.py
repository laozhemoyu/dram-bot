import os, time, hmac, hashlib, base64, urllib.parse, requests, logging
import matplotlib.pyplot as plt
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from bs4 import BeautifulSoup
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 获取环境变量
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")

def configure_fonts():
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

def get_ai_analysis(data_results):
    if not AI_API_KEY: return "⚠️ 未配置 AI API Key。"
    summary = ""
    for cat, content in data_results.items():
        summary += f"\n【{cat}】\n" + "\n".join([" | ".join(row) for row in content['rows'][:10]])
    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "你是一名存储行业资深分析师。"},
                      {"role": "user", "content": f"分析以下存储价格趋势，150字内，结论需**加粗**：\n{summary}"}]
        )
        return response.choices[0].message.content
    except: return "❌ AI 趋势分析调用失败。"

def scrape_trendforce():
    """使用 Microsoft Edge 进行数据抓取"""
    options = EdgeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # 模拟真实 Edge 用户代理
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0")
    
    service = EdgeService(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)
    
    results = {}
    try:
        logger.info("📡 正在启动 Edge 访问 TrendForce...")
        driver.get("https://www.trendforce.cn/price")
        
        # 针对海外 IP 访问国内站增加超长等待
        wait = WebDriverWait(driver, 45)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 额外缓冲时间确保 SSD 动态数据渲染完毕
        time.sleep(12) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        tables = soup.find_all('table')
        logger.info(f"✅ Edge 加载成功，找到 {len(tables)} 个数据表")
        
        cats = ["DRAM", "NAND Flash", "SSD"]
        for i, table in enumerate(tables[:3]):
            headers = [th.text.strip() for th in table.find_all('th')]
            rows = [[td.text.strip() for td in tr.find_all('td')] for tr in table.find_all('tr') if tr.find_all('td')]
            if rows:
                results[cats[i]] = {"headers": headers, "rows": rows}
                logger.info(f"提取成功: {cats[i]}")
    except Exception as e:
        logger.error(f"❌ Edge 抓取过程出错: {e}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    if not rows: return None
    fig, ax = plt.subplots(figsize=(12, len(rows)*0.45 + 1.5))
    ax.axis('off')
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='center')
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.8)
    
    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#D6EAF8')
            cell.set_text_props(weight='bold')
        elif j == len(headers) - 1: # 涨跌变色
            val = rows[i-1][j]
            if '▲' in val or '+' in val: cell.set_text_props(color='#C0392B', weight='bold')
            elif '▼' in val or '-' in val: cell.set_text_props(color='#27AE60', weight='bold')
    
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=130); plt.close()
    return path

def send_dingtalk(links, ai_text):
    if not WEBHOOK or not links: return
    ts = str(round(time.time() * 1000))
    sign = urllib.parse.quote_plus(base64.b64encode(hmac.new(SECRET.encode('utf-8'), f"{ts}\n{SECRET}".encode('utf-8'), hashlib.sha256).digest()))
    
    md = f"## 📊 存储价格行情 (Edge 引擎)\n\n### 🤖 AI 深度解读\n{ai_text}\n\n---\n"
    for cat, url in links.items():
        md += f"#### {cat}\n![{cat}]({url})\n\n"

    requests.post(f"{WEBHOOK}&timestamp={ts}&sign={sign}", 
                  json={"msgtype": "markdown", "markdown": {"title": "行情报告", "text": md}})

if __name__ == "__main__":
    configure_fonts()
    data = scrape_trendforce()
    if data:
        ai_msg = get_ai_analysis(data)
        links = {}
        for cat, content in data.items():
            path = draw_table(cat, content['headers'], content['rows'])
            if path:
                # 通过 Catbox 上传生成公网图床链接
                with open(path, 'rb') as f:
                    r = requests.post('https://catbox.moe/user/api.php', 
                                     data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
                    if r.status_code == 200: links[cat] = r.text.strip()
                os.remove(path)
        send_dingtalk(links, ai_msg)
    else:
        logger.error("未能抓取到任何数据。")
