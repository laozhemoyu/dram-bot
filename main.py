import os, time, hmac, hashlib, base64, urllib.parse, requests, logging
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

# 环境配置
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
    
    # 🔥 核心修复：直接调用系统预装的 msedgedriver，删掉 DriverManager().install()
    # GitHub Actions ubuntu 环境通过 apt 安装后，路径就在 /usr/bin/msedgedriver
    try:
        service = EdgeService(executable_path='/usr/bin/msedgedriver')
        driver = webdriver.Edge(service=service, options=options)
    except Exception as e:
        logger.warning(f"指定路径启动失败，尝试默认模式: {e}")
        driver = webdriver.Edge(options=options)
    
    results = {}
    try:
        logger.info("📡 正在实时访问 TrendForce 官网...")
        driver.get("https://www.trendforce.cn/price")
        
        # 等待表格加载
        WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 强制向下滚动，确保底部的 SSD 模块被触发加载
        for scroll in [1000, 2000]:
            driver.execute_script(f"window.scrollTo(0, {scroll});")
            time.sleep(5)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        targets = {"DRAM": "DRAM 现货价格", "NAND Flash": "NAND Flash 现货价格", "SSD": "成品现货价格"}
        
        for key, title_text in targets.items():
            anchor = soup.find(lambda tag: tag.name in ['div', 'span', 'h3'] and title_text in tag.text)
            if anchor:
                table = anchor.find_next('table')
                if table:
                    headers = [th.get_text(strip=True) for th in table.find_all('th')]
                    rows = []
                    for tr in table.find_all('tr')[1:]:
                        cells = tr.find_all('td')
                        if len(cells) >= 2:
                            # 修复之前出现的“型号显示为数字”的问题
                            line = []
                            for i, td in enumerate(cells):
                                # 优先抓取 title 属性，这通常包含完整的型号名称
                                txt = td.get('title') or td.get_text(" ", strip=True)
                                line.append(txt)
                            if len(line[0]) > 3: # 过滤无效行
                                rows.append(line[:len(headers)])
                    
                    if rows:
                        results[key] = {"headers": headers, "rows": rows}
                        logger.info(f"✅ 成功抓取: {key}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    if not rows: return None
    # 加宽画布防止文字重叠
    fig, ax = plt.subplots(figsize=(16, len(rows)*0.55 + 2))
    ax.axis('off')
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='left')
    table.auto_set_font_size(False); table.set_fontsize(11); table.scale(1.2, 2.4)
    for (i, j), cell in table.get_celld().items():
        if i == 0: cell.set_facecolor('#D6EAF8'); cell.set_text_props(weight='bold', ha='center')
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=120); plt.close()
    return path

def get_ai_analysis(data):
    if not AI_API_KEY: return "AI Key 未配置"
    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        resp = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "user", "content": f"总结行情：{str(data)[:1000]}"}])
        return resp.choices[0].message.content
    except: return "AI 分析暂时不可用"

def send_dingtalk(links, ai_text):
    if not WEBHOOK or not links: return
    ts = str(round(time.time() * 1000))
    sign = urllib.parse.quote_plus(base64.b64encode(hmac.new(SECRET.encode('utf-8'), f"{ts}\n{SECRET}".encode('utf-8'), hashlib.sha256).digest()))
    md = f"### 📊 实时存储行情报告\n{ai_text}\n\n---\n"
    for cat in ["DRAM", "NAND Flash", "SSD"]:
        if cat in links: md += f"#### {cat}\n![{cat}]({links[cat]})\n\n"
    requests.post(f"{WEBHOOK}&timestamp={ts}&sign={sign}", json={"msgtype": "markdown", "markdown": {"title": "价格监控", "text": md}})

if __name__ == "__main__":
    configure_fonts()
    res = scrape_trendforce()
    if res:
        ai = get_ai_analysis(res)
        img_links = {}
        for cat, content in res.items():
            p = draw_table(cat, content['headers'], content['rows'])
            if p:
                r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': open(p, 'rb')})
                if r.status_code == 200: img_links[cat] = r.text.strip()
        send_dingtalk(img_links, ai)
