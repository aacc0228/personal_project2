import os
import uuid
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
import google.generativeai as genai
import traceback

# --- 0. 初始化與設定 ---
print("--- 開始端對端搜尋測試 ---")
load_dotenv()

# --- Gemini 設定 ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("找不到 GOOGLE_API_KEY，請在 .env 檔案中設定")
genai.configure(api_key=GOOGLE_API_KEY)
GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"
print(f"✅ Gemini API 已設定 (模型: {GEMINI_EMBEDDING_MODEL})")

# --- Qdrant 設定 ---
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)  # 本地端通常不需要 API Key
COLLECTION_NAME = "test_search_collection" # 使用一個全新的、獨立的集合名稱以避免衝突
VECTOR_DIMENSION = 768 # Gemini 'text-embedding-004' 的向量維度
print(f"✅ Qdrant 目標 URL: {QDRANT_URL}")
print(f"✅ 測試集合名稱: {COLLECTION_NAME}")

# --- 測試用的資料 ---
KNOWLEDGE_BASE_TEXT = "要重設公司內部系統的密碼，請聯繫 IT 部門，分機號碼是 #1234。"
SEARCH_QUESTION = "我忘記密碼了怎麼辦？"

try:
    # --- 步驟 1: 以 REST 模式連接到 Qdrant ---
    print("\n[步驟 1] 正在以 REST (HTTP) 模式連接到 Qdrant...")
    client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, prefer_grpc=False, timeout=20)
    print("✅ 連線成功。")

    # --- 步驟 2: 重置並建立測試集合 ---
    print(f"\n[步驟 2] 正在重置測試集合 '{COLLECTION_NAME}'...")
    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=VECTOR_DIMENSION, distance=models.Distance.COSINE)
    )
    print("✅ 集合重置成功。")

    # --- 步驟 3: 將知識庫內容向量化並存入 Qdrant ---
    print("\n[步驟 3] 正在將知識庫內容寫入 Qdrant...")
    print(f"   - 知識庫內容: '{KNOWLEDGE_BASE_TEXT}'")
    
    # 產生向量
    response = genai.embed_content(
        model=GEMINI_EMBEDDING_MODEL,
        content=[KNOWLEDGE_BASE_TEXT], # 注意：即使只有一個也要用 list 包起來
        task_type="RETRIEVAL_DOCUMENT"
    )
    knowledge_vector = response['embedding'][0]
    
    # 寫入資料庫
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(id=str(uuid.uuid4()), vector=knowledge_vector, payload={"text": KNOWLEDGE_BASE_TEXT})
        ],
        wait=True
    )
    print("✅ 知識庫內容寫入成功。")
    
    # 驗證寫入
    count_result = client.count(collection_name=COLLECTION_NAME, exact=True)
    if count_result.count != 1:
        raise Exception(f"寫入驗證失敗！預期 count 為 1，實際為 {count_result.count}")
    print("✅ 寫入後數量驗證成功 (count=1)。")

    # --- 步驟 4: 將問題向量化並執行搜尋 ---
    print("\n[步驟 4] 正在用您的問題執行搜尋...")
    print(f"   - 您的問題: '{SEARCH_QUESTION}'")
    
    # 產生問題的向量
    response = genai.embed_content(
        model=GEMINI_EMBEDDING_MODEL,
        content=[SEARCH_QUESTION],
        task_type="RETRIEVAL_QUERY"
    )
    query_vector = response['embedding'][0]
    
    # 執行搜尋
    search_results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=1,
        with_payload=True
    )
    print("✅ 搜尋指令執行完畢。")

    # --- 步驟 5: 分析搜尋結果 ---
    print("\n--- 最終搜尋結果分析 ---")
    if not search_results:
        print("\n[🔴 測試失敗!] 搜尋沒有返回任何結果。")
        print("這表示即使在最簡單的測試中，搜尋功能也無法找到剛才存入的資料。")
        print("這是一個非常深層的問題，強烈建議您帶著此腳本和結果，聯繫 Qdrant 官方支援。")
    else:
        top_hit = search_results[0]
        print("\n[🎉 測試成功!] 成功找到了相關的知識庫內容！")
        print(f"   - 相似度分數: {top_hit.score:.4f}")
        print(f"   - 找到的內容: '{top_hit.payload.get('text')}'")
        print("\n這證明了您的本地 Qdrant、Python 環境和 Gemini Embedding 功能都可以正常協同工作。")
        print("您主應用程式中『找不到內容』的問題，很可能出在以下幾點：")
        print("  1. 相似度門檻太高: 您主程式中的 `SEARCH_SCORE_THRESHOLD` 可能設得太高，嘗試調低它（例如 `0.7`）或暫時移除。")
        print("  2. 資料索引問題: 請確認您用來上傳大量資料的 UPLOAD 程式，也已經加入了 `prefer_grpc=False` 的設定。")
        print("  3. 檔案內容問題: 您上傳的檔案可能本身是空的，或 `unstructured` 套件無法正確解析其內容。")

except Exception as e:
    print(f"\n[🔴 執行期間發生嚴重錯誤]:")
    traceback.print_exc()

