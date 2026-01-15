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

# ================= 配置 =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")

def configure_fonts():
    """
    专门针对 GitHub Linux 环境的字体配置
    """
    # 1. 优先尝试加载 Linux 系统自带的中文字体 (需要 workflow 安装)
    font_names = ['WenQuanYi Micro Hei', 'Noto Sans CJK JP', 'SimHei']
    
    # 查找系统可用字体
    system_fonts = set(f.name for f in fm.fontManager.ttflist)
    logger.info(f"系统可用字体示例: {list(system_fonts)[:5]}")
    
    detected_font = None
    for font in font_names:
        if font in system_fonts:
            detected_font = font
            break
            
    if detected_font:
        logger.info(f"✅ 使用系统字体: {detected_font}")
        plt.rcParams['font.sans-serif'] = [detected_font]
        plt.rcParams['axes.unicode_minus'] = False
    else:
        # 2. 如果都没有，尝试下载字体 (保底策略)
        font_path = 'SimHei.ttf'
        if not os.path.exists(font_path):
            logger.info("⚠️ 未找到系统字体，正在下载 SimHei.ttf ...")
            try:
                # 从 GitHub 镜像或其他源下载字体
                url = "https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf"
                r = requests.get(url)
                with open(font_path, "wb") as f:
                    f.write(r.content)
            except Exception as e:
                logger.error(f"字体下载失败: {e}")
                
        if os.path.exists(font_path):
            # 显式加载字体文件
            prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = prop.get_name()
            logger.info(f"✅ 已加载本地字体文件: {font_path}")
        else:
            logger.error("❌ 严重警告: 无可用中文字体，图表文字将显示为方框")

def get_driver():
    """获取适配 GitHub Actions 的 Driver"""
    options = Options()
    options.add_argument("--headless=new") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    # 伪装反爬
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 使用 webdriver_manager 自动安装驱动
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # 移除 selenium 特征
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    return driver

def upload_image(file_path):
    """上传到 Catbox"""
    try:
        if not os.path.exists(file_path): return None
        with open(file_path, 'rb') as f:
            resp = requests.post(
                'https://catbox.moe/user/api.php', 
                data={'reqtype': 'fileupload'}, 
                files={'fileToUpload': f},
                timeout=30
            )
            if resp.status_code == 200:
                return resp.text.strip()
    except Exception as e:
        logger.error(f"上传失败: {e}")
    return None

def draw_table(title, headers, rows):
    """绘图函数"""
    if not rows: return None
    # 截取前 25 行防止图片过长
    rows = rows[:25]
    
    # 设置图形大小
    h_scale = len(rows) * 0.6 + 2
    w_scale = len(headers) * 2.5
    fig, ax = plt.subplots(figsize=(w_scale, h_scale))
    ax.axis('off')
    
    # 绘制
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='center')
    
    # 样式调整
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 1.8)
    
    # 如果使用了本地字体文件，需要手动应用字体属性
    font_path = 'SimHei.ttf'
    font_prop = fm.FontProperties(fname=font_path) if os.path.exists(font_path) else None
    
    if font_prop:
        for cell in table.get_celld().values():
            cell.set_text_props(fontproperties=font_prop)

    # 简单配色
    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#409EFF')
            cell.set_text_props(color='white', weight='bold')
            if font_prop: cell.set_text_props(fontproperties=font_prop, weight='bold', color='white')
        else:
            val = rows[i-1][j]
            if j == len(headers) - 1: # 最后一列涨跌
                if '▲' in val or '+' in val: cell.set_text_props(color='red')
                if '▼' in val or '-' in val: cell.set_text_props(color='green')

    plt.title(f"{title} ({time.strftime('%m-%d')})", y=0.98)
    filename = f"{title}.png"
    plt.savefig(filename, bbox_inches='tight', dpi=120)
    plt.close()
    return filename

def main():
    configure_fonts() # 初始化字体
    driver = get_driver()
    results = {}
    
    try:
        url = "https://www.trendforce.cn/price"
        logger.info(f"正在访问: {url}")
        driver.get(url)
        time.sleep(5) # 简单粗暴等待 Cloudflare 验证通过
        
        # 调试：打印当前页面标题，看是否被拦截
        logger.info(f"当前页面标题: {driver.title}")
        
        if "403" in driver.title or "Access denied" in driver.page_source:
            logger.error("❌ 被 TrendForce 拦截 (403 Forbidden)")
            return

        # 获取 DRAM 和 Flash 数据 (根据当前页面 DOM 结构)
        # 注意：这里简化处理，获取页面所有表格
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        # 针对 TrendForce 的结构尝试寻找 DRAM 按钮并点击
        # 实际 GitHub Actions 可能不需要点击，直接抓默认显示的，或者抓取所有 tab 内容
        # 这里为了演示稳定性，我们尝试直接抓取当前显示的表格
        
        tables = soup.find_all('table')
        categories = ['DRAM', 'NAND Flash'] # 假定顺序，或者根据内容判断
        
        for idx, table in enumerate(tables):
            if idx >= len(categories): break
            
            cat_name = categories[idx]
            headers = [th.text.strip() for th in table.find_all('th')]
            rows = []
            for tr in table.find_all('tr'):
                cols = [td.text.strip() for td in tr.find_all('td')]
                if cols: rows.append(cols)
            
            if rows:
                if not headers: headers = [f"Col{i}" for i in range(len(rows[0]))]
                results[cat_name] = {'headers': headers, 'rows': rows}
                logger.info(f"抓取到 {cat_name}: {len(rows)} 行")

    except Exception as e:
        logger.error(f"抓取过程出错: {e}")
    finally:
        driver.quit()

    # 推送
    if results:
        image_urls = {}
        for name, data in results.items():
            path = draw_table(name, data['headers'], data['rows'])
            if path:
                link = upload_image(path)
                if link: image_urls[name] = link
        
        if image_urls:
            send_dingtalk(image_urls)
    else:
        logger.warning("未获取到数据，不推送")

def send_dingtalk(img_map):
    if not WEBHOOK or not SECRET: return
    timestamp = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = '{}\n{}'.format(timestamp, SECRET)
    hmac_code = hmac.new(secret_enc, string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    md_text = f"## 📊 存储价格日报\n> {time.strftime('%Y-%m-%d')}\n\n"
    for k, v in img_map.items():
        md_text += f"**{k}**\n![img]({v})\n"
        
    requests.post(
        f"{WEBHOOK}&timestamp={timestamp}&sign={sign}",
        json={"msgtype": "markdown", "markdown": {"title": "价格日报", "text": md_text}}
    )

if __name__ == "__main__":
    main()
