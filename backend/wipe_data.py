import os
import shutil
import sys
from neo4j import GraphDatabase

# Tambahkan path agar bisa meng-import configs
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def wipe_neo4j():
    from configs.settings import settings
    print("🧹 Menghapus Neo4j Knowledge Graph...")
    try:
        driver = GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
        )
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("✅ Neo4j bersih!")
    except Exception as e:
        print(f"❌ Gagal menghapus Neo4j: {e}")

def wipe_qdrant():
    print("🧹 Menghapus Qdrant Vector Memory...")
    qdrant_path = os.path.join(os.path.dirname(__file__), "data", "qdrant")
    if os.path.exists(qdrant_path):
        try:
            shutil.rmtree(qdrant_path)
            print("✅ Qdrant bersih!")
        except Exception as e:
            print(f"❌ Gagal menghapus Qdrant: {e}\n(Mungkin karena backend Uvicorn masih nyala. Matikan dulu!)")
    else:
        print("✅ Qdrant sudah kosong.")

def wipe_sqlite():
    print("🧹 Menghapus riwayat chat SQLite...")
    db_path = os.path.join(os.path.dirname(__file__), "data", "personia.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
            print("✅ SQLite bersih!")
        except Exception as e:
            print(f"❌ Gagal menghapus SQLite: {e}")
    else:
        print("✅ SQLite sudah kosong.")

if __name__ == "__main__":
    print("==================================================")
    print("⚠️ WARNING: INI AKAN MENGHAPUS SELURUH INGATAN CLAIRE!")
    print("==================================================")
    print("Pastikan kamu sudah mematikan server Uvicorn sebelum lanjut.")
    confirm = input("Yakin mau hapus semua data? (y/n): ")
    if confirm.lower() == 'y':
        wipe_neo4j()
        wipe_qdrant()
        wipe_sqlite()
        print("\n✨ Wipe selesai! Nyalakan ulang backend untuk mulai dari nol.")
    else:
        print("Operasi dibatalkan.")
