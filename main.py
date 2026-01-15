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
from webdriver_manager.chrome import ChromeDriverManager
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
    """解决 Linux 环境中文乱码"""
    # 安装命令: sudo apt-get install fonts-wqy-microhei
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False

def get_ai_analysis(data_results):
    """DeepSeek AI 分析"""
    if not AI_API_KEY:
        return "⚠️ AI 配置缺失，请在 GitHub Secrets 中配置 AI_API_KEY。"
    
    # 格式化数据给 AI
    summary_data = ""
    for cat, content in data_results.items():
        summary_data += f"\n【{cat}】\n" + " | ".join(content['headers']) + "\n"
        for row in content['rows'][:8]:
            summary_data += " | ".join(row) + "\n"

    try:
        client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个存储行业分析师，请根据数据给出简短有力的市场趋势判断。"},
                {"role": "user", "content": f"分析以下价格数据并给出结论，要求加粗核心观点，总字数150内：\n{summary_data}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ AI 分析调用失败: {str(e)}"

def draw_table(title, headers, rows):
    """精美表格绘制"""
    if not rows: return None
    
    # 动态调整尺寸
    fig_width = max(10, len(headers) * 1.5)
    fig_height = len(rows) * 0.5 + 1.5
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    ax.axis('off')

    # 绘图配色
    colors = {'header': '#e6f4ff', 'row_even': '#ffffff', 'row_odd': '#fafafa'}
    
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.8)

    # 样式美化
    for (i, j), cell in table.get_celld().items():
        if i == 0:  # 表头
            cell.set_facecolor(colors['header'])
            cell.set_text_props(weight='bold')
        else:
            cell.set_facecolor(colors['row_even'] if i % 2 == 0 else colors['row_odd'])
            # 最后一列涨跌变色
            if j == len(headers) - 1:
                val = rows[i-1][j]
                if '▲' in val or '+' in val: cell.set_text_props(color='red', weight='bold')
                elif '▼' in val or '-' in val: cell.set_text_props(color='green', weight='bold')

    plt.title(f"{title} Monitor ({time.strftime('%Y-%m-%d')})", fontsize=14, weight='bold', pad=10)
    path = f"table_{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=150)
    plt.close()
    return path

def scrape_trendforce():
    """爬取所有板块"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
    
    results = {}
    try:
        driver.get("https://www.trendforce.cn/price")
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 定义你需要抓取的关键词
        targets = ["DRAM", "NAND Flash", "SSD"]
        tables = soup.find_all('table')
        
        for i, table in enumerate(tables):
            if i >= len(targets): break
            name = targets[i]
            headers = [th.text.strip() for th in table.find_all('th')]
            rows = [[td.text.strip() for td in tr.find_all('td')] for tr in table.find_all('tr') if tr.find_all('td')]
            if rows:
                results[name] = {"headers": headers, "rows": rows}
    finally:
        driver.quit()
    return results

def send_dingtalk(img_links, ai_text):
    """最终汇总推送"""
    if not WEBHOOK: return
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{SECRET}"
    hmac_code = hmac.new(SECRET.encode('utf-8'), string_to_sign.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    md_content = f"## 📊 TrendForce 存储价格 全局报告\n> 更新时间: {time.strftime('%H:%M')}\n\n"
    md_content += f"### 🤖 AI 深度解读\n{ai_text}\n\n---\n"
    
    for cat, url in img_links.items():
        md_content += f"#### {cat}\n![{cat}]({url})\n\n"

    requests.post(f"{WEBHOOK}&timestamp={timestamp}&sign={sign}", 
                  json={"msgtype": "markdown", "markdown": {"title": "存储价格日报", "text": md_content}})

if __name__ == "__main__":
    configure_fonts()
    all_data = scrape_trendforce()
    
    if all_data:
        # 1. 获取 AI 分析
        ai_summary = get_ai_analysis(all_data)
        
        # 2. 绘图并上传
        final_links = {}
        for cat, content in all_data.items():
            file_path = draw_table(cat, content['headers'], content['rows'])
            if file_path:
                # 上传 Catbox
                with open(file_path, 'rb') as f:
                    r = requests.post('https://catbox.moe/user/api.php', 
                                     data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
                    if r.status_code == 200:
                        final_links[cat] = r.text.strip()
                os.remove(file_path)
        
        # 3. 推送
        send_dingtalk(final_links, ai_summary)
