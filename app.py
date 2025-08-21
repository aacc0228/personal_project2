import os
import time
import pandas as pd
import pyodbc
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
import json
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import uuid
from qdrant_client import QdrantClient
import google.generativeai as genai
import traceback

# --- 0. 從 .env 檔案載入環境變數 ---
if os.environ.get('ENV') != 'production':
    print("Running in development mode, loading .env file.")
    load_dotenv()

# --- 1. 從環境變數讀取 Google Gemini 設定 ---
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GEMINI_GENERATIVE_MODEL_NAME = os.environ.get("GEMINI_GENERATIVE_MODEL", "gemini-2.5-flash")
GEMINI_EMBEDDING_MODEL_NAME = os.environ.get("GEMINI_EMBEDDING_MODEL", "models/text-embedding-004")

# --- 2. 從環境變數讀取 GCP SQL Server 設定 (已修改) ---
GCP_SQL_SERVER = os.environ.get("GCP_SQL_SERVER")
GCP_SQL_DATABASE = os.environ.get("GCP_SQL_DATABASE")
GCP_SQL_USERNAME = os.environ.get("GCP_SQL_USERNAME")
GCP_SQL_PASSWORD = os.environ.get("GCP_SQL_PASSWORD")
ODBC_DRIVER = os.environ.get("ODBC_DRIVER", '{ODBC Driver 18 for SQL Server}')

# --- 3. 從環境變數讀取 MongoDB 設定 (已修改) ---
MONGO_CONNECTION_STRING = os.environ.get("MONGO_CONNECTION_STRING")
MONGO_DATABASE_NAME = os.environ.get("MONGO_DATABASE_NAME", "ITKnowledgeBase")
MONGO_COLLECTION_NAME = os.environ.get("MONGO_COLLECTION_NAME", "Queries")

# --- 初始化 MongoDB Client (已修改並加入 certifi) ---
import certifi  # <--- 1. 匯入 certifi

mongo_collection = None
is_mongodb_configured = bool(MONGO_CONNECTION_STRING)
if not is_mongodb_configured:
    print("警告: MongoDB 連接字串 (MONGO_CONNECTION_STRING) 未在 .env 檔案中設定。問答記錄將不會儲存。")
else:
    try:
        print("正在連接到 MongoDB...")
        
        # --- 2. 在 MongoClient 中加入 tlsCAFile 參數 ---
        mongo_client = MongoClient(
            MONGO_CONNECTION_STRING,
            tlsCAFile=certifi.where()
        )
        # --------------------------------------------------

        # 使用 ping 指令來驗證連線
        mongo_client.admin.command('ping')
        db = mongo_client[MONGO_DATABASE_NAME]
        mongo_collection = db[MONGO_COLLECTION_NAME]
        print("✅ MongoDB 用戶端初始化成功。")
    except ConnectionFailure as e:
        print(f"❌ 初始化 MongoDB 用戶端時發生連線錯誤: {e}")
        print("   請檢查：")
        print("   1. 連線字串 (MONGO_CONNECTION_STRING) 是否正確。")
        print("   2. MongoDB Atlas 的 Network Access 清單是否已加入您伺服器的 IP。")
        mongo_collection = None
        is_mongodb_configured = False
    except Exception as e:
        print(f"❌ 初始化 MongoDB 用戶端時發生未預期的錯誤: {e}")
        mongo_collection = None
        is_mongodb_configured = False

# --- 4. 從環境變數讀取 Qdrant 設定 ---
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = "factory_manuals"


# --- 初始化 Google Gemini Client ---
gemini_model = None
is_gemini_configured = bool(GOOGLE_API_KEY)
if not is_gemini_configured:
    print("警告: Google AI API 金鑰 (GOOGLE_API_KEY) 未在 .env 檔案中設定。AI 功能將無法使用。")
else:
    try:
        print("正在設定 Google Gemini API...")
        genai.configure(api_key=GOOGLE_API_KEY)
        gemini_model = genai.GenerativeModel(GEMINI_GENERATIVE_MODEL_NAME)
        gemini_model.generate_content("test", generation_config={"max_output_tokens": 5})
        print(f"✅ Google Gemini 用戶端初始化成功 (生成模型: {GEMINI_GENERATIVE_MODEL_NAME})。")
    except Exception as e:
        print(f"❌ 初始化 Google Gemini 時發生嚴重錯誤: {e}")
        gemini_model = None
        is_gemini_configured = False


# --- 初始化 Azure Cosmos DB for MongoDB Client ---
mongo_collection = None
is_mongodb_configured = bool(MONGO_CONNECTION_STRING)
if not is_mongodb_configured:
    print("警告: MongoDB 連接字串 (MONGO_CONNECTION_STRING) 未在 .env 檔案中設定。問答記錄將不會儲存。")
else:
    try:
        print("正在連接到 Azure Cosmos DB for MongoDB...")
        mongo_client = MongoClient(MONGO_CONNECTION_STRING)
        mongo_client.admin.command('ismaster')
        db = mongo_client[MONGO_DATABASE_NAME]
        mongo_collection = db[MONGO_COLLECTION_NAME]
        print("✅ Azure Cosmos DB for MongoDB 用戶端初始化成功。")
    except Exception as e:
        print(f"❌ 初始化 Azure Cosmos DB for MongoDB 用戶端時發生錯誤: {e}")
        mongo_collection = None
        is_mongodb_configured = False


# --- 初始化 Qdrant Client (強制使用 REST 模式並支援 API Key) ---
qdrant_client = None
is_qdrant_configured = bool(QDRANT_URL)
if not is_qdrant_configured:
    print("警告: Qdrant URL (QDRANT_URL) 未在 .env 檔案中設定。內部知識庫功能將無法使用。")
else:
    try:
        print(f"正在以 REST (HTTP) 模式連接到 Qdrant 於 {QDRANT_URL}...")
        if QDRANT_API_KEY:
            print("   - 使用 API Key 進行連線 (適用於雲端服務)。")
        else:
            print("   - 未使用 API Key (適用於本地端服務)。")
            
        qdrant_client = QdrantClient(
            url=QDRANT_URL, 
            api_key=QDRANT_API_KEY,
            prefer_grpc=False,
            timeout=20
        )
        qdrant_client.get_collections()
        print("✅ Qdrant 用戶端初始化成功。")
    except Exception as e:
        print(f"❌ 初始化 Qdrant 用戶端時發生嚴重錯誤: {e}")
        qdrant_client = None
        is_qdrant_configured = False

# --- 建立 Flask 應用程式 ---
app = Flask(__name__)

# --- 資料庫連線輔助函式 (已修改註解) ---
def establish_db_connection_with_retry(connection_string, retries=5, delay=10):
    last_exception = None
    for i in range(retries):
        try:
            print(f"資料庫連線嘗試: 第 {i + 1} 次...")
            connection = pyodbc.connect(connection_string, timeout=20)
            print("✅ 資料庫連線成功！")
            return connection
        except pyodbc.Error as ex:
            last_exception = ex
            # GCP SQL Server 通常沒有 Azure 的 "Serverless 喚醒" 狀態，
            # 但保留重試機制可以處理一般的網路暫時性問題。
            sqlstate = ex.args[0]
            if sqlstate in ('08001', 'HYT00'): # 連線錯誤或超時
                print(f"資料庫連線錯誤或超時 ({sqlstate})，將在 {delay} 秒後重試...")
                time.sleep(delay)
            else:
                print(f"發生非預期的資料庫錯誤 ({sqlstate})，將不會重試。")
                raise ex
    print("❌ 所有重試均失敗，無法連線至資料庫。")
    raise last_exception

# --- 功能函式 1: 從 GCP SQL Server 抓取記錄 (已修改) ---
def fetch_log_data_from_gcp_sql():
    if not all([GCP_SQL_SERVER, GCP_SQL_DATABASE, GCP_SQL_USERNAME, GCP_SQL_PASSWORD]):
        error_message = "❌ **設定錯誤**\n\n資料庫連線資訊未在 `.env` 檔案中完整設定。"
        return None, error_message
    connection_string = f'DRIVER={ODBC_DRIVER};SERVER={GCP_SQL_SERVER};DATABASE={GCP_SQL_DATABASE};UID={GCP_SQL_USERNAME};PWD={GCP_SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=yes;'
    query = "SELECT log_id, log_date, log_data, ticket_number, status FROM log_data ORDER BY log_date DESC;"
    conn = None
    try:
        conn = establish_db_connection_with_retry(connection_string)
        df = pd.read_sql(query, conn)
        return df, None
    except Exception as e:
        error_message = f"❌ **資料庫或資料處理錯誤**\n\n詳細資訊: `{e}`"
        return None, error_message
    finally:
        if conn:
            conn.close()
            print("資料庫連線已關閉。")

# --- 更新功能函式: 更新資料庫 (已修改) ---
def update_log_details_in_gcp_sql(log_id, ticket_number, status):
    if not all([GCP_SQL_SERVER, GCP_SQL_DATABASE, GCP_SQL_USERNAME, GCP_SQL_PASSWORD]):
        return False, "❌ **設定錯誤**\n\n資料庫連線資訊未在 `.env` 檔案中完整設定。"
    if not ticket_number or not ticket_number.strip():
        return False, "處理單號不可為空。"
    connection_string = f'DRIVER={ODBC_DRIVER};SERVER={GCP_SQL_SERVER};DATABASE={GCP_SQL_DATABASE};UID={GCP_SQL_USERNAME};PWD={GCP_SQL_PASSWORD};Encrypt=yes;TrustServerCertificate=yes;'
    query = "UPDATE log_data SET ticket_number = ?, status = ? WHERE log_id = ?;"
    conn = None
    try:
        conn = establish_db_connection_with_retry(connection_string)
        cursor = conn.cursor()
        cursor.execute(query, ticket_number, status, log_id)
        conn.commit()
        if cursor.rowcount == 0:
            return False, f"找不到 log_id 為 {log_id} 的記錄，或資料無變更。"
        print(f"✅ 成功更新 log_id {log_id} 的處理單號為 {ticket_number}，狀態為 {status}")
        return True, None
    except Exception as e:
        error_message = f"❌ **資料庫更新錯誤**\n\n詳細錯誤: `{e}`"
        return False, error_message
    finally:
        if conn:
            conn.close()
            print("資料庫連線已關閉。")

# --- 儲存問答記錄到 MongoDB ---
def save_qa_to_mongodb(question, answer, source):
    if not is_mongodb_configured or mongo_collection is None:
        print("MongoDB 未設定或初始化失敗，跳過儲存。")
        return
    try:
        item = {
            'id': str(uuid.uuid4()),
            '問題': question,
            '回答': answer,
            '來源': source,
            'timestamp': time.time()
        }
        result = mongo_collection.insert_one(item)
        print(f"✅ 成功將問答記錄儲存到 MongoDB (Document _id: {result.inserted_id})")
    except Exception as e:
        print(f"❌ 儲存到 MongoDB 時發生錯誤: {e}")


# --- IT 知識庫功能函式 (已修正) ---
def it_knowledge_base_qa(question):
    """
    使用 Qdrant 和 Gemini 進行 RAG (Retrieval-Augmented Generation) 來回答問題。
    """
    if not is_gemini_configured or not gemini_model or not qdrant_client:
        return "❌ AI 功能或 Qdrant 知識庫未啟用。請檢查程式啟動時的憑證設定與錯誤訊息。"

    if not question:
        return "請輸入您的IT問題。"

    # 【核心修改】稍微降低相似度門檻，給予相關結果一點容錯空間
    SEARCH_SCORE_THRESHOLD = 0.4

    try:
        # --- 步驟 1: 將問題轉換為 Embedding ---
        print(f"為問題產生 Embedding (使用 Gemini): '{question[:30]}...'")
        result = genai.embed_content(
            model=GEMINI_EMBEDDING_MODEL_NAME,
            content=question,
            task_type="RETRIEVAL_QUERY"
        )
        query_vector = result['embedding']
        print("✅ Gemini Embedding 產生成功。")

        # --- 步驟 2: 在 Qdrant 中進行向量搜尋 ---
        print(f"在 Qdrant collection '{QDRANT_COLLECTION_NAME}' 中搜尋...")
        search_results = qdrant_client.search(
            collection_name=QDRANT_COLLECTION_NAME,
            query_vector=query_vector,
            limit=50,
            with_payload=True,
            score_threshold=SEARCH_SCORE_THRESHOLD
        )
        print(f"✅ Qdrant 搜尋完成，找到 {len(search_results)} 個相關結果。")
        
        # 【核心修改】加入日誌，顯示找到的結果分數，方便未來微調
        if search_results:
            print("--- 找到的結果分數 (高於門檻) ---")
            for hit in search_results:
                print(f"   - 分數: {hit.score:.4f}, 內容: '{hit.payload.get('text', '')[:50]}...'")
            print("---------------------------------")


        # --- 步驟 3: 根據搜尋結果決定後續動作 ---
        if not search_results:
            print("在內部知識庫中找不到答案（分數低於門檻），轉向通用 AI。")
            source = "外部 (Gemini)"
            prompt = f"""
            你的任務是判斷一個問題是否與「IT技術」相關，並根據判斷結果行動。
            1.  **分析問題**：請先分析使用者的問題。
            2.  **判斷類型**：這個問題是否屬於 IT 技術領域（例如：電腦軟硬體、網路、系統、程式開發等）？
            3.  **執行動作**：
                * **如果「是」IT 相關問題**：請扮演一位非常專業的 IT 技術支援專家，提供詳細、準確且易於理解的解決方案。
                * **如果「不是」IT 相關問題**：請直接、完整地回覆以下這句話，不要有任何修改或增加：「抱歉，我只回答 IT 技術相關的問題。」
            
            使用者的問題是："{question}"
            請嚴格依照以上規則執行。
            """
            response = gemini_model.generate_content(prompt)
            final_answer = response.text
            save_qa_to_mongodb(question, final_answer, source)
            return final_answer
        else:
            print("在內部知識庫中找到相關資料，正在生成摘要性回答...")
            source = f"內部 (Qdrant: {QDRANT_COLLECTION_NAME})"
            
            context_from_qdrant = "\n---\n".join([
                f"來源文件 {i+1}:\n{hit.payload.get('text', '錯誤：找不到文字內容')}"
                for i, hit in enumerate(search_results)
            ])

            print(f"\n--- 傳送給 Gemini 的上下文 ---\n{context_from_qdrant}\n--------------------------\n")

            prompt = f"""
            你是一個精確的「資料檢索與呈現」助理。
            你的唯一任務是從下方提供的「參考資料」中，找出與「使用者的問題」最相關的完整區塊，並將該區塊「一字不漏」地呈現出來。

            「使用者的問題」是："{question}"

            --- 參考資料 ---
            {context_from_qdrant}
            --- 參考資料結束 ---

            請嚴格遵守以下規則：
            1.  **找出最相關的區塊**：在「參考資料」中定位到與「使用者的問題」最匹配的段落或條目。
            2.  **完整複製內容**：將你找到的那個完整區塊，從頭到尾，一字不漏地複製出來作為你的答案。不要進行任何摘要、改寫或省略任何細節。
            3.  **保持原始格式**：盡可能保持原始文字的換行和結構。
            4.  **找不到就說找不到**：如果「參考資料」中沒有任何內容與「使用者的問題」相關，請只回覆「根據我手邊的工廠手冊資料，找不到相關的處理方式。」。
            """
            response = gemini_model.generate_content(prompt)
            final_answer = response.text
            save_qa_to_mongodb(question, final_answer, source)
            return f"✅ 從內部知識庫找到解答：\n\n{final_answer}"

    except Exception as e:
        print(f"❌ 在與 AI 或資料庫溝通時發生錯誤:")
        traceback.print_exc() # 印出更詳細的錯誤堆疊
        return f"❌ 處理您的問題時發生錯誤: {e}"


# --- Flask 路由 (API Endpoints) ---
@app.route('/')
def index():
    is_ai_fully_configured = is_gemini_configured and is_qdrant_configured
    return render_template('index.html', is_ai_configured=is_ai_fully_configured)

@app.route('/api/logs', methods=['GET'])
def get_logs():
    # 已修改呼叫的函式名稱
    full_df, error_msg = fetch_log_data_from_gcp_sql()
    if error_msg:
        return jsonify({"error": error_msg}), 500
    if full_df is None or full_df.empty:
        return jsonify([])

    def format_status(status):
        if status == '進行中': return f"⏳ 進行中"
        elif status == '已完成': return f"✅ 已完成"
        return f"🔴 未開始"

    def format_log_content(log_string):
        if not isinstance(log_string, str): return ""
        last_bracket_pos = log_string.rfind('] ')
        content_to_display = log_string[last_bracket_pos + 2:].strip() if last_bracket_pos != -1 else log_string
        return content_to_display[:80] + '...' if len(content_to_display) > 80 else content_to_display

    full_df['status_display'] = full_df['status'].apply(format_status)
    full_df['log_date'] = pd.to_datetime(full_df['log_date'], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
    full_df['log_date'] = full_df['log_date'].fillna('')
    full_df['log_preview'] = full_df['log_data'].apply(format_log_content)
    full_df['ticket_number'] = full_df['ticket_number'].fillna('').astype(str)
    logs_list = full_df.to_dict(orient='records')
    
    return jsonify(logs_list)

@app.route('/api/ask', methods=['POST'])
def ask_question():
    if not (is_gemini_configured and is_qdrant_configured):
        return jsonify({"answer": "❌ AI 或知識庫功能未啟用。請檢查伺服器端的環境變數設定。"}), 400

    data = request.get_json()
    if not data or 'question' not in data:
        return jsonify({"answer": "錯誤：請求中未包含問題。"}), 400
    
    question = data['question']
    answer = it_knowledge_base_qa(question)
    
    return jsonify({"answer": answer})

@app.route('/api/logs/update', methods=['POST'])
def update_log_ticket():
    data = request.get_json()
    if not data or 'log_id' not in data or 'ticket_number' not in data or 'status' not in data:
        return jsonify({"error": "請求無效，缺少 log_id、ticket_number 或 status。"}), 400
    
    log_id = data['log_id']
    ticket_number = data['ticket_number']
    status = data['status']
    
    # 已修改呼叫的函式名稱
    success, message = update_log_details_in_gcp_sql(log_id, ticket_number, status)
    
    if success:
        return jsonify({"message": "更新成功！"})
    else:
        return jsonify({"error": message}), 500

# --- 啟動 Flask 應用程式 ---
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5001, debug=True)