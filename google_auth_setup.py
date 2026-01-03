"""
Google Drive OAuth 2.0 首次授權腳本

執行此腳本以完成 Google Drive 的首次授權，生成 token.json 檔案。
只需執行一次，之後 token 會自動刷新。

使用方式:
    python google_auth_setup.py
"""

import os
import pickle
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# Google Drive API 權限範圍
SCOPES = ['https://www.googleapis.com/auth/drive.file']


def authorize_google_drive():
    """
    執行 OAuth 2.0 授權流程並生成 token.json

    流程：
    1. 讀取 credentials.json
    2. 開啟瀏覽器進行 Google 授權
    3. 用戶登入並授權應用程式
    4. 生成並儲存 token.json
    5. 測試連接

    Returns:
        googleapiclient.discovery.Resource: Google Drive API 服務實例
    """
    creds = None
    token_file = os.getenv('GOOGLE_TOKEN_FILE', 'token.json')
    credentials_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

    # 檢查 credentials.json 是否存在
    if not os.path.exists(credentials_file):
        print(f"錯誤: 找不到憑證檔案 {credentials_file}")
        print("請確認已從 Google Cloud Console 下載 credentials.json")
        print("並將檔案放在專案目錄中")
        return None

    print(f"找到憑證檔案: {credentials_file}")

    # 檢查是否已有 token
    if os.path.exists(token_file):
        print(f"發現現有的 token 檔案: {token_file}")
        user_input = input("是否要重新授權？(y/n): ")
        if user_input.lower() != 'y':
            print("取消授權，使用現有 token")
            with open(token_file, 'rb') as token:
                creds = pickle.load(token)
            return build('drive', 'v3', credentials=creds)

    # 執行 OAuth 授權流程
    print("\n開始 OAuth 2.0 授權流程...")
    print("瀏覽器將會開啟，請登入您的 Google 帳號並授權應用程式")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            credentials_file,
            SCOPES
        )

        # 執行本機伺服器流程（會自動開啟瀏覽器）
        creds = flow.run_local_server(port=0)

        print("\n授權成功！")

        # 儲存憑證到 token.json
        with open(token_file, 'wb') as token:
            pickle.dump(creds, token)

        print(f"Token 已儲存到: {token_file}")

        # 建立 Drive API 服務
        service = build('drive', 'v3', credentials=creds)

        return service

    except Exception as e:
        print(f"\n授權過程發生錯誤: {e}")
        return None


def test_drive_connection(service):
    """
    測試 Google Drive 連接

    Args:
        service: Google Drive API 服務實例

    Returns:
        bool: 測試是否成功
    """
    try:
        print("\n測試 Google Drive 連接...")

        # 列出最近的 5 個檔案
        results = service.files().list(
            pageSize=5,
            fields="files(id, name, mimeType)"
        ).execute()

        items = results.get('files', [])

        if not items:
            print("您的 Google Drive 目前沒有檔案")
        else:
            print("\n成功連接到 Google Drive！")
            print("您最近的檔案：")
            for item in items:
                print(f"  - {item['name']} (ID: {item['id']})")

        return True

    except Exception as e:
        print(f"測試連接時發生錯誤: {e}")
        return False


def create_test_folder(service):
    """
    建立測試資料夾

    Args:
        service: Google Drive API 服務實例

    Returns:
        str: 資料夾 ID 或 None
    """
    try:
        folder_name = os.getenv('GOOGLE_DRIVE_FOLDER_NAME', 'LINE靈感助手')
        print(f"\n建立測試資料夾: {folder_name}")

        # 搜尋是否已存在
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        items = results.get('files', [])

        if items:
            folder_id = items[0]['id']
            print(f"資料夾已存在 (ID: {folder_id})")
            return folder_id
        else:
            # 建立新資料夾
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = service.files().create(
                body=file_metadata,
                fields='id, webViewLink'
            ).execute()

            folder_id = folder.get('id')
            folder_link = folder.get('webViewLink')
            print(f"資料夾已建立！")
            print(f"  ID: {folder_id}")
            print(f"  連結: {folder_link}")
            return folder_id

    except Exception as e:
        print(f"建立資料夾時發生錯誤: {e}")
        return None


def main():
    """
    主程式
    """
    print("=" * 60)
    print("Google Drive OAuth 2.0 授權設定")
    print("=" * 60)

    # 1. 執行授權
    service = authorize_google_drive()

    if not service:
        print("\n授權失敗，請檢查錯誤訊息")
        return

    # 2. 測試連接
    if not test_drive_connection(service):
        print("\n連接測試失敗")
        return

    # 3. 建立測試資料夾
    folder_id = create_test_folder(service)

    if folder_id:
        print("\n" + "=" * 60)
        print("設定完成！")
        print("=" * 60)
        print("\n接下來您可以：")
        print("1. 啟動 LINE Bot: python app.py")
        print("2. 在 LINE 傳送圖片進行測試")
        print("\ntoken.json 已生成，之後會自動刷新，無需重新授權")
    else:
        print("\n設定過程出現問題，請檢查錯誤訊息")


if __name__ == "__main__":
    main()
