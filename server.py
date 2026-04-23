from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import os
import logging


# ---------------------------------------------------------
# ENV
# ---------------------------------------------------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")


# ---------------------------------------------------------
# MongoDB bağlantısı
# ---------------------------------------------------------

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get("DB_NAME", "sisly_resort")]

# Menu tek bir doküman olarak saklanır; sabit _id ile upsert edilir.
MENU_DOC_ID = "current"


# Uygulama ve router
app = FastAPI()
api_router = APIRouter(prefix="/api")

# ---------------------------------------------------------
# MODELLER
# ---------------------------------------------------------

class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


# --------- REZERVASYON MODELLERİ ---------

class ReservationBase(BaseModel):
    name: str                       # Müşteri adı
    phone: Optional[str] = None     # Telefon numarası
    people: int                     # Kaç kişi
    date: str                       # 2025-11-25
    time: str                       # 19:30
    type: str                       # "kahvaltı" / "yemek" vb.
    note: Optional[str] = None      # Opsiyonel not

    @model_validator(mode="before")
    @classmethod
    def map_phone(cls, data):
        if isinstance(data, dict) and not data.get("phone"):
            for k in ("telefon", "phoneNumber", "tel", "mobile"):
                if data.get(k):
                    data["phone"] = data[k]
                    break
        return data


class Reservation(ReservationBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReservationCreate(ReservationBase):
    pass


# ---------------------------------------------------------
# ROUTES – GENEL
# ---------------------------------------------------------

@api_router.get("/")
async def root():
    return {"message": "Hello World"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)

    doc = status_obj.model_dump()
    doc["timestamp"] = doc["timestamp"].isoformat()

    await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for check in status_checks:
        if isinstance(check["timestamp"], str):
            check["timestamp"] = datetime.fromisoformat(check["timestamp"])
    return status_checks


# ---------------------------------------------------------
# MENÜ ENDPOINTLERİ (MongoDB)
# ---------------------------------------------------------

@api_router.get("/menu")
async def get_menu():
    try:
        doc = await db.menu.find_one({"_id": MENU_DOC_ID}, {"_id": 0})
        return doc or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.put("/menu")
async def update_menu(new_menu: Dict[str, Any]):
    try:
        if "tr" not in new_menu and "en" not in new_menu:
            raise HTTPException(
                status_code=400,
                detail="Geçersiz menü formatı: 'tr' veya 'en' bulunamadı",
            )

        await db.menu.replace_one(
            {"_id": MENU_DOC_ID},
            {**new_menu, "_id": MENU_DOC_ID},
            upsert=True,
        )
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# REZERVASYON ENDPOINTLERİ (MongoDB)
# ---------------------------------------------------------

@api_router.get("/reservations", response_model=List[Reservation])
async def list_reservations():
    raw_list = await db.reservations.find({}, {"_id": 0}).to_list(10000)
    return [Reservation(**item) for item in raw_list]


@api_router.get("/reservation", response_model=List[Reservation])
async def list_reservations_alias():
    return await list_reservations()


@api_router.post("/reservations", response_model=Reservation)
async def create_reservation(input: ReservationCreate):
    res_obj = Reservation(**input.model_dump())

    doc = res_obj.model_dump()
    doc["created_at"] = res_obj.created_at.isoformat()

    await db.reservations.insert_one(doc)
    return res_obj


@api_router.delete("/reservations/{res_id}")
async def delete_reservation(res_id: str):
    result = await db.reservations.delete_one({"id": res_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Rezervasyon bulunamadı")
    return {"status": "ok", "id": res_id}


# Router'ı uygula
app.include_router(api_router)

# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://qr.sislyresort.com",
    "http://qr.sislyresort.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Logging & shutdown
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))  # Render PORT değişkenini buradan verecek
    app.run(host="0.0.0.0", port=port)
