# reset_collection.py
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

# --- 從 .env 讀取設定 ---
load_dotenv()
QDRANT_URL="http://localhost:6333"
QDRANT_API_KEY=""
COLLECTION_NAME = "factory_manuals"
# 這是 Gemini "text-embedding-004" 模型產生的向量維度
VECTOR_DIMENSION = 768 

# --- 連線到 Qdrant ---
try:
    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        prefer_grpc=False, # <-- 加入這一行，強制使用 HTTP
        timeout=20
    )
    print("✅ 成功連接到 Qdrant 服務。")

    # --- 步驟 1: 刪除可能已損壞的舊集合 ---
    print(f"\n正在嘗試刪除舊的集合 '{COLLECTION_NAME}'...")
    try:
        delete_result = client.delete_collection(collection_name=COLLECTION_NAME)
        if delete_result:
            print(f"✅ 成功刪除舊集合 '{COLLECTION_NAME}'。")
        else:
            # 在某些版本中，即使集合不存在，也可能返回 False 而非拋出錯誤
            print(f"🟡 舊集合 '{COLLECTION_NAME}' 不存在或刪除時未返回成功狀態。")
    except Exception as e:
        # 捕捉可能發生的錯誤，例如集合原本就不存在
        print(f"🟡 刪除舊集合時發生提示（這通常是正常的）: {e}")

    # --- 步驟 2: 重新建立一個乾淨的新集合 ---
    print(f"\n正在重新建立新的集合 '{COLLECTION_NAME}'...")
    client.recreate_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=VECTOR_DIMENSION, distance=models.Distance.COSINE)
    )
    print(f"✅ 成功建立新的、乾淨的集合 '{COLLECTION_NAME}'，維度為 {VECTOR_DIMENSION}。")
    print("\n🎉 重置完成！現在您可以執行您的資料索引/上傳腳本了。")

except Exception as e:
    print(f"\n[🔴 發生嚴重錯誤]: {e}")
    print("請檢查您的 Qdrant 服務是否正常運行。")