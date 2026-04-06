from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import os
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = FastAPI(
    title="Matchmaking API — ASBAMA 2026",
    description="Motor de matching para el 4° Congreso Bananero Colombiano",
    version="2.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Config ────────────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "")
SHEET_REGISTROS  = "Participantes"
SHEET_RESULTADOS = "MatchResultados"
SHEET_HISTORIA   = "MatchHistoria"
DEFAULT_TOP_N    = 5

# Pesos del scoring ASBAMA
W_OFRECE_BUSCA = 0.45
W_BUSCA_OFRECE = 0.45
W_ROL          = 0.10

ROLES_COMPLEMENTARIOS = [
    {"Productor / Finca", "Proveedor de insumos agrícolas"},
    {"Productor / Finca", "Proveedor de maquinaria / tecnología"},
    {"Productor / Finca", "Empresa de logística / transporte / puerto"},
    {"Productor / Finca", "Empresa de certificación / auditoría"},
    {"Productor / Finca", "Consultoría / servicios técnicos"},
    {"Productor / Finca", "Academia / centro de investigación"},
    {"Proveedor de insumos agrícolas", "Consultoría / servicios técnicos"},
    {"Academia / centro de investigación", "Proveedor de insumos agrícolas"},
]

NIVELES_SCORE = [
    (90, "Excepcional"),
    (75, "Altamente Compatible"),
    (60, "Muy Compatible"),
    (0,  "Compatible"),
]


# ─── Sheets client ─────────────────────────────────────────────────────────────
def get_sheets_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        raise HTTPException(status_code=500, detail="GOOGLE_CREDENTIALS no configurado")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


# ─── Helpers ───────────────────────────────────────────────────────────────────
def normalizar(val) -> str:
    return "".join(filter(str.isdigit, str(val)))


def nombre_completo(nombres: str, apellidos: str) -> str:
    return f"{nombres} {apellidos}".strip()


def parsear_multivalor(val: str) -> set:
    if not val or str(val).strip() in ("", "nan", "None"):
        return set()
    return {v.strip() for v in str(val).split(";") if v.strip()}


def jaccard(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


def roles_complementarios(rol_a: str, rol_b: str) -> bool:
    par = {rol_a.strip(), rol_b.strip()}
    return any(par == c for c in ROLES_COMPLEMENTARIOS)


def calcular_score(a: dict, b: dict) -> float:
    ofrece_a = parsear_multivalor(a.get("ofrece", ""))
    busca_a  = parsear_multivalor(a.get("busca",  ""))
    ofrece_b = parsear_multivalor(b.get("ofrece", ""))
    busca_b  = parsear_multivalor(b.get("busca",  ""))
    rol_a    = str(a.get("rol", "")).strip()
    rol_b    = str(b.get("rol", "")).strip()

    s = (
        W_OFRECE_BUSCA * jaccard(ofrece_a, busca_b) +
        W_BUSCA_OFRECE * jaccard(ofrece_b, busca_a) +
        W_ROL          * (1.0 if roles_complementarios(rol_a, rol_b) else 0.0)
    )
    # Penalizar misma empresa
    empresa_a = str(a.get("empresa", "")).strip().lower()
    empresa_b = str(b.get("empresa", "")).strip().lower()
    if empresa_a and empresa_a == empresa_b:
        s *= 0.1

    return round(min(s * 100, 100), 1)


def nivel_desde_score(score: float) -> str:
    for umbral, nivel in NIVELES_SCORE:
        if score >= umbral:
            return nivel
    return "Compatible"


def razon_match(a: dict, b: dict) -> str:
    ofrece_b = parsear_multivalor(b.get("ofrece", ""))
    busca_a  = parsear_multivalor(a.get("busca",  ""))
    comun    = ofrece_b & busca_a
    if comun:
        item = next(iter(comun))
        return f"{b.get('nombres', '')} ofrece '{item}', que es exactamente lo que buscas en este evento."
    if roles_complementarios(str(a.get("rol", "")), str(b.get("rol", ""))):
        return f"Roles complementarios: {a.get('rol','')} ↔ {b.get('rol','')}, alta sinergia en la cadena bananera."
    return "Perfil estratégico con potencial de colaboración en el sector bananero."


def buscar_columna(row: dict, *candidatos) -> str:
    """
    Busca el primer candidato que exista como clave en row (case-insensitive,
    ignorando tildes) y devuelve su valor. Si ninguno coincide, devuelve "".
    """
    import unicodedata
    def normalizar_key(k):
        k = k.lower().strip()
        return unicodedata.normalize("NFKD", k).encode("ascii", "ignore").decode("ascii")

    row_normalized = {normalizar_key(k): v for k, v in row.items()}
    for c in candidatos:
        val = row_normalized.get(normalizar_key(c), None)
        if val is not None:
            return str(val)
    return ""


def leer_participantes(ss) -> list:
    try:
        sheet = ss.worksheet(SHEET_REGISTROS)
    except Exception:
        raise HTTPException(status_code=500, detail=f"Hoja '{SHEET_REGISTROS}' no encontrada")
    records = sheet.get_all_records()
    result = []
    for r in records:
        tel_raw = buscar_columna(r,
            "Teléfono móvil", "Telefono movil", "telefono", "móvil", "movil", "celular", "tel")
        result.append({
            "telefono" : normalizar(tel_raw),
            "nombres"  : buscar_columna(r, "Nombres", "nombres", "nombre"),
            "apellidos": buscar_columna(r, "Apellidos", "apellidos", "apellido"),
            "email"    : buscar_columna(r, "Email", "email", "correo"),
            "empresa"  : buscar_columna(r, "Empresa/Institución", "Empresa/Institucion", "empresa", "institucion"),
            "cargo"    : buscar_columna(r, "Cargo", "cargo"),
            "rol"      : buscar_columna(r,
                "¿Cual es tu rol principal en la cadena de valor del banano?",
                "Cual es tu rol principal en la cadena de valor del banano?",
                "rol principal", "rol"),
            "busca"    : buscar_columna(r,
                "En este evento, ¿qué estás buscando principalmente? (máximo 3 opciones) ",
                "En este evento, que estas buscando principalmente? (maximo 3 opciones)",
                "En este evento, ¿qué estás buscando principalmente?",
                "busca", "buscando"),
            "ofrece"   : buscar_columna(r,
                "¿Qué ofreces a otros participantes del evento? (máximo 3 opciones)",
                "Que ofreces a otros participantes del evento? (maximo 3 opciones)",
                "¿Qué ofreces a otros participantes del evento?",
                "ofrece", "ofreces"),
            "tipo"     : buscar_columna(r, "Tipo entrada", "tipo entrada", "tipo"),
        })
    return result


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────
class MatchRequest(BaseModel):
    movil: str


class BatchRequest(BaseModel):
    registros: Optional[List[dict]] = None
    top_n: Optional[int] = DEFAULT_TOP_N


class MatchResult(BaseModel):
    posicion : int
    nombre   : str
    email    : str
    movil    : str
    empresa  : str
    cargo    : str
    score    : float
    nivel    : str
    razon    : str


class MatchResponse(BaseModel):
    status  : str
    fuente  : Optional[str] = None
    usuario : Optional[str] = None
    matches : Optional[List[MatchResult]] = None
    mensaje : Optional[str] = None


class BatchResponse(BaseModel):
    status        : str
    total_usuarios: int
    total_matches : int
    matches       : List[dict]
    mensaje       : Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "mensaje": "ASBAMA Matchmaking API v2.1 activa", "version": "2.1.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/debug")
def debug():
    """
    Muestra las columnas exactas del Sheet y un registro de muestra
    con los valores mapeados. Usar solo en desarrollo.
    """
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    try:
        sheet = ss.worksheet(SHEET_REGISTROS)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    records = sheet.get_all_records()
    if not records:
        return {"columnas": [], "muestra_raw": {}, "muestra_mapeada": {}}
    columnas = list(records[0].keys())
    participantes = leer_participantes(ss)
    return {
        "total_registros" : len(records),
        "columnas"        : columnas,
        "muestra_raw"     : records[0],
        "muestra_mapeada" : participantes[0] if participantes else {},
    }


@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest):
    if not req.movil:
        raise HTTPException(status_code=400, detail="Campo 'movil' es requerido")

    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    movil_norm = normalizar(req.movil)

    # ── Historial ──────────────────────────────────────────────────────────────
    matches_guardados = obtener_historial(movil_norm, ss)
    if matches_guardados:
        incrementar_contador(movil_norm, ss)
        participantes = leer_participantes(ss)
        usuario_row = next((p for p in participantes if p["telefono"] == movil_norm), None)
        nombre_u = nombre_completo(usuario_row["nombres"], usuario_row["apellidos"]) if usuario_row else req.movil
        return MatchResponse(
            status="ok", fuente="historial", usuario=nombre_u,
            matches=matches_guardados,
            mensaje=formatear_mensaje(nombre_u, matches_guardados),
        )

    # ── Leer participantes ─────────────────────────────────────────────────────
    participantes = leer_participantes(ss)
    usuario_row = next((p for p in participantes if p["telefono"] == movil_norm), None)
    if not usuario_row:
        raise HTTPException(status_code=404, detail=f"No se encontró usuario con móvil {req.movil}")

    # ── Calcular scores (un match por empresa) ─────────────────────────────────
    candidatos = [p for p in participantes if p["telefono"] != movil_norm]

    # Dedup: quedarse con el mejor score por empresa
    empresa_mejor: dict = {}  # empresa_lower -> (score, candidato)
    for c in candidatos:
        score = calcular_score(usuario_row, c)
        emp = str(c.get("empresa", "")).strip().lower()
        if emp not in empresa_mejor or score > empresa_mejor[emp][0]:
            empresa_mejor[emp] = (score, c)

    scored = sorted(empresa_mejor.values(), key=lambda x: x[0], reverse=True)
    top = scored[:DEFAULT_TOP_N]

    matches = [
        MatchResult(
            posicion = i + 1,
            nombre   = nombre_completo(c["nombres"], c["apellidos"]),
            email    = c["email"],
            movil    = c["telefono"],
            empresa  = c["empresa"],
            cargo    = c["cargo"],
            score    = score,
            nivel    = nivel_desde_score(score),
            razon    = razon_match(usuario_row, c),
        )
        for i, (score, c) in enumerate(top)
    ]

    guardar_historial(movil_norm, matches, ss)
    nombre_u = nombre_completo(usuario_row["nombres"], usuario_row["apellidos"])
    return MatchResponse(
        status="ok", fuente="nuevo", usuario=nombre_u,
        matches=matches,
        mensaje=formatear_mensaje(nombre_u, matches),
    )


@app.post("/batch-match", response_model=BatchResponse)
def batch_match(req: BatchRequest):
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    top_n = req.top_n or DEFAULT_TOP_N

    if req.registros:
        participantes = []
        for r in req.registros:
            tel_raw = buscar_columna(r,
                "Teléfono móvil", "Telefono movil", "telefono", "móvil", "movil")
            participantes.append({
                "telefono" : normalizar(tel_raw),
                "nombres"  : buscar_columna(r, "Nombres", "nombres"),
                "apellidos": buscar_columna(r, "Apellidos", "apellidos"),
                "email"    : buscar_columna(r, "Email", "email"),
                "empresa"  : buscar_columna(r, "Empresa/Institución", "empresa"),
                "cargo"    : buscar_columna(r, "Cargo", "cargo"),
                "rol"      : buscar_columna(r,
                    "¿Cual es tu rol principal en la cadena de valor del banano?",
                    "Cual es tu rol principal en la cadena de valor del banano?", "rol"),
                "busca"    : buscar_columna(r,
                    "En este evento, ¿qué estás buscando principalmente? (máximo 3 opciones) ",
                    "En este evento, que estas buscando principalmente?", "busca"),
                "ofrece"   : buscar_columna(r,
                    "¿Qué ofreces a otros participantes del evento? (máximo 3 opciones)",
                    "Que ofreces a otros participantes del evento?", "ofrece"),
                "tipo"     : buscar_columna(r, "Tipo entrada", "tipo"),
            })
    else:
        participantes = leer_participantes(ss)

    if not participantes:
        raise HTTPException(status_code=400, detail="No hay participantes para procesar")

    df = pd.DataFrame(participantes)
    all_matches = []

    for i, usuario in df.iterrows():
        candidatos_df = df[df["telefono"] != usuario["telefono"]]
        empresa_mejor: dict = {}
        for _, c in candidatos_df.iterrows():
            score = calcular_score(usuario.to_dict(), c.to_dict())
            emp = str(c.get("empresa", "")).strip().lower()
            if emp not in empresa_mejor or score > empresa_mejor[emp][0]:
                empresa_mejor[emp] = (score, c.to_dict())

        scored = sorted(empresa_mejor.values(), key=lambda x: x[0], reverse=True)
        for pos, (score, c) in enumerate(scored[:top_n]):
            all_matches.append({
                "posicion"       : pos + 1,
                "tel_usuario"    : usuario["telefono"],
                "nombre_usuario" : nombre_completo(usuario["nombres"], usuario["apellidos"]),
                "email_usuario"  : usuario["email"],
                "empresa_usuario": usuario["empresa"],
                "tel_match"      : c["telefono"],
                "nombre_match"   : nombre_completo(c["nombres"], c["apellidos"]),
                "email_match"    : c["email"],
                "empresa_match"  : c["empresa"],
                "cargo_match"    : c["cargo"],
                "score"          : score,
                "nivel"          : nivel_desde_score(score),
                "razon"          : razon_match(usuario.to_dict(), c),
            })

    try:
        try:
            sheet_res = ss.worksheet(SHEET_RESULTADOS)
            sheet_res.clear()
        except Exception:
            sheet_res = ss.add_worksheet(title=SHEET_RESULTADOS, rows=str(len(all_matches)+10), cols="15")
        if all_matches:
            headers = list(all_matches[0].keys())
            rows = [headers] + [[m.get(h, "") for h in headers] for m in all_matches]
            sheet_res.update(rows, "A1")
    except Exception:
        pass

    return BatchResponse(
        status="ok",
        total_usuarios=len(participantes),
        total_matches=len(all_matches),
        matches=all_matches,
        mensaje=f"Modelo corrido: {len(participantes)} participantes × top-{top_n}. Resultados en '{SHEET_RESULTADOS}'.",
    )


# ─── Historial ─────────────────────────────────────────────────────────────────
def obtener_historial(movil_norm: str, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
        records = sheet.get_all_records()
    except Exception:
        return None
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
        sheet = ss.add_worksheet(title=SHEET_HISTORIA, rows="2000", cols="5")
        sheet.append_row(["Movil", "FechaConsulta", "MatchesJSON", "VecesConsultado"])
    sheet.append_row([
        movil_norm,
        datetime.utcnow().isoformat(),
        json.dumps([m.dict() for m in matches], ensure_ascii=False),
        1,
    ])


def incrementar_contador(movil_norm: str, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            if normalizar(str(row.get("Movil", ""))) == movil_norm:
                sheet.update_cell(i + 2, 4, int(row.get("VecesConsultado", 1)) + 1)
                return
    except Exception:
        pass


# ─── Mensaje WhatsApp ──────────────────────────────────────────────────────────
def formatear_mensaje(nombre_usuario: str, matches: list) -> str:
    msg  = f"🌿 *{nombre_usuario}*, encontré tus conexiones estratégicas para el Congreso Bananero 2026!\n\n"
    msg += "Analicé todos los perfiles del evento y estos son los más afines a ti:\n\n"
    for m in matches:
        msg += f"*{m.posicion}. {m.nombre}* — {m.nivel} ({m.score}pts)\n"
        msg += f"🏢 {m.empresa}\n"
        msg += f"📱 {m.movil}\n"
        msg += f"💡 {m.razon}\n\n"
    msg += "¿Quieres saber más sobre alguno de estos perfiles o coordinar un encuentro?"
    return msg
