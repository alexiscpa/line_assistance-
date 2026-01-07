from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, AudioMessageContent, ImageMessageContent
import os
import tempfile
from dotenv import load_dotenv
from openai import OpenAI
from notion_client import Client
from google_drive_service import get_google_drive_service, create_folder_if_not_exists, upload_image_to_drive
import base64
import re
import requests
from bs4 import BeautifulSoup
from apify_client import ApifyClient
import logging
from logging.handlers import RotatingFileHandler

load_dotenv()

app = Flask(__name__)

# 設定日誌記錄到檔案
if not app.debug:
    file_handler = RotatingFileHandler('bot_logs.txt', maxBytes=10240000, backupCount=10, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info('LINE Bot 啟動')

configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
notion = Client(auth=os.getenv('NOTION_API_KEY'))
apify_client = ApifyClient(os.getenv('APIFY_API_KEY'))

# Google Drive 會在首次需要時才初始化（延遲載入）
drive_service = None
drive_folder_id = None

def init_google_drive():
    """延遲初始化 Google Drive"""
    global drive_service, drive_folder_id
    if drive_service is not None:
        return True

    try:
        app.logger.info("正在初始化 Google Drive...")
        drive_service = get_google_drive_service()

        # 優先使用指定的資料夾 ID
        folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')
        if folder_id:
            drive_folder_id = folder_id
            app.logger.info(f"使用指定的 Google Drive 資料夾 ID: {folder_id}")
        else:
            drive_folder_id = create_folder_if_not_exists(
                drive_service,
                os.getenv('GOOGLE_DRIVE_FOLDER_NAME', 'LINE靈感助手')
            )
        app.logger.info("Google Drive 初始化成功！")
        return True
    except Exception as e:
        app.logger.error(f"Google Drive 初始化失敗: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        # 重置 drive_service 以便下次可以重試
        drive_service = None
        return False


def is_url(text):
    """檢查文字是否包含 URL"""
    # 簡單的 URL 正則表達式
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    return url_pattern.search(text)


def extract_url(text):
    """從文字中提取 URL"""
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    match = url_pattern.search(text)
    return match.group(0) if match else None


def is_facebook_url(url):
    """檢查是否為 Facebook URL"""
    facebook_patterns = [
        r'facebook\.com',
        r'fb\.com',
        r'fb\.watch',
        r'm\.facebook\.com'
    ]
    return any(re.search(pattern, url) for pattern in facebook_patterns)


def is_threads_url(url):
    """檢查是否為 Threads URL"""
    threads_patterns = [
        r'threads\.net',
        r'www\.threads\.net',
        r'threads\.com',  # 支援 .com 網域
        r'www\.threads\.com'
    ]
    return any(re.search(pattern, url) for pattern in threads_patterns)


def scrape_threads_content(url):
    """使用免費網頁爬取方式處理 Threads 內容"""
    try:
        app.logger.info(f"正在使用網頁爬取 Threads 內容: {url}")

        # 設定完整的瀏覽器 headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }

        # 發送請求
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.raise_for_status()

        app.logger.info(f"HTTP 狀態碼: {response.status_code}")
        app.logger.info(f"回應內容長度: {len(response.content)}")

        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # 儲存爬取結果
        content = ""
        title = "Threads 貼文"
        author = ""

        # 方法 1: 從 Open Graph meta 標籤取得資訊
        meta_description = soup.find('meta', {'property': 'og:description'})
        meta_title = soup.find('meta', {'property': 'og:title'})

        if meta_description and meta_description.get('content'):
            content = meta_description.get('content')
            app.logger.info(f"✓ 從 og:description 取得內容 ({len(content)} 字元)")

        if meta_title and meta_title.get('content'):
            title = meta_title.get('content')
            # 從標題提取作者名稱
            if ' on Threads' in title:
                author = title.replace(' on Threads', '').strip()
                title = f"{author} 的 Threads 貼文"
            app.logger.info(f"✓ 從 og:title 取得標題: {title}")

        # 方法 2: 從 Twitter Card meta 標籤取得
        if not content:
            twitter_desc = soup.find('meta', {'name': 'twitter:description'})
            if twitter_desc and twitter_desc.get('content'):
                content = twitter_desc.get('content')
                app.logger.info(f"✓ 從 twitter:description 取得內容")

        if not title or title == "Threads 貼文":
            twitter_title = soup.find('meta', {'name': 'twitter:title'})
            if twitter_title and twitter_title.get('content'):
                title = twitter_title.get('content')
                app.logger.info(f"✓ 從 twitter:title 取得標題")

        # 方法 3: 從 JSON-LD 結構化資料取得
        if not content or len(content) < 20:
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    import json
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if 'articleBody' in data:
                            content = data['articleBody']
                            app.logger.info(f"✓ 從 JSON-LD articleBody 取得內容")
                        elif 'description' in data:
                            content = data['description']
                            app.logger.info(f"✓ 從 JSON-LD description 取得內容")
                except:
                    pass

        # 方法 4: 從頁面標題取得
        if not title or title == "Threads 貼文":
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
                app.logger.info(f"✓ 從 <title> 取得: {title}")

        # 記錄爬取狀態
        app.logger.info(f"===== Threads 爬取結果 =====")
        app.logger.info(f"標題: {title}")
        app.logger.info(f"內容長度: {len(content)} 字元")
        app.logger.info(f"內容預覽: {content[:200] if content else '(無)'}")

        # 如果成功取得內容
        if content and len(content) >= 10:
            # 限制內容長度
            max_length = 2000
            if len(content) > max_length:
                content = content[:max_length] + "..."

            # 格式化內容
            formatted_content = f"【貼文內容】\n{content}"
            if author:
                formatted_content = f"【作者】\n{author}\n\n" + formatted_content

            return {
                'title': title[:100] if title else "Threads 貼文",
                'content': formatted_content,
                'url': url
            }
        else:
            # 內容不足，記錄詳細資訊並返回連結
            app.logger.warning(f"內容不足（僅 {len(content)} 字元），返回連結資訊")
            return {
                'title': "Threads 貼文連結",
                'content': f"🔗 Threads URL: {url}\n\n⚠️ 無法自動爬取完整內容（Threads 可能需要登入或使用反爬蟲機制）\n\n📝 建議：\n1. 點擊上方連結查看貼文\n2. 複製貼文文字\n3. 使用 /a 指令貼上內容重新送出",
                'url': url
            }

    except requests.exceptions.RequestException as e:
        app.logger.error(f"HTTP 請求失敗: {e}")
        import traceback
        traceback.print_exc()

        return {
            'title': "Threads 貼文連結",
            'content': f"🔗 Threads URL: {url}\n\n⚠️ 無法連線到 Threads\n錯誤: {str(e)[:100]}\n\n📝 建議：\n1. 點擊上方連結查看貼文\n2. 複製貼文文字\n3. 使用 /a 指令貼上內容重新送出",
            'url': url
        }
    except Exception as e:
        app.logger.error(f"爬取 Threads 發生未預期錯誤: {e}")
        import traceback
        traceback.print_exc()

        return {
            'title': "Threads 貼文連結",
            'content': f"🔗 Threads URL: {url}\n\n⚠️ 處理 Threads 內容時發生錯誤\n錯誤: {str(e)[:100]}\n\n📝 建議：\n1. 點擊上方連結查看貼文\n2. 複製貼文文字\n3. 使用 /a 指令貼上內容重新送出",
            'url': url
        }


def scrape_facebook_content(url):
    """使用 Apify 爬取 Facebook 內容"""
    try:
        app.logger.info(f"正在使用 Apify 爬取 Facebook: {url}")

        # 使用 Apify 的 Facebook Posts Scraper
        # 正確的輸入格式（根據官方文檔）
        run_input = {
            "startUrls": [
                {
                    "url": url  # 物件格式，包含 url 欄位
                }
            ],
            "resultsLimit": 1,  # 限制結果數量
            "captionText": False,  # 不需要圖片說明文字
        }

        # 執行 Actor - 優先使用 facebook-posts-scraper
        app.logger.info("開始執行 Apify Actor (facebook-posts-scraper)...")
        try:
            run = apify_client.actor("apify/facebook-posts-scraper").call(
                run_input=run_input,
                timeout_secs=120  # 設定超時時間為 2 分鐘
            )
        except Exception as actor_error:
            # 如果第一個失敗，嘗試備用 Actor
            app.logger.warning(f"第一個 Actor 失敗: {actor_error}")
            app.logger.info("嘗試備用 Actor (rX1OOBy5c4h27p6ph)...")
            run = apify_client.actor("rX1OOBy5c4h27p6ph").call(
                run_input=run_input,
                timeout_secs=120
            )

        app.logger.info(f"Actor 執行完成，狀態: {run.get('status')}")

        # 取得結果
        items = []
        dataset_id = run.get("defaultDatasetId")

        if not dataset_id:
            app.logger.error("無法取得 dataset ID")
            return {
                'title': "Facebook 貼文",
                'content': "Apify 爬取未返回資料集",
                'url': url
            }

        for item in apify_client.dataset(dataset_id).iterate_items():
            items.append(item)
            app.logger.info(f"取得項目: {item.keys() if item else 'None'}")

        if not items:
            app.logger.warning("Apify 返回空結果")
            # 回退到一般網頁爬取
            return scrape_web_content(url)

        # 取得第一個貼文
        post = items[0]
        app.logger.info(f"貼文資料: {post}")

        # 提取資訊（支援多種欄位名稱）
        text = (post.get('text') or post.get('postText') or
                post.get('message') or post.get('content') or '')

        title = text[:100] if text else "Facebook 貼文"
        content_parts = []

        # 貼文文字
        if text:
            content_parts.append(f"【貼文內容】\n{text}")

        # 貼文時間
        time_field = (post.get('time') or post.get('createdTime') or
                     post.get('timestamp') or post.get('date'))
        if time_field:
            content_parts.append(f"\n【發布時間】\n{time_field}")

        # 作者資訊
        author = (post.get('userName') or post.get('authorName') or
                 post.get('user') or post.get('author'))
        if author:
            content_parts.append(f"\n【作者】\n{author}")

        # 互動數據
        likes = post.get('likes') or post.get('likesCount') or 0
        comments = post.get('comments') or post.get('commentsCount') or 0
        shares = post.get('shares') or post.get('sharesCount') or 0

        if likes or comments or shares:
            content_parts.append(f"\n【互動數據】")
            if likes:
                content_parts.append(f"按讚: {likes}")
            if comments:
                content_parts.append(f"留言: {comments}")
            if shares:
                content_parts.append(f"分享: {shares}")

        content = '\n'.join(content_parts) if content_parts else "無法提取貼文內容"

        return {
            'title': title,
            'content': content,
            'url': url
        }

    except Exception as e:
        app.logger.error(f"Apify 爬取 Facebook 失敗: {e}")
        import traceback
        traceback.print_exc()

        # Facebook 無法用一般方式爬取，返回有用的資訊
        app.logger.info("Facebook 爬取失敗，返回連結資訊")
        return {
            'title': "Facebook 貼文連結",
            'content': f"🔗 Facebook URL: {url}\n\n⚠️ 由於 Facebook 的隱私設定，無法自動爬取內容。\n\n📝 如需保存貼文內容，請：\n1. 點擊上方連結查看貼文\n2. 複製貼文文字\n3. 使用 /a 指令貼上內容",
            'url': url
        }


def scrape_web_content(url):
    """爬取網頁內容"""
    try:
        # 設定 User-Agent 避免被擋
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        # 發送請求
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        # 使用 BeautifulSoup 解析 HTML
        soup = BeautifulSoup(response.content, 'lxml')

        # 移除 script 和 style 標籤
        for script in soup(["script", "style"]):
            script.decompose()

        # 取得標題
        title = soup.title.string if soup.title else "無標題"

        # 取得主要內容（嘗試多種方式）
        # 1. 嘗試取得 article 標籤
        content = ""
        article = soup.find('article')
        if article:
            content = article.get_text(separator='\n', strip=True)
        else:
            # 2. 嘗試取得 main 標籤
            main = soup.find('main')
            if main:
                content = main.get_text(separator='\n', strip=True)
            else:
                # 3. 取得 body 的文字（去除過多空白）
                content = soup.get_text(separator='\n', strip=True)

        # 清理內容：移除多餘的空行
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        content = '\n'.join(lines)

        # 限制內容長度（避免太長）
        max_length = 3000
        if len(content) > max_length:
            content = content[:max_length] + "..."

        return {
            'title': title,
            'content': content,
            'url': url
        }

    except requests.exceptions.RequestException as e:
        app.logger.error(f"爬取網頁失敗: {e}")
        return {
            'title': "爬取失敗",
            'content': f"無法爬取網頁內容：{str(e)}",
            'url': url
        }
    except Exception as e:
        app.logger.error(f"處理網頁內容時發生錯誤: {e}")
        return {
            'title': "處理失敗",
            'content': f"處理網頁內容時發生錯誤：{str(e)}",
            'url': url
        }


def generate_summary(text):
    """使用 OpenAI GPT 生成摘要"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一個專業的摘要助手。請用繁體中文生成簡潔的摘要，最多50字。"},
                {"role": "user", "content": f"請為以下內容生成摘要：\n\n{text}"}
            ],
            max_tokens=100,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # 如果 API 呼叫失敗，回傳前50字作為備用
        return text[:50]


def analyze_image_with_gpt(image_path):
    """使用 GPT-4 Vision 分析圖片內容"""
    try:
        # 讀取圖片並轉為 base64
        with open(image_path, 'rb') as image_file:
            image_data = base64.b64encode(image_file.read()).decode('utf-8')

        # 判斷圖片格式
        import imghdr
        image_type = imghdr.what(image_path)
        mime_type = f"image/{image_type}" if image_type else "image/jpeg"

        # 呼叫 GPT-4 Vision API
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "你是一個專業的圖片分析助手。請用繁體中文詳細描述圖片內容，包括主要元素、場景、文字內容（如有）等，約100-200字。"
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "請詳細描述這張圖片的內容："
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_data}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500
        )

        description = response.choices[0].message.content.strip()

        # 生成簡短摘要
        summary = generate_summary(description)

        return description, summary

    except Exception as e:
        app.logger.error(f"圖片分析失敗: {e}")
        return "圖片內容（分析失敗）", "圖片"


@app.route("/", methods=['GET'])
def home():
    return 'LINE Bot is running! Webhook endpoint: /webhook'


@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 取得文字訊息內容
        text_content = event.message.text

        # 檢查是否包含 URL
        if is_url(text_content):
            # 提取 URL
            url = extract_url(text_content)
            app.logger.info(f"===== 檢測到 URL: {url} =====")

            # 根據 URL 類型選擇爬取方式
            is_fb = is_facebook_url(url)
            is_th = is_threads_url(url)
            app.logger.info(f"===== 是否為 Facebook URL: {is_fb} =====")
            app.logger.info(f"===== 是否為 Threads URL: {is_th} =====")

            if is_fb:
                # Facebook URL - 使用 Apify 爬取
                app.logger.info("===== 使用 Facebook 處理分支 =====")
                web_data = scrape_facebook_content(url)
                category = "Facebook 筆記"
            elif is_th:
                # Threads URL - 使用 Apify 爬取
                app.logger.info("===== 使用 Threads 處理分支 =====")
                web_data = scrape_threads_content(url)
                category = "Threads 筆記"
            else:
                # 一般網頁 - 使用 BeautifulSoup
                app.logger.info("===== 使用一般網頁處理分支 =====")
                web_data = scrape_web_content(url)
                category = "網頁筆記"

            app.logger.info(f"===== 類別: {category} =====")

            # 使用 OpenAI 生成摘要（針對網頁內容）
            summary = generate_summary(web_data['content'])

            # 儲存到 Notion
            from datetime import datetime

            notion.pages.create(
                parent={"database_id": os.getenv('NOTION_DATABASE_ID')},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": web_data['title'][:100]  # 使用網頁標題
                                }
                            }
                        ]
                    },
                    "內容": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": web_data['content'][:2000]  # Notion 限制
                                }
                            }
                        ]
                    },
                    "摘要": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": summary  # AI 生成的摘要
                                }
                            }
                        ]
                    },
                    "創建時間": {
                        "date": {
                            "start": datetime.now().isoformat()
                        }
                    },
                    "類別": {
                        "select": {
                            "name": category
                        }
                    },
                    "URL": {
                        "url": url
                    }
                }
            )

            # 回傳確認訊息
            reply_text = f"已存入 Notion ({category})\n\n標題: {web_data['title']}\n摘要: {summary}"
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text[:500])]  # LINE 訊息長度限制
                )
            )

        else:
            # 原有的文字筆記處理邏輯
            # 檢查是否為文字筆記指令（/a 開頭）
            if text_content.startswith('/a '):
                # 提取 /a 後面的文字
                actual_content = text_content[3:].strip()
                category = "文字筆記"
            else:
                # 一般訊息（語音輸入）
                actual_content = text_content
                category = "語音筆記"

            # 使用 OpenAI 生成摘要
            summary = generate_summary(actual_content)

            # 儲存到 Notion
            from datetime import datetime

            notion.pages.create(
                parent={"database_id": os.getenv('NOTION_DATABASE_ID')},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": actual_content[:100]  # 使用前100字作為標題
                                }
                            }
                        ]
                    },
                    "內容": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": actual_content
                                }
                            }
                        ]
                    },
                    "摘要": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": summary  # AI 生成的摘要
                                }
                            }
                        ]
                    },
                    "創建時間": {
                        "date": {
                            "start": datetime.now().isoformat()
                        }
                    },
                    "類別": {
                        "select": {
                            "name": category
                        }
                    }
                }
            )

            # 回傳確認訊息
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"已存入 Notion ({category})：{actual_content[:50]}...")]
                )
            )


@handler.add(MessageEvent, message=AudioMessageContent)
def handle_audio_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_blob_api = MessagingApiBlob(api_client)

        # 取得語音訊息 ID
        message_id = event.message.id

        # 下載語音檔案
        message_content = line_bot_blob_api.get_message_content(message_id)

        # 儲存到臨時檔案
        with tempfile.NamedTemporaryFile(delete=False, suffix='.m4a') as temp_audio:
            temp_audio.write(message_content)
            temp_audio_path = temp_audio.name

        try:
            # 使用 Whisper API 轉換
            with open(temp_audio_path, 'rb') as audio_file:
                transcript = openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="zh"
                )

            # 使用 OpenAI 生成摘要
            summary = generate_summary(transcript.text)

            # 儲存到 Notion
            from datetime import datetime

            notion.pages.create(
                parent={"database_id": os.getenv('NOTION_DATABASE_ID')},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": transcript.text[:100]  # 使用前100字作為標題
                                }
                            }
                        ]
                    },
                    "內容": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": transcript.text
                                }
                            }
                        ]
                    },
                    "摘要": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": summary  # AI 生成的摘要
                                }
                            }
                        ]
                    },
                    "創建時間": {
                        "date": {
                            "start": datetime.now().isoformat()
                        }
                    },
                    "類別": {
                        "select": {
                            "name": "語音筆記"
                        }
                    }
                }
            )

            # 回傳文字訊息
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=transcript.text)]
                )
            )
        finally:
            # 清理臨時檔案
            os.unlink(temp_audio_path)


@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    """處理圖片訊息"""
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_blob_api = MessagingApiBlob(api_client)

        # 初始化 Google Drive（首次使用時）
        if not init_google_drive():
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="Google Drive 服務暫時無法使用，請稍後再試。")]
                )
            )
            return

        # 取得圖片訊息 ID
        message_id = event.message.id

        try:
            # 下載圖片
            message_content = line_bot_blob_api.get_message_content(message_id)

            # 儲存到臨時檔案
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_image:
                temp_image.write(message_content)
                temp_image_path = temp_image.name

            # 1. 上傳到 Google Drive
            drive_link = upload_image_to_drive(
                drive_service,
                temp_image_path,
                drive_folder_id
            )

            # 2. 使用 GPT Vision 分析圖片
            description, summary = analyze_image_with_gpt(temp_image_path)

            # 3. 儲存到 Notion
            from datetime import datetime

            notion.pages.create(
                parent={"database_id": os.getenv('NOTION_DATABASE_ID')},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": description[:100]  # 前100字作為標題
                                }
                            }
                        ]
                    },
                    "內容": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": description[:2000]  # Notion 限制
                                }
                            }
                        ]
                    },
                    "摘要": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": summary
                                }
                            }
                        ]
                    },
                    "創建時間": {
                        "date": {
                            "start": datetime.now().isoformat()
                        }
                    },
                    "類別": {
                        "select": {
                            "name": "圖片筆記"
                        }
                    },
                    "URL": {
                        "url": drive_link
                    }
                }
            )

            # 4. 回傳確認訊息
            reply_text = f"已存入 Notion (圖片筆記)\n\n{summary}\n\nGoogle Drive: {drive_link}"
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text[:500])]  # LINE 訊息長度限制
                )
            )

        except Exception as e:
            app.logger.error(f"處理圖片訊息時發生錯誤: {e}")
            import traceback
            traceback.print_exc()

            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=f"處理圖片時發生錯誤：{str(e)[:100]}")]
                )
            )
        finally:
            # 清理臨時檔案
            if 'temp_image_path' in locals():
                try:
                    os.unlink(temp_image_path)
                except:
                    pass


if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    # 關閉 debug 模式以避免 WSL 檔案系統問題
    app.run(host='0.0.0.0', port=port, debug=False)
