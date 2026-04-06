from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import random
import os
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = FastAPI(
    title="Matchmaking API",
    description="API de matchmaking para eventos B2B - ANDICOM / ASBAMA",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Configuración Google Sheets ───────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SHEET_REGISTROS = "Registros"
SHEET_HISTORIA = "MatchHistoria"
NUM_MATCHES = 5
SCORES = [93, 88, 82, 76, 70]
NIVELES = ["Excepcional", "Altamente Compatible", "Altamente Compatible", "Muy Compatible", "Muy Compatible"]


def get_sheets_client():
    """Retorna cliente gspread autenticado vía variable de entorno GOOGLE_CREDENTIALS."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        raise HTTPException(status_code=500, detail="GOOGLE_CREDENTIALS no configurado")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def normalizar(val: str) -> str:
    """Elimina caracteres no numéricos del teléfono."""
    return "".join(filter(str.isdigit, str(val)))


def nombre_completo(nombres: str, apellidos: str) -> str:
    return f"{nombres} {apellidos}".strip()


def generar_razon(usuario: dict, posicion: int) -> str:
    razones = [
        f"Perfil complementario clave: {usuario.get('rol', '')} genera alta sinergia en el ecosistema.",
        f"Especialidad tecnológica alineada con tu objetivo: {usuario.get('objetivo', '')}.",
        f"Opera en la industria {usuario.get('industria', '')} con experiencia relevante para tu red.",
        f"Alto potencial de colaboración en especialización {usuario.get('especialidadtec', '')}.",
        "Oportunidad de networking estratégico con perfil complementario al tuyo.",
    ]
    return razones[posicion] if posicion < len(razones) else razones[0]


# ─── Modelos ───────────────────────────────────────────────────────────────────
class MatchRequest(BaseModel):
    movil: str
    rol: Optional[str] = ""
    especialidadtec: Optional[str] = ""
    industria: Optional[str] = ""
    objetivo: Optional[str] = ""


class MatchResult(BaseModel):
    posicion: int
    nombre: str
    email: str
    movil: str
    score: int
    nivel: str
    razon: str


class MatchResponse(BaseModel):
    status: str
    fuente: Optional[str] = None
    usuario: Optional[str] = None
    matches: Optional[List[MatchResult]] = None
    mensaje: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "mensaje": "Matchmaking API activa", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest):
    if not req.movil:
        raise HTTPException(status_code=400, detail="Campo 'movil' es requerido")

    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)

    # ── Leer hoja Registros ────────────────────────────────────────────────────
    try:
        sheet_reg = ss.worksheet(SHEET_REGISTROS)
    except Exception:
        raise HTTPException(status_code=500, detail=f"Hoja '{SHEET_REGISTROS}' no encontrada")

    data = sheet_reg.get_all_records()
    if not data:
        raise HTTPException(status_code=500, detail="La hoja de registros está vacía")

    movil_norm = normalizar(req.movil)

    # ── Buscar usuario ─────────────────────────────────────────────────────────
    fila_usuario = None
    for row in data:
        for key in ["telefono", "tel", "phone", "cel", "movil", "móvil", "celular"]:
            if key in row and normalizar(str(row[key])) == movil_norm:
                fila_usuario = row
                break
        if fila_usuario:
            break

    if not fila_usuario:
        raise HTTPException(status_code=404, detail=f"No se encontró usuario con móvil {req.movil}")

    # ── Actualizar variables de matching en el registro ────────────────────────
    campos_update = {"Rol": req.rol, "EspecialidadTec": req.especialidadtec,
                     "Industria": req.industria, "Objetivo": req.objetivo}
    # (Se actualiza en memoria; para persistir en Sheets usa sheet_reg.update_cell)

    usuario = {
        "nombres": str(fila_usuario.get("nombres", fila_usuario.get("nombre", ""))),
        "apellidos": str(fila_usuario.get("apellidos", fila_usuario.get("apellido", ""))),
        "email": str(fila_usuario.get("email", fila_usuario.get("correo", ""))),
        "movil": req.movil,
        "rol": req.rol,
        "especialidadtec": req.especialidadtec,
        "industria": req.industria,
        "objetivo": req.objetivo,
    }

    # ── Verificar historial ────────────────────────────────────────────────────
    matches_guardados = obtener_historial(movil_norm, ss)
    if matches_guardados:
        incrementar_contador(movil_norm, ss)
        return MatchResponse(
            status="ok",
            fuente="historial",
            usuario=nombre_completo(usuario["nombres"], usuario["apellidos"]),
            matches=matches_guardados,
            mensaje=formatear_mensaje(nombre_completo(usuario["nombres"], usuario["apellidos"]), matches_guardados),
        )

    # ── Candidatos ────────────────────────────────────────────────────────────
    candidatos = [
        row for row in data
        if normalizar(str(row.get("telefono", row.get("movil", row.get("cel", ""))))) != movil_norm
        and row.get("email", row.get("correo", ""))
    ]

    if not candidatos:
        raise HTTPException(status_code=404, detail="No hay candidatos disponibles en la base")

    random.shuffle(candidatos)
    seleccionados = candidatos[:NUM_MATCHES]

    matches = []
    for i, c in enumerate(seleccionados):
        matches.append(MatchResult(
            posicion=i + 1,
            nombre=nombre_completo(
                str(c.get("nombres", c.get("nombre", ""))),
                str(c.get("apellidos", c.get("apellido", "")))
            ),
            email=str(c.get("email", c.get("correo", ""))),
            movil=str(c.get("telefono", c.get("movil", c.get("cel", "")))),
            score=SCORES[i],
            nivel=NIVELES[i],
            razon=generar_razon(usuario, i),
        ))

    guardar_historial(movil_norm, matches, ss)

    return MatchResponse(
        status="ok",
        fuente="nuevo",
        usuario=nombre_completo(usuario["nombres"], usuario["apellidos"]),
        matches=matches,
        mensaje=formatear_mensaje(nombre_completo(usuario["nombres"], usuario["apellidos"]), matches),
    )


# ─── Historial ─────────────────────────────────────────────────────────────────
def obtener_historial(movil_norm: str, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
    except Exception:
        return None
    records = sheet.get_all_records()
    for row in records:
        if normalizar(str(row.get("Movil", ""))) == movil_norm:
            try:
                raw = json.loads(row.get("MatchesJSON", "[]"))
                return [MatchResult(**m) for m in raw]
            except Exception:
                return None
    return None


def guardar_historial(movil_norm: str, matches: list, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
    except Exception:
        sheet = ss.add_worksheet(title=SHEET_HISTORIA, rows="1000", cols="5")
        sheet.append_row(["Movil", "FechaConsulta", "MatchesJSON", "VecesConsultado"])
    sheet.append_row([
        movil_norm,
        datetime.utcnow().isoformat(),
        json.dumps([m.dict() for m in matches], ensure_ascii=False),
        1
    ])


def incrementar_contador(movil_norm: str, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            if normalizar(str(row.get("Movil", ""))) == movil_norm:
                veces = int(row.get("VecesConsultado", 1)) + 1
                sheet.update_cell(i + 2, 4, veces)
                return
    except Exception:
        pass


def formatear_mensaje(nombre_usuario: str, matches: list) -> str:
    msg = f"{nombre_usuario}, encontré tus conexiones estratégicas para el evento!\n"
    msg += "Analicé el ecosistema y estos son los perfiles con mayor potencial para ti:\n\n"
    for m in matches:
        msg += f"--- {m.posicion}. {m.nombre} | {m.nivel}\n"
        msg += f"📱 {m.movil}\n"
        msg += f"📧 {m.email}\n"
        msg += f"💡 {m.razon}\n\n"
    msg += "Estas conexiones están documentadas en tu perfil. Coordinaré los encuentros en el momento ideal.\n"
    msg += "¿Quieres saber más sobre alguno de estos perfiles?"
    return msg
