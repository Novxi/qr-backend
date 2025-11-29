# ---------------------------------------------------------
# ENV & PATH
# ---------------------------------------------------------
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# ---------------------------------------------------------
# MENÜ DOSYASI (menu.json) OKUMA / YAZMA YARDIMCI FONKSİYONLARI
# ---------------------------------------------------------

MOCK_FILE = ROOT_DIR / "menu.json"


def read_menu() -> Dict[str, Any]:
    """menu.json içinden menü verisini okur."""
    if not MOCK_FILE.exists():
        return {}
    with MOCK_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_menu(new_menu: Dict[str, Any]) -> None:
    """Menü verisini menu.json dosyasına yazar."""
    with MOCK_FILE.open("w", encoding="utf-8") as f:
        json.dump(new_menu, f, ensure_ascii=False, indent=2)



# ---------------------------------------------------------
# REZERVASYONLAR İÇİN JSON DOSYASI
# ---------------------------------------------------------

RES_FILE = ROOT_DIR / "reservations.json"


def load_reservations() -> List[Dict[str, Any]]:
    """reservations.json dosyasını liste olarak okur."""
    if not RES_FILE.exists():
        return []
    try:
        raw = RES_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def save_reservations(data: List[Dict[str, Any]]) -> None:
    """Verilen listeyi reservations.json dosyasına yazar."""
    RES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------
# MongoDB bağlantısı (sadece /status endpointleri için)
# ---------------------------------------------------------

mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get("DB_NAME", "test_db")]

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

from typing import List, Tuple, Dict, Any, Optional  # en üstte Optional zaten ekli

class ReservationBase(BaseModel):
    name: str                       # Müşteri adı
    phone: Optional[str] = None     # Telefon numarası
    people: int                     # Kaç kişi
    date: str                       # 2025-11-25
    time: str                       # 19:30
    type: str                       # "kahvaltı" / "yemek" vb.
    note: Optional[str] = None      # Opsiyonel not



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
# MENÜ ENDPOINTLERİ
# ---------------------------------------------------------

@api_router.get("/menu")
async def get_menu():
    """mock.js içindeki menuData'yı döner."""
    try:
        data = read_menu()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.put("/menu")
async def update_menu(new_menu: Dict[str, Any]):
    """Admin panelden gelen menuData'yı mock.js içine yazar."""
    try:
        if "tr" not in new_menu and "en" not in new_menu:
            raise HTTPException(
                status_code=400,
                detail="Geçersiz menü formatı: 'tr' veya 'en' bulunamadı",
            )

        write_menu(new_menu)
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# REZERVASYON ENDPOINTLERİ (JSON DOSYA TABANLI)
# ---------------------------------------------------------

@api_router.get("/reservations", response_model=List[Reservation])
async def list_reservations():
    """
    Tüm rezervasyonları getir.
    GET /api/reservations
    """
    raw_list = load_reservations()
    # Pydantic datetime'ı kendisi parse ediyor (ISO string → datetime)
    return [Reservation(**item) for item in raw_list]


@api_router.get("/reservation", response_model=List[Reservation])
async def list_reservations_alias():
    """
    /api/reservation isteyen yerler için alias.
    """
    return await list_reservations()


@api_router.post("/reservations", response_model=Reservation)
async def create_reservation(input: ReservationCreate):
    """
    Yeni rezervasyon oluştur.
    POST /api/reservations
    """
    res_obj = Reservation(**input.model_dump())
    data = load_reservations()

    # datetime JSON'a çevrilirken patlamasın diye stringe çeviriyoruz
    doc = res_obj.model_dump()
    doc["created_at"] = res_obj.created_at.isoformat()

    data.append(doc)
    save_reservations(data)
    return res_obj


@api_router.delete("/reservations/{res_id}")
async def delete_reservation(res_id: str):
    """
    Rezervasyonu ID'ye göre sil.
    DELETE /api/reservations/{id}
    """
    data = load_reservations()
    new_data = [r for r in data if r.get("id") != res_id]

    if len(new_data) == len(data):
        raise HTTPException(status_code=404, detail="Rezervasyon bulunamadı")

    save_reservations(new_data)
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
