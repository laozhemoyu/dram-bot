import os, time, hmac, hashlib, base64, urllib.parse, requests, logging
import matplotlib.pyplot as plt
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from openai import OpenAI

# 1. 日志配置：确保在 GitHub Actions 日志中清晰可见
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 2. 从 GitHub Secrets 读取环境变量
WEBHOOK = os.environ.get("DING_WEBHOOK")
SECRET = os.environ.get("DING_SECRET")
AI_API_KEY = os.environ.get("AI_API_KEY")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.deepseek.com")

def scrape_trendforce():
    """使用 Chrome 抓取 TrendForce 实时价格"""
    chrome_options = Options()
    chrome_options.add_argument("--headless") # 必须开启无头模式
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 自动识别系统中的 chromedriver
    driver = webdriver.Chrome(options=chrome_options)
    results = {}
    
    try:
        logger.info("📡 正在联网访问 TrendForce 官网抓取数据...")
        driver.get("https://www.trendforce.cn/price")
        
        # 等待表格核心组件加载
        WebDriverWait(driver, 35).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        
        # 模拟滚动，确保所有懒加载的表格（如 SSD）都能渲染
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {800 * (i+1)});")
            time.sleep(2)
        
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
                            for idx, td in enumerate(cells):
                                # 🔥 核心修复：优先抓取 title 属性（TrendForce 网页版型号通常存在 title 中）
                                val = td.get('title') or td.get_text(" ", strip=True)
                                line.append(val)
                            
                            # 过滤掉非数据行（如广告或空行）
                            if line and len(line[0]) > 3:
                                rows.append(line[:len(headers)])
                    
                    if rows:
                        results[key] = {"headers": headers, "rows": rows}
                        logger.info(f"✅ 抓取板块成功: {key}")
    except Exception as e:
        logger.error(f"❌ 抓取过程中出错: {e}")
    finally:
        driver.quit()
    return results

def draw_table(title, headers, rows):
    """将数据绘制成图片"""
    if not rows: return None
    
    # 设置中文字体（需配合 yml 中的安装命令）
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 动态调整图片高度，避免数据多时重叠
    fig, ax = plt.subplots(figsize=(16, len(rows) * 0.6 + 2))
    ax.axis('off')
    
    table = ax.table(cellText=rows, colLabels=headers, loc='center', cellLoc='left')
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 2.8) # 增加行高
    
    # 美化表头
    for (i, j), cell in table.get_celld().items():
        if i == 0:
            cell.set_facecolor('#D6EAF8')
            cell.set_text_props(weight='bold', ha='center')
            
    path = f"{title}.png"
    plt.savefig(path, bbox_inches='tight', dpi=120)
    plt.close()
    return path

def send_dingtalk(links, ai_text):
    """发送带图片的钉钉消息，并打印调试日志"""
    if not WEBHOOK or not SECRET:
        logger.error("❌ 环境变量 DING_WEBHOOK 或 DING_SECRET 缺失，请检查 GitHub Secrets 配置！")
        return

    # 生成时间戳和签名
    ts = str(round(time.time() * 1000))
    secret_enc = SECRET.encode('utf-8')
    string_to_sign = f'{ts}\n{SECRET}'
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    
    # 构造 Markdown 内容
    # 标题包含关键词“价格监控”，请确保钉钉机器人“关键词”设置中包含“价格”
    md_text = f"### 📊 实时存储价格监控报告 ({time.strftime('%Y-%m-%d')})\n\n"
    md_text += f"> {ai_text}\n\n---\n"
    
    for cat in ["DRAM", "NAND Flash", "SSD"]:
        if cat in links:
            md_text += f"#### {cat} 行情预览\n![{cat}]({links[cat]})\n\n"

    # 发送请求
    target_url = f"{WEBHOOK}&timestamp={ts}&sign={sign}"
    try:
        resp = requests.post(target_url, json={
            "msgtype": "markdown",
            "markdown": {"title": "价格监控报告", "text": md_text}
        })
        
        # 🔥 核心调试：打印钉钉的反馈结果
        result = resp.json()
        logger.info(f"📡 钉钉接口反馈: {result}")
        if result.get("errcode") == 0:
            logger.info("🎉 钉钉消息发送成功！")
        else:
            logger.error(f"⚠️ 钉钉发送失败！错误原因: {result.get('errmsg')}")
            logger.error("👉 请检查：1.机器人是否加签 2.关键词是否匹配 3.Webhook地址是否正确")
    except Exception as e:
        logger.error(f"❌ 请求钉钉接口出错: {e}")

if __name__ == "__main__":
    data_results = scrape_trendforce()
    
    if data_results:
        # AI 行情分析（DeepSeek 驱动）
        summary = "今日存储市场现货价格已更新，详细趋势请见下方图表。"
        if AI_API_KEY:
            try:
                client = OpenAI(api_key=AI_API_KEY, base_url=AI_BASE_URL)
                # 仅传前 1000 字符防止 Token 溢出
                prompt = f"请对以下存储器行情数据做简要总结（200字以内）：{str(data_results)[:1000]}"
                response = client.chat.completions.create(model="deepseek-chat", messages=[{"role": "user", "content": prompt}])
                summary = response.choices[0].message.content
                logger.info("🤖 AI 分析生成成功")
            except Exception as e:
                logger.warning(f"🤖 AI 分析失败: {e}")

        # 生成图片并上传
        img_urls = {}
        for category, content in data_results.items():
            file_path = draw_table(category, content['headers'], content['rows'])
            if file_path:
                try:
                    # 使用 Catbox 临时图床，以便钉钉能正常解析 Markdown 图片
                    with open(file_path, 'rb') as f:
                        upload_resp = requests.post('https://catbox.moe/user/api.php', 
                                                  data={'reqtype': 'fileupload'}, 
                                                  files={'fileToUpload': f})
                        if upload_resp.status_code == 200:
                            img_urls[category] = upload_resp.text.strip()
                            logger.info(f"📤 图片已上传 ({category}): {img_urls[category]}")
                    os.remove(file_path) # 删除本地临时文件
                except Exception as e:
                    logger.error(f"📤 图片上传失败 ({category}): {e}")
        
        # 最终发送
        send_dingtalk(img_urls, summary)
    else:
        logger.error("🈳 未能抓取到任何数据，请检查网络或 TrendForce 页面结构是否变化。")
