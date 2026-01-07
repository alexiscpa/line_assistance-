"""
Google Drive 服務模組
提供 Google Drive API 的核心功能：認證、資料夾管理、檔案上傳
"""

import os
import pickle
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Google Drive API 權限範圍（僅限存取本應用建立的檔案）
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# 設定日誌
logger = logging.getLogger(__name__)


def get_google_drive_service():
    """
    取得 Google Drive 服務實例

    處理 OAuth 2.0 認證流程：
    1. 檢查 token.json 是否存在或从环境变量读取
    2. 驗證 token 有效性
    3. 自動刷新過期的 token
    4. 建立並返回 Drive 服務實例

    Returns:
        googleapiclient.discovery.Resource: Google Drive API 服務實例

    Raises:
        Exception: 當找不到 credentials.json 或授權失敗時
    """
    creds = None
    token_file = os.getenv('GOOGLE_TOKEN_FILE', 'token.json')
    credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

    # 优先从环境变量读取 token（用于云部署）
    token_base64 = os.getenv('GOOGLE_DRIVE_TOKEN_BASE64')

    # 使用 logger 输出调试信息
    logger.info(f"[DEBUG] Checking env var GOOGLE_DRIVE_TOKEN_BASE64")
    logger.info(f"[DEBUG] Token exists: {token_base64 is not None}")

    if token_base64:
        logger.info(f"[DEBUG] Token length: {len(token_base64)}")
        try:
            import base64
            logger.info("[DEBUG] Decoding base64...")
            token_data = base64.b64decode(token_base64)
            logger.info(f"[DEBUG] Decoded length: {len(token_data)}")
            logger.info("[DEBUG] Loading pickle...")
            creds = pickle.loads(token_data)
            logger.info("[DEBUG] Pickle loaded successfully!")
            logger.info("从环境变量加载 Google Drive token")
        except Exception as e:
            logger.error(f"[DEBUG] Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            logger.error(f"从环境变量加载 token 失败: {e}")
    else:
        logger.info("[DEBUG] GOOGLE_DRIVE_TOKEN_BASE64 not found in env")

    # 檢查 token.json 是否存在
    if not creds and os.path.exists(token_file):
        with open(token_file, 'rb') as token:
            creds = pickle.load(token)
            logger.info("从文件加载 Google Drive token")

    # 如果沒有有效的憑證，需要進行授權
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Token 過期但可以刷新
            try:
                logger.info("Token 已過期，正在刷新...")
                creds.refresh(Request())
                logger.info("Token 已自動刷新")

                # 儲存刷新後的憑證
                with open(token_file, 'wb') as token:
                    pickle.dump(creds, token)
                logger.info("已儲存新的 token")
            except Exception as e:
                logger.error(f"Token 刷新失敗: {e}")
                logger.error("請執行 google_auth_setup.py 重新授權")
                raise Exception(f"Token 刷新失敗: {str(e)}。請執行 google_auth_setup.py 重新授權。")
        else:
            # 沒有 token 或無法刷新，需要重新授權
            logger.error("找不到有效的授權 token")
            raise Exception(
                "找不到有效的授權 token。請先執行 google_auth_setup.py 進行授權。"
            )

    # 建立 Drive API 服務
    try:
        service = build('drive', 'v3', credentials=creds)
        logger.info("Google Drive API 服務建立成功")
        return service
    except Exception as e:
        logger.error(f"建立 Google Drive API 服務失敗: {e}")
        raise


def create_folder_if_not_exists(service, folder_name):
    """
    建立 Google Drive 資料夾（如不存在）

    Args:
        service: Google Drive API 服務實例
        folder_name (str): 資料夾名稱

    Returns:
        str: 資料夾 ID

    Raises:
        HttpError: Google Drive API 錯誤
    """
    try:
        # 搜尋是否已存在同名資料夾
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        items = results.get('files', [])

        if items:
            # 資料夾已存在
            folder_id = items[0]['id']
            logger.info(f"找到現有資料夾: {folder_name} (ID: {folder_id})")
            return folder_id
        else:
            # 建立新資料夾
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(
                body=file_metadata,
                fields='id'
            ).execute()

            folder_id = folder.get('id')
            logger.info(f"已建立新資料夾: {folder_name} (ID: {folder_id})")
            return folder_id

    except HttpError as error:
        logger.error(f"建立資料夾時發生錯誤: {error}")
        raise


def upload_image_to_drive(service, image_path, folder_id):
    """
    上傳圖片到 Google Drive 並返回分享連結

    Args:
        service: Google Drive API 服務實例
        image_path (str): 本機圖片檔案路徑
        folder_id (str): 目標資料夾 ID

    Returns:
        str: 圖片的 Google Drive 分享連結

    Raises:
        HttpError: Google Drive API 錯誤
        FileNotFoundError: 找不到指定的圖片檔案
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"找不到圖片檔案: {image_path}")

    try:
        # 取得檔案名稱
        file_name = os.path.basename(image_path)

        # 判斷 MIME 類型
        import imghdr
        image_type = imghdr.what(image_path)
        mime_type = f"image/{image_type}" if image_type else "image/jpeg"

        # 準備檔案 metadata
        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }

        # 準備要上傳的媒體檔案
        media = MediaFileUpload(
            image_path,
            mimetype=mime_type,
            resumable=True
        )

        # 上傳檔案
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink, webContentLink'
        ).execute()

        file_id = file.get('id')
        logger.info(f"檔案已上傳: {file.get('name')} (ID: {file_id})")

        # 設定檔案權限為「任何人都能檢視」
        permission = {
            'type': 'anyone',
            'role': 'reader'
        }
        service.permissions().create(
            fileId=file_id,
            body=permission
        ).execute()

        logger.info(f"已設定檔案權限為公開檢視")

        # 返回分享連結
        share_link = file.get('webViewLink')
        return share_link

    except HttpError as error:
        logger.error(f"上傳圖片時發生錯誤: {error}")
        raise
    except Exception as error:
        logger.error(f"處理圖片時發生錯誤: {error}")
        raise


if __name__ == "__main__":
    # 測試程式碼（可選）
    print("此模組應該被 import 使用，而非直接執行")
    print("請使用 google_auth_setup.py 進行首次授權")
