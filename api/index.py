from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import os
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = FastAPI(
    title="Matchmaking API — ASBAMA 2026",
    description="Motor de matching para el 4° Congreso Bananero Colombiano",
    version="2.0.0"
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
W_OFRECE_BUSCA = 0.45   # lo que A ofrece cubre lo que B busca
W_BUSCA_OFRECE = 0.45   # lo que B ofrece cubre lo que A busca
W_ROL          = 0.10   # complementariedad de rol

# Roles complementarios (pares que suman valor)
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
    """Convierte 'A;B;;C' en {'A','B','C'} eliminando vacíos."""
    if not val:
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
    """Score 0-100 entre dos participantes."""
    ofrece_a = parsear_multivalor(a.get("ofrece", ""))
    busca_a  = parsear_multivalor(a.get("busca",  ""))
    ofrece_b = parsear_multivalor(b.get("ofrece", ""))
    busca_b  = parsear_multivalor(b.get("busca",  ""))
    rol_a    = str(a.get("rol", ""))
    rol_b    = str(b.get("rol", ""))

    # A ofrece lo que B busca + B ofrece lo que A busca
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
        return f"{b.get('nombres','')} ofrece '{item}', que es exactamente lo que buscas en este evento."
    if roles_complementarios(str(a.get('rol','')), str(b.get('rol',''))):
        return f"Roles complementarios: {a.get('rol','')} ↔ {b.get('rol','')}, alta sinergia en la cadena bananera."
    return "Perfil estratégico con potencial de colaboración en el sector bananero."


def leer_participantes(ss) -> list:
    """Lee la hoja Participantes y devuelve lista de dicts normalizados."""
    try:
        sheet = ss.worksheet(SHEET_REGISTROS)
    except Exception:
        raise HTTPException(status_code=500, detail=f"Hoja '{SHEET_REGISTROS}' no encontrada")
    records = sheet.get_all_records()
    result = []
    for r in records:
        # Mapear columnas con nombres exactos del CSV de ASBAMA
        tel_raw = (
            r.get("Teléfono móvil") or
            r.get("Telefono movil") or
            r.get("telefono") or
            r.get("móvil") or
            r.get("movil") or ""
        )
        result.append({
            "telefono"  : normalizar(tel_raw),
            "nombres"   : str(r.get("Nombres", r.get("nombres", ""))),
            "apellidos" : str(r.get("Apellidos", r.get("apellidos", ""))),
            "email"     : str(r.get("Email", r.get("email", r.get("correo", "")))),
            "empresa"   : str(r.get("Empresa/Institución", r.get("empresa", ""))),
            "cargo"     : str(r.get("Cargo", r.get("cargo", ""))),
            "rol"       : str(r.get("¿Cual es tu rol principal en la cadena de valor del banano?", r.get("rol", ""))),
            "busca"     : str(r.get("En este evento, ¿qué estás buscando principalmente? (máximo 3 opciones) ", r.get("busca", ""))),
            "ofrece"    : str(r.get("¿Qué ofreces a otros participantes del evento? (máximo 3 opciones)", r.get("ofrece", ""))),
            "tipo"      : str(r.get("Tipo entrada", r.get("tipo", ""))),
        })
    return result


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────
class MatchRequest(BaseModel):
    movil: str


class BatchRequest(BaseModel):
    registros: Optional[List[dict]] = None   # si viene vacío, lee directo del Sheet
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
    return {"status": "ok", "mensaje": "ASBAMA Matchmaking API v2.0 activa", "version": "2.0.0"}


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest):
    """Consulta en tiempo real: recibe móvil, devuelve top-N matches."""
    if not req.movil:
        raise HTTPException(status_code=400, detail="Campo 'movil' es requerido")

    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)

    movil_norm = normalizar(req.movil)

    # ── Verificar historial primero ────────────────────────────────────────────
    matches_guardados = obtener_historial(movil_norm, ss)
    if matches_guardados:
        incrementar_contador(movil_norm, ss)
        nombre = matches_guardados[0].razon  # placeholder; se sobreescribe
        # Obtener nombre real
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

    # ── Calcular scores vs todos ───────────────────────────────────────────────
    candidatos = [p for p in participantes if p["telefono"] != movil_norm]
    scored = []
    for c in candidatos:
        score = calcular_score(usuario_row, c)
        scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
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
    """
    Corre el modelo completo:
    - Si req.registros viene con datos, los usa directamente.
    - Si viene vacío, lee la hoja Participantes del Sheet.
    Devuelve la tabla completa de matches para todos los usuarios.
    """
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)

    top_n = req.top_n or DEFAULT_TOP_N

    # ── Obtener participantes ──────────────────────────────────────────────────
    if req.registros:
        # Normalizar desde el JSON que envía Apps Script
        participantes = []
        for r in req.registros:
            tel_raw = (
                r.get("Teléfono móvil") or r.get("Telefono movil") or
                r.get("telefono") or r.get("móvil") or r.get("movil") or ""
            )
            participantes.append({
                "telefono"  : normalizar(tel_raw),
                "nombres"   : str(r.get("Nombres", r.get("nombres", ""))),
                "apellidos" : str(r.get("Apellidos", r.get("apellidos", ""))),
                "email"     : str(r.get("Email", r.get("email", ""))),
                "empresa"   : str(r.get("Empresa/Institución", r.get("empresa", ""))),
                "cargo"     : str(r.get("Cargo", r.get("cargo", ""))),
                "rol"       : str(r.get("¿Cual es tu rol principal en la cadena de valor del banano?", r.get("rol", ""))),
                "busca"     : str(r.get("En este evento, ¿qué estás buscando principalmente? (máximo 3 opciones) ", r.get("busca", ""))),
                "ofrece"    : str(r.get("¿Qué ofreces a otros participantes del evento? (máximo 3 opciones)", r.get("ofrece", ""))),
                "tipo"      : str(r.get("Tipo entrada", r.get("tipo", ""))),
            })
    else:
        participantes = leer_participantes(ss)

    if not participantes:
        raise HTTPException(status_code=400, detail="No hay participantes para procesar")

    # ── Correr modelo con pandas ───────────────────────────────────────────────
    df = pd.DataFrame(participantes)
    all_matches = []

    for i, usuario in df.iterrows():
        candidatos = df[df["telefono"] != usuario["telefono"]]
        scored = []
        for _, c in candidatos.iterrows():
            score = calcular_score(usuario.to_dict(), c.to_dict())
            scored.append({
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
                "razon"          : razon_match(usuario.to_dict(), c.to_dict()),
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        for pos, m in enumerate(scored[:top_n]):
            m["posicion"] = pos + 1
            all_matches.append(m)

    # ── Escribir resultados en MatchResultados ─────────────────────────────────
    try:
        try:
            sheet_res = ss.worksheet(SHEET_RESULTADOS)
            sheet_res.clear()
        except Exception:
            sheet_res = ss.add_worksheet(title=SHEET_RESULTADOS, rows=str(len(all_matches) + 10), cols="15")

        if all_matches:
            headers = list(all_matches[0].keys())
            rows    = [headers] + [[m.get(h, "") for h in headers] for m in all_matches]
            sheet_res.update(rows, "A1")
    except Exception as e:
        pass  # No bloquear la respuesta si falla escribir al Sheet

    return BatchResponse(
        status         = "ok",
        total_usuarios = len(participantes),
        total_matches  = len(all_matches),
        matches        = all_matches,
        mensaje        = f"Modelo corrido: {len(participantes)} participantes × top-{top_n} matches cada uno. Resultados guardados en '{SHEET_RESULTADOS}'.",
    )


# ─── Historial ─────────────────────────────────────────────────────────────────
def obtener_historial(movil_norm: str, ss):
    try:
        sheet   = ss.worksheet(SHEET_HISTORIA)
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
        sheet   = ss.worksheet(SHEET_HISTORIA)
        records = sheet.get_all_records()
        for i, row in enumerate(records):
            if normalizar(str(row.get("Movil", ""))) == movil_norm:
                sheet.update_cell(i + 2, 4, int(row.get("VecesConsultado", 1)) + 1)
                return
    except Exception:
        pass


# ─── Formatear mensaje WhatsApp ────────────────────────────────────────────────
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
