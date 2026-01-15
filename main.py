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

def get_ai_analysis(data_results):
    if not AI_API_KEY: return "⚠️ 未配置 AI Key。"
    summary = ""
    for cat, content in data_results.items():
        summary += f"\n【{cat}】\n" + "\n".join([" | ".join(row) for row in content['rows'][:10]])
    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "system", "content": "你是一名存储分析师。"},
                      {"role": "user", "content": f"总结以下价格趋势（150字内，**加粗**结论）：\n{summary}"}]
        )
        return response.choices[0].message.content
    except: return "❌ AI 分析失败。"

def scrape_trendforce():
    options = EdgeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0")
    
    service = EdgeService(EdgeChromiumDriverManager().install())
    driver = webdriver.Edge(service=service, options=options)
    
    results = {}
    try:
        logger.info("📡 正在启动 Edge 访问页面...")
        driver.get("https://www.trendforce.cn/price")
        
        # 初始等待
        WebDriverWait(driver, 45).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 🔥 修复 SSD 缺失：分三段滚动并触发懒加载
        for p in [0.3, 0.6, 1.0]:
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight * {p});")
            time.sleep(4)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # 寻找所有包含“现货价格”的模块
        sections = soup.find_all('div', class_='price-table-block') or soup.find_all('div', class_='table-responsive')
        
        # 预设顺序
        cats_list = ["DRAM", "NAND Flash", "SSD"]
        tables = soup.find_all('table')
        logger.info(f"检测到 {len(tables)} 个表格")

        for i, table in enumerate(tables):
            if i >= len(cats_list): break
            
            # 🔥 修复项目名字错误：精准提取第一列文字
            headers = [th.get_text(strip=True) for th in table.find_all('th')]
            rows = []
            for tr in table.find_all('tr'):
                cells = tr.find_all('td')
                if not cells: continue
                # 尝试获取第一列的完整文字（包含隐藏属性或子标签）
                row_data = [td.get_text(strip=True) for td in cells]
                if row_data: rows.append(row_data)
            
            if rows:
                results[cats_list[i]] = {"headers": headers, "rows": rows}
                logger.info(f"✅ 成功提取: {cats_list[i]} (共 {len(rows)} 行)")

    except Exception as e:
        logger.error(f"❌ 抓取异常: {e}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    if not rows: return None
    # 增加宽度以适应长项目名称
    fig, ax = plt.subplots(figsize=(14, len(rows)*0.5 + 2))
    ax.axis('off')
    
    # 修复文字显示：自动调整列宽
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='left')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 2.0) # 纵向拉伸方便阅读

    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#D6EAF8')
            cell.set_text_props(weight='bold', ha='center')
        elif j == len(headers) - 1: # 最后一列变色
            val = rows[i-1][j]
            if '▲' in val or '+' in val: cell.set_text_props(color='red', weight='bold')
            elif '▼' in val or '-' in val: cell.set_text_props(color='green', weight='bold')
            cell.set_text_props(ha='center')
        else:
            cell.set_text_props(ha='left')

    plt.title(f"{title} Monitor ({time.strftime('%Y-%m-%d')})", fontsize=16, pad=20, weight='bold')
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=120)
    plt.close()
    return path

def send_dingtalk(links, ai_text):
    if not WEBHOOK or not links: return
    ts = str(round(time.time() * 1000))
    sign = urllib.parse.quote_plus(base64.b64encode(hmac.new(SECRET.encode('utf-8'), f"{ts}\n{SECRET}".encode('utf-8'), hashlib.sha256).digest()))
    
    md = f"## 📊 存储价格快报\n\n### 🤖 AI 深度解读\n{ai_text}\n\n---\n"
    # 显式排序确保 SSD 在末尾
    for key in ["DRAM", "NAND Flash", "SSD"]:
        if key in links:
            md += f"#### {key}\n![{key}]({links[key]})\n\n"

    requests.post(f"{WEBHOOK}&timestamp={ts}&sign={sign}", 
                  json={"msgtype": "markdown", "markdown": {"title": "价格报告", "text": md}})

if __name__ == "__main__":
    configure_fonts()
    data = scrape_trendforce()
    if data:
        ai_msg = get_ai_analysis(data)
        links = {}
        for cat, content in data.items():
            path = draw_table(cat, content['headers'], content['rows'])
            if path:
                # 使用 Catbox 上传
                with open(path, 'rb') as f:
                    r = requests.post('https://catbox.moe/user/api.php', 
                                     data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
                    if r.status_code == 200: links[cat] = r.text.strip()
                os.remove(path)
        send_dingtalk(links, ai_msg)
