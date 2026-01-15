import os, time, hmac, hashlib, base64, urllib.parse, requests, logging
import matplotlib.pyplot as plt
from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
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

def scrape_trendforce():
    options = EdgeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0")
    
    driver = webdriver.Edge(service=EdgeService(EdgeChromiumDriverManager().install()), options=options)
    
    results = {}
    try:
        logger.info("📡 正在精准探测 TrendForce 数据源...")
        driver.get("https://www.trendforce.cn/price")
        
        # 🔥 步骤 1: 强制滚动以激活 SSD 懒加载
        for scroll in [800, 1600, 2400]:
            driver.execute_script(f"window.scrollTo(0, {scroll});")
            time.sleep(3)
        time.sleep(5) # 最终缓冲
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 🔥 步骤 2: 定义锚点关键词
        # TrendForce 的 SSD 模块通常标题包含“成品”或“SSD”
        targets = {
            "DRAM": "DRAM 现货价格",
            "NAND Flash": "NAND Flash 现货价格",
            "SSD": "成品现货价格" 
        }
        
        for key, title_text in targets.items():
            # 找到包含该标题的元素
            anchor = soup.find(lambda tag: tag.name in ['div', 'span', 'h3'] and title_text in tag.get_text())
            
            if anchor:
                # 找到该标题后方最近的一个 table
                table = anchor.find_next('table')
                if table:
                    # 提取表头
                    headers = [th.get_text(strip=True) for th in table.find_all('th')][:6] # 通常只要前6列
                    
                    rows = []
                    for tr in table.find_all('tr')[1:]:
                        cells = tr.find_all('td')
                        if len(cells) >= 2:
                            # 🔥 步骤 3: 深度清理脏数据（剔除脚本和干扰）
                            row_data = []
                            for i, td in enumerate(cells):
                                # 剔除所有的 script 和 style 标签
                                for dbg in td(["script", "style"]):
                                    dbg.decompose()
                                
                                if i == 0:
                                    # 第一列型号通常较复杂，优先取完整文本
                                    name = td.get_text(" ", strip=True)
                                    row_data.append(name)
                                else:
                                    # 后续列取纯数字/涨跌符
                                    row_data.append(td.get_text(strip=True))
                            
                            if row_data and len(row_data[0]) > 2: # 过滤掉只有数字的错误行
                                rows.append(row_data[:len(headers)])
                    
                    if rows:
                        results[key] = {"headers": headers, "rows": rows}
                        logger.info(f"✅ 精准抓取成功: {key} (找到 {len(rows)} 行)")

    except Exception as e:
        logger.error(f"❌ 抓取核心异常: {e}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    if not rows: return None
    # 增加 figsize 宽度到 16，确保 DDR5 16G (2Gx8) 这种长名字不重叠
    fig, ax = plt.subplots(figsize=(16, len(rows)*0.55 + 2))
    ax.axis('off')
    
    # cellLoc='left' 让文字更有条理
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 2.2)

    # 样式微调：第一列（型号）左对齐，其他居中
    for i in range(len(rows) + 1):
        table[(i, 0)].set_text_props(ha='left', px=10)
        if i == 0:
            table[(i, 0)].set_facecolor('#D6EAF8')
            table[(i, 0)].set_text_props(weight='bold', ha='center')
        else:
            # 奇偶行变色增加可读性
            if i % 2 == 0:
                for j in range(len(headers)):
                    table[(i, j)].set_facecolor('#F9F9F9')

    plt.title(f"TrendForce {title} 监控报告", fontsize=18, pad=35, weight='bold')
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=120)
    plt.close()
    return path

# get_ai_analysis 和 send_dingtalk 保持逻辑不变即可
def get_ai_analysis(data):
    if not AI_API_KEY: return "AI 密钥未配置"
    summary_input = ""
    for k, v in data.items():
        summary_input += f"\n{k}:\n" + "\n".join([str(r) for r in v['rows'][:5]])
    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": f"请作为行业专家总结存储行情变化：{summary_input}"}]
        )
        return resp.choices[0].message.content
    except: return "AI 分析暂时无法连接"

def send_dingtalk(links, ai_text):
    if not WEBHOOK or not links: return
    ts = str(round(time.time() * 1000))
    sign = urllib.parse.quote_plus(base64.b64encode(hmac.new(SECRET.encode('utf-8'), f"{ts}\n{SECRET}".encode('utf-8'), hashlib.sha256).digest()))
    md = f"### 🤖 存储价格深度分析 (Edge Pro)\n{ai_text}\n\n---\n"
    for cat in ["DRAM", "NAND Flash", "SSD"]:
        if cat in links: md += f"#### {cat} 行情预览\n![{cat}]({links[cat]})\n\n"
    requests.post(f"{WEBHOOK}&timestamp={ts}&sign={sign}", json={"msgtype": "markdown", "markdown": {"title": "价格报告", "text": md}})

if __name__ == "__main__":
    configure_fonts()
    data_results = scrape_trendforce()
    if data_results:
        ai_summary = get_ai_analysis(data_results)
        img_links = {}
        for cat, content in data_results.items():
            path = draw_table(cat, content['headers'], content['rows'])
            if path:
                r = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': open(path, 'rb')})
                if r.status_code == 200: img_links[cat] = r.text.strip()
                os.remove(path)
        send_dingtalk(img_links, ai_summary)
    else:
        logger.error("❌ 任务最终未抓取到任何数据，请检查 TrendForce 网页是否变动。")
