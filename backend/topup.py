"""Pay as you go, user side: the user picks a pack of video minutes, sees the owner's payment QR, uploads the payment slip, and waits
for the admin to check it (admin side: admin/routes.py). Bought minutes live in User.credit_seconds and are used only after the
daily / monthly allowance is used up (main.create_job). Slips are private files in DATA_DIR/slips, shown by signed links only."""
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

import auth
from admin import settings as S
from config import DATA_DIR
from db import Session, TopupRequest, User

SLIP_DIR = os.path.join(DATA_DIR, "slips")
MAX_SLIP_MB = 8
MAX_PENDING = 3
LINK_SECONDS = 3600
router = APIRouter()


def kind_of(head: bytes) -> str | None:
    """File type from the first bytes (the browser's name / type is not trusted): jpg, png, webp, pdf."""
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:5] == b"%PDF-":
        return "pdf"
    return None


def read_image(upload: UploadFile, max_mb: int, allow_pdf: bool) -> tuple[bytes, str]:
    data = upload.file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File is larger than {max_mb} MB.")
    kind = kind_of(data[:16])
    if kind is None or (kind == "pdf" and not allow_pdf):
        raise HTTPException(status_code=400, detail="Please upload a picture (JPG, PNG or WEBP)" + (" or a PDF." if allow_pdf else "."))
    return data, kind


def link(name: str | None) -> str | None:
    if not name:
        return None
    exp, sig = auth.sign_file(name, LINK_SECONDS)
    return f"/api/private/{name}?exp={exp}&sig={sig}"


def packs() -> list[dict]:
    price = S.price_per_minute_thb()
    return [{"minutes": m, "price_thb": round(m * price, 2)} for m in S.topup_packs()]


def request_row(r: TopupRequest) -> dict:
    return {"id": r.id, "minutes": r.minutes, "amount_thb": r.amount_thb, "status": r.status, "note": r.note, "admin_note": r.admin_note,
            "created_at": (r.created_at.isoformat() if r.created_at and r.created_at.tzinfo else (r.created_at.isoformat() + "+00:00" if r.created_at else None)),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None}


@router.get("/api/topup")
def topup_info(user: User = Depends(auth.current_user)):
    with Session() as s:
        mine = s.execute(select(TopupRequest).where(TopupRequest.user_id == user.id).order_by(TopupRequest.id.desc()).limit(20)).scalars().all()
        credit = s.get(User, user.id).credit_seconds or 0.0
    return {"price_per_minute": S.price_per_minute_thb(), "packs": packs(), "qr_url": link(S.payment_qr_file()), "payment_note": S.payment_note(),
            "credit_minutes": round(max(0.0, credit) / 60, 1), "requests": [request_row(r) for r in mine]}


@router.post("/api/topup/requests")
def submit_slip(minutes: int = Form(...), note: str = Form(""), slip: UploadFile = File(...), user: User = Depends(auth.current_user)):
    price = S.price_per_minute_thb()
    if minutes not in S.topup_packs():
        raise HTTPException(status_code=400, detail="Pick one of the minute packs.")
    if not S.payment_qr_file():
        raise HTTPException(status_code=503, detail="Top-up is not set up yet. Please ask the admin.")
    with Session() as s:
        pending = s.execute(select(func.count()).select_from(TopupRequest).where(TopupRequest.user_id == user.id, TopupRequest.status == "pending")).scalar_one()
    if pending >= MAX_PENDING:
        raise HTTPException(status_code=429, detail="You already have top-ups waiting for the admin. Please wait for them to be checked.")
    data, kind = read_image(slip, MAX_SLIP_MB, allow_pdf=True)
    os.makedirs(SLIP_DIR, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{kind}"
    with open(os.path.join(SLIP_DIR, name), "wb") as f:
        f.write(data)
    with Session() as s:
        row = TopupRequest(user_id=user.id, minutes=minutes, price_per_minute=price, amount_thb=round(minutes * price, 2), slip_file=name, note=note.strip()[:300] or None)
        s.add(row)
        s.commit()
        return request_row(row)


@router.get("/api/private/{name}")
def private_file(name: str, exp: int, sig: str):
    """Slips and the payment QR: only through a signed, expiring link (an <img> tag cannot send a login header)."""
    name = os.path.basename(name)
    if not auth.check_signature(name, exp, sig):
        raise HTTPException(status_code=403, detail="Link expired. Reload the page to get a new one.")
    path = os.path.join(SLIP_DIR, name) if os.path.isfile(os.path.join(SLIP_DIR, name)) else (os.path.join(DATA_DIR, name) if name == S.payment_qr_file() else "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"})
