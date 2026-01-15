import os, time, hmac, hashlib, base64, urllib.parse, requests, logging
import matplotlib.pyplot as plt
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# 获取密钥
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")

def configure_fonts():
    # 尝试加载中文字体
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False

def scrape_trendforce():
    chrome_options = Options()
    chrome_options.add_argument("--headless") # 无头模式
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # 模拟真实浏览器
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 🔥 核心修改：使用 GitHub Actions 系统自带的 chromedriver，无需下载
    driver = webdriver.Chrome(options=chrome_options)
    
    results = {}
    try:
        logger.info("📡 正在实时访问 TrendForce 官网...")
        driver.get("https://www.trendforce.cn/price")
        
        # 等待表格加载
        WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 强制滚动以触发加载 SSD 板块
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {1000 * (i+1)});")
            time.sleep(3)
            
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
                            line = []
                            for i, td in enumerate(cells):
                                # 🔥 修复项目名称：优先取 title 属性（包含完整规格）
                                txt = td.get('title') or td.get_text(" ", strip=True)
                                line.append(txt)
                            # 过滤掉明显的空行或纯数字错误行
                            if len(line[0]) > 3:
                                rows.append(line[:len(headers)])
                    
                    if rows:
                        results[key] = {"headers": headers, "rows": rows}
                        logger.info(f"✅ 成功抓取板块: {key}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    if not rows: return None
    # 动态调整图片高度
    fig, ax = plt.subplots(figsize=(16, len(rows)*0.6 + 2))
    ax.axis('off')
    # 创建表格
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='left')
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 2.8) # 增加行高，防止文字挤在一起
    
    # 设置表头颜色
    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#D6EAF8')
            cell.set_text_props(weight='bold', ha='center')
            
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=120)
    plt.close()
    return path

def get_ai_analysis(data):
    if not AI_API_KEY: return "AI Key 未配置"
    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": f"请对以下存储器行情做简要分析（200字以内）：{str(data)[:1000]}"}]
        )
        return resp.choices[0].message.content
    except:
        return "AI 分析服务暂不可用"

def send_dingtalk(links, ai_text):
    if not WEBHOOK or not links: return
    ts = str(round(time.time() * 1000))
    sign = urllib.parse.quote_plus(base64.b64encode(hmac.new(SECRET.encode('utf-8'), f"{ts}\n{SECRET}".encode('utf-8'), hashlib.sha256).digest()))
    
    # 组装 Markdown
    md = f"### 📊 实时存储价格报告 ({time.strftime('%Y-%m-%d')})\n\n"
    md += f"> {ai_text}\n\n---\n"
    for cat in ["DRAM", "NAND Flash", "SSD"]:
        if cat in links:
            md += f"#### {cat}\n![{cat}]({links[cat]})\n\n"
            
    requests.post(f"{WEBHOOK}&timestamp={ts}&sign={sign}", json={
        "msgtype": "markdown",
        "markdown": {"title": "价格快报", "text": md}
    })

if __name__ == "__main__":
    configure_fonts()
    res = scrape_trendforce()
    if res:
        ai_msg = get_ai_analysis(res)
        img_links = {}
        for cat, content in res.items():
            p = draw_table(cat, content['headers'], content['rows'])
            if p:
                # 使用 Catbox 临时上传图片
                r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': open(p, 'rb')})
                if r.status_code == 200:
                    img_links[cat] = r.text.strip()
                os.remove(p)
        send_dingtalk(img_links, ai_msg)
