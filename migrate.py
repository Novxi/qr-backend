"""
Tek seferlik migration: menu.json ve reservations.json içindeki verileri
MongoDB'ye yükler. Idempotent — aynı veriler zaten varsa duplicate oluşturmaz.

Kullanım:
    python migrate.py

Gereksinim: .env dosyasında MONGO_URL ve DB_NAME ayarlı olmalı.
"""

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
import asyncio
import json
import os
import sys

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MENU_FILE = ROOT_DIR / "menu.json"
RES_FILE = ROOT_DIR / "reservations.json"
MENU_DOC_ID = "current"


async def migrate_menu(db) -> None:
    if not MENU_FILE.exists():
        print(f"[menu] {MENU_FILE.name} bulunamadı, atlanıyor.")
        return

    with MENU_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not data:
        print("[menu] Dosya boş, atlanıyor.")
        return

    await db.menu.replace_one(
        {"_id": MENU_DOC_ID},
        {**data, "_id": MENU_DOC_ID},
        upsert=True,
    )
    print(f"[menu] Yüklendi. Kategoriler: "
          f"tr={len(data.get('tr', {}).get('categories', []))}, "
          f"en={len(data.get('en', {}).get('categories', []))}")


async def migrate_reservations(db) -> None:
    if not RES_FILE.exists():
        print(f"[reservations] {RES_FILE.name} bulunamadı, atlanıyor.")
        return

    raw = RES_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        print("[reservations] Dosya boş, atlanıyor.")
        return

    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        print("[reservations] Kayıt yok, atlanıyor.")
        return

    existing_ids = set()
    async for doc in db.reservations.find({}, {"id": 1, "_id": 0}):
        if "id" in doc:
            existing_ids.add(doc["id"])

    new_docs = [r for r in data if r.get("id") and r["id"] not in existing_ids]
    skipped = len(data) - len(new_docs)

    if not new_docs:
        print(f"[reservations] Hepsi zaten yüklü ({skipped} atlandı).")
        return

    await db.reservations.insert_many(new_docs)
    print(f"[reservations] {len(new_docs)} yeni kayıt eklendi, {skipped} atlandı.")


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "sisly_resort")

    if not mongo_url or "localhost" in mongo_url:
        print("HATA: MONGO_URL .env dosyasında Atlas connection string olarak ayarlı olmalı.")
        sys.exit(1)

    print(f"Bağlanılıyor: DB='{db_name}'")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    try:
        # Sağlık kontrolü
        await client.admin.command("ping")
        print("Bağlantı OK.\n")

        await migrate_menu(db)
        await migrate_reservations(db)

        print("\nMigration tamamlandı.")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
