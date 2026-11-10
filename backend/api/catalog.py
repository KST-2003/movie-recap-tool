"""Public catalogue routes: pre-generated voice and character-look samples. No login needed; these only serve
static files that were made once by generate_voice_samples.py / generate_look_samples.py."""
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from voices import VOICES, VOICE_NAMES

router = APIRouter(prefix="/api", tags=["catalog"])
SAMPLES_DIR = "voice_samples"
LOOK_SAMPLES_DIR = "look_samples"


@router.get("/voices")
def list_voices():
    """Voice catalogue with pre-generated sample URLs (only voices whose sample file exists)."""
    return [
        {**v, "sample_url": f"/api/voice-samples/{v['name']}.wav"}
        for v in VOICES if os.path.exists(os.path.join(SAMPLES_DIR, f"{v['name']}.wav"))
    ]


@router.get("/voice-samples/{filename}")
def voice_sample(filename: str):
    name = filename.removesuffix(".wav")
    path = os.path.join(SAMPLES_DIR, f"{name}.wav")
    if name not in VOICE_NAMES or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sample not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{name}-sample.wav",
                        headers={"Cache-Control": "public, max-age=604800"})


@router.get("/looks")
def list_looks():
    """Character looks (baby, monster, animal...) whose sample exists: base voice + performance instruction."""
    from looks import LOOKS
    return [{"id": i, "group": g, "label": lab, "voice": v, "sample_url": f"/api/look-samples/{i}.wav"}
            for i, g, lab, v, _ in LOOKS if os.path.exists(os.path.join(LOOK_SAMPLES_DIR, f"{i}.wav"))]


@router.get("/look-samples/{filename}")
def look_sample(filename: str):
    from looks import LOOK_IDS
    name = filename.removesuffix(".wav")
    path = os.path.join(LOOK_SAMPLES_DIR, f"{name}.wav")
    if name not in LOOK_IDS or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sample not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{name}-sample.wav",
                        headers={"Cache-Control": "public, max-age=604800"})
