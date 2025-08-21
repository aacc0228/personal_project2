# test_write.py
import os
import numpy as np
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models

# --- 從 .env 讀取設定 ---
load_dotenv()
QDRANT_URL="http://localhost:6333"
QDRANT_API_KEY=""
COLLECTION_NAME = "factory_manuals"
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

    # --- 步驟 1: 刪除並重新建立一個乾淨的集合 ---
    print(f"\n[步驟 1] 正在重置集合 '{COLLECTION_NAME}'...")
    try:
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=VECTOR_DIMENSION, distance=models.Distance.COSINE)
        )
        print(f"✅ 成功重置集合。")
    except Exception as e:
        print(f"🔴 重置集合時發生錯誤: {e}")
        exit() # 如果重置失敗，則終止程式

    # --- 步驟 2: 嘗試寫入一個假的向量 ---
    print(f"\n[步驟 2] 正在嘗試向 '{COLLECTION_NAME}' 寫入一個測試向量...")
    try:
        # 建立一個符合維度的隨機假向量
        dummy_vector = np.random.rand(VECTOR_DIMENSION).tolist()
        
        # 使用 upsert 操作寫入資料
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=1, # 給定一個簡單的 ID
                    vector=dummy_vector,
                    payload={"test": "true"}
                )
            ],
            wait=True # 等待操作完成
        )
        print("✅ 成功執行 upsert (寫入) 操作。")
    except Exception as e:
        print(f"🔴 寫入測試向量時發生嚴重錯誤: {e}")
        exit()

    # --- 步驟 3: 馬上檢查集合狀態 ---
    print(f"\n[步驟 3] 正在檢查寫入後的集合狀態...")
    try:
        collection_info = client.get_collection(collection_name=COLLECTION_NAME)
        
        # 使用相容性檢查
        vector_count = collection_info.vectors_count if hasattr(collection_info, 'vectors_count') else None
        
        print("\n--- 最終檢查結果 ---")
        print(f"集合名稱: '{COLLECTION_NAME}'")
        print(f"向量總數 (vectors_count): {vector_count}")
        print("--------------------")

        if vector_count == 1:
            print("\n[🎉 測試成功!] 成功寫入並讀取到 1 個向量。")
            print("這表示您的 Qdrant 服務本身是正常的。")
            print("問題 100% 出在您自己的『資料索引腳本』中，它可能在呼叫 client.upsert() 時失敗了但您沒有發現。請檢查您的索引腳本。")
        else:
            print(f"\n[🔴 測試失敗!] 即使在最簡單的寫入測試後，向量數量仍然是 '{vector_count}' 而不是 1。")
            print("這強烈表示您的 Qdrant 服務實例本身存在問題。")
            print("👉 建議解決方案：")
            print("  1. 如果使用 Docker，請檢查 Docker 的日誌: `docker logs <您的Qdrant容器名稱>`，看是否有錯誤訊息。")
            print("  2. 嘗試停止並刪除現有的 Qdrant 容器，然後拉取最新的 Qdrant 映像檔並重新建立一個容器。")

    except Exception as e:
        print(f"🔴 在最終檢查時發生錯誤: {e}")

except Exception as e:
    print(f"\n[🔴 無法連接到 Qdrant]: {e}")