from fastapi import APIRouter
from fastapi.responses import Response
import qrcode
from io import BytesIO

router = APIRouter(tags=["qr"])


@router.get("/qr/{data:path}")
async def generate_qr(data: str):
    """Generate QR code image for any data"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1a1a2e", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return Response(content=buffer.getvalue(), media_type="image/png")
