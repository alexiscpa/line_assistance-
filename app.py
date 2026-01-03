from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, AudioMessageContent
import os
import tempfile
from dotenv import load_dotenv
from openai import OpenAI
from notion_client import Client

load_dotenv()

app = Flask(__name__)

configuration = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
notion = Client(auth=os.getenv('NOTION_API_KEY'))


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

        # 取得語音訊息 ID
        message_id = event.message.id

        # 下載語音檔案
        message_content = line_bot_api.get_message_content(message_id)

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


if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
