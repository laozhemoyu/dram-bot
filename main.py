import os, time, hmac, hashlib, base64, urllib.parse, requests, logging, re
import matplotlib.pyplot as plt
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")

def configure_fonts():
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

def scrape_trendforce():
    options = EdgeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0")
    
    # 🔥 修复方案：直接使用 GitHub 环境预装的驱动，跳过 WebDriver Manager 网络连接
    try:
        service = EdgeService(executable_path='/usr/bin/msedgedriver') 
        driver = webdriver.Edge(service=service, options=options)
    except:
        # 如果路径不匹配，尝试自动寻找（不联网下载）
        driver = webdriver.Edge(options=options)
    
    results = {}
    try:
        logger.info("📡 正在精准访问 TrendForce...")
        driver.get("https://www.trendforce.cn/price")
        
        # 强制等待核心表格出现
        WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 深度滚动触发所有异步数据
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {800 * (i+1)});")
            time.sleep(4)
            
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 目标板块关键字
        targets = {"DRAM": "DRAM 现货价格", "NAND Flash": "NAND Flash 现货价格", "SSD": "成品现货价格"}
        
        for key, title_text in targets.items():
            # 找到标题
            anchor = soup.find(lambda tag: tag.name in ['div', 'span', 'h3'] and title_text in tag.text)
            if not anchor: continue
            
            table = anchor.find_next('table')
            if table:
                headers = [th.get_text(strip=True) for th in table.find_all('th')]
                rows = []
                for tr in table.find_all('tr')[1:]:
                    cells = tr.find_all('td')
                    if len(cells) > 2:
                        # 🔥 修复项目名称显示问题：排除干扰脚本，只提取纯净文字
                        line = []
                        for i, td in enumerate(cells):
                            [s.extract() for s in td(['script', 'style'])] # 剔除脚本
                            text = td.get_text(" ", strip=True)
                            # 如果第一列全是数字，尝试抓取它子标签里的 title 或数据
                            if i == 0 and text.replace('.', '').isdigit():
                                text = td.get('title') or text
                            line.append(text)
                        
                        if len(line[0]) > 3: # 过滤无效短行
                            rows.append(line[:len(headers)])
                
                if rows:
                    results[key] = {"headers": headers, "rows": rows}
                    logger.info(f"✅ 成功抓取板块: {key}")

    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    if not rows: return None
    # 进一步加宽画布，确保 DDR5 16G (2Gx8) 不重叠
    fig, ax = plt.subplots(figsize=(16, len(rows)*0.5 + 2))
    ax.axis('off')
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='left')
    table.auto_set_font_size(False); table.set_fontsize(11); table.scale(1.2, 2.4)
    
    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#D6EAF8'); cell.set_text_props(weight='bold', ha='center')
        elif j == len(headers) - 1:
            val = rows[i-1][j]
            if '▲' in val or '+' in val: cell.set_text_props(color='red', weight='bold')
            elif '▼' in val or '-' in val: cell.set_text_props(color='green', weight='bold')
    
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=120); plt.close()
    return path

def get_ai_analysis(data):
    if not AI_API_KEY: return "AI 配置缺失"
    prompt = f"分析以下存储行情并给出150字内判断，加粗结论：\n{str(data)[:2000]}"
    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        resp = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content
    except: return "AI 分析暂时故障"

def send_dingtalk(links, ai_text):
    if not WEBHOOK or not links: return
    ts = str(round(time.time() * 1000))
    sign = urllib.parse.quote_plus(base64.b64encode(hmac.new(SECRET.encode('utf-8'), f"{ts}\n{SECRET}".encode('utf-8'), hashlib.sha256).digest()))
    md = f"## 📊 存储价格行情监控\n\n### 🤖 AI 分析\n{ai_text}\n\n---\n"
    for cat in ["DRAM", "NAND Flash", "SSD"]:
        if cat in links: md += f"#### {cat}\n![{cat}]({links[cat]})\n\n"
    requests.post(f"{WEBHOOK}&timestamp={ts}&sign={sign}", json={"msgtype": "markdown", "markdown": {"title": "行情快报", "text": md}})

if __name__ == "__main__":
    configure_fonts()
    res = scrape_trendforce()
    if res:
        ai = get_ai_analysis(res)
        links = {}
        for cat, content in res.items():
            p = draw_table(cat, content['headers'], content['rows'])
            if p:
                r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': open(p, 'rb')})
                if r.status_code == 200: links[cat] = r.text.strip()
        send_dingtalk(links, ai)
