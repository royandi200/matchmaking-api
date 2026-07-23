from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json, os, unicodedata, re
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

app = FastAPI(
    title="Matchmaking API — ANDICOM / ASBAMA 2026",
    description="Motor de matching para eventos B2B tecnológicos",
    version="3.0.0"
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SCOPES            = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "")
SHEET_REGISTROS  = "Participantes"
SHEET_RESULTADOS = "MatchResultados"
SHEET_HISTORIA   = "MatchHistoria"
DEFAULT_TOP_N    = 10

W_OFRECE_BUSCA = 0.45
W_BUSCA_OFRECE = 0.45
W_ROL          = 0.10

ROLES_COMPLEMENTARIOS = [
    {"Invierto en empresas o proyectos.", "Tengo una startup o emprendimiento tecnológico."},
    {"Invierto en empresas o proyectos.", "Tengo una empresa y uso tecnología en mi negocio."},
    {"Vendo software o servicios de tecnología.", "Tengo una empresa y uso tecnología en mi negocio."},
    {"Vendo equipos, redes o infraestructura tecnológica.", "Tengo una empresa y uso tecnología en mi negocio."},
    {"Ayudo a empresas a mejorar sus procesos con tecnología.", "Tengo una empresa y uso tecnología en mi negocio."},
    {"Ayudo a empresas a mejorar sus procesos con tecnología.", "Tengo una startup o emprendimiento tecnológico."},
    {"Trabajo en educación, investigación o innovación.", "Tengo una startup o emprendimiento tecnológico."},
    {"Trabajo en educación, investigación o innovación.", "Vendo software o servicios de tecnología."},
    {"Hago parte de una comunidad, gremio, clúster o aceleradora.", "Tengo una startup o emprendimiento tecnológico."},
    {"Hago parte de una comunidad, gremio, clúster o aceleradora.", "Invierto en empresas o proyectos."},
    {"Trabajo en una entidad pública.", "Tengo una startup o emprendimiento tecnológico."},
    {"Trabajo en una entidad pública.", "Vendo software o servicios de tecnología."},
    {"Trabajo en una entidad pública.", "Ayudo a empresas a mejorar sus procesos con tecnología."},
    {"Ofrezco servicios creativos, marketing digital o comercio electrónico.", "Tengo una empresa y uso tecnología en mi negocio."},
    {"Ofrezco servicios creativos, marketing digital o comercio electrónico.", "Vendo software o servicios de tecnología."},
    {"Vendo equipos, redes o infraestructura tecnológica.", "Vendo software o servicios de tecnología."},
    {"Proveedor de soluciones tecnológicas.", "Tengo una empresa y uso tecnología en mi negocio."},
    {"Startup / emprendimiento tecnológico.", "Invierto en empresas o proyectos."},
    {"Startup / emprendimiento tecnológico.", "Hago parte de una comunidad, gremio, clúster o aceleradora."},
]

NIVELES_SCORE = [(90, "Excepcional"), (75, "Altamente Compatible"), (60, "Muy Compatible"), (0, "Compatible")]

CANON_RULES: list[tuple[list[str], str]] = [
    # ── ROL CADENA ──────────────────────────────────────────────
    (["startup", "emprendimiento"],              "startup_tech"),
    (["proveedor", "soluciones", "tecnol"],      "proveedor_tech"),
    (["proveedor", "tecnol"],                    "proveedor_tech"),
    (["invierto", "empresas"],                   "inversionista"),
    (["invierto", "proyectos"],                  "inversionista"),
    (["ayudo", "empresas", "procesos"],          "consultor_tech"),
    (["mejora", "procesos", "tecnolog"],         "consultor_tech"),
    (["vendo", "software"],                      "proveedor_software"),
    (["servicios", "tecnolog"],                  "proveedor_software"),
    (["vendo", "equipos"],                       "proveedor_hardware"),
    (["redes", "infraestructura"],               "proveedor_hardware"),
    (["servicios", "creativos"],                 "marketing_digital"),
    (["marketing", "digital"],                   "marketing_digital"),
    (["comercio", "electronico"],                "ecommerce"),
    (["educacion", "investigacion"],             "academia"),
    (["innovacion"],                             "academia"),
    (["entidad", "publica"],                     "sector_publico"),
    (["comunidad", "gremio"],                    "ecosistema"),
    (["cluster", "aceleradora"],                 "ecosistema"),
    (["empresa", "uso", "tecnolog"],             "empresa_usuaria"),
    (["empresa", "tecnolog"],                    "empresa_usuaria"),

    # ── BUSCA ───────────────────────────────────────────────────
    (["clientes", "productos"],                  "clientes_b2b"),
    (["clientes", "servicios"],                  "clientes_b2b"),
    (["proveedores", "tecnolog"],                "proveedores_tech"),
    (["proveedores", "servicio"],                "proveedores_tech"),
    (["aliados", "proyectos"],                   "alianzas"),
    (["aliados", "nuevos"],                      "alianzas"),
    (["apoyo", "emprendimiento"],                "apoyo_emprendimiento"),
    (["hacer", "crecer", "emprendimiento"],      "apoyo_emprendimiento"),
    (["personas", "equipo"],                     "talento"),
    (["sumar", "equipo"],                        "talento"),
    (["inversion", "financiacion"],              "financiero"),
    (["opciones", "inversion"],                  "financiero"),
    (["inversion", "apoyo"],                     "financiero"),
    (["ideas", "casos", "aprender"],             "aprendizaje"),
    (["ideas", "aprender"],                      "aprendizaje"),
    (["aprender"],                               "aprendizaje"),
    (["impacto", "social"],                      "impacto_social"),
    (["impacto", "ambiental"],                   "impacto_social"),
    (["conexiones", "sector"],                   "networking"),
    (["nuevas", "conexiones"],                   "networking"),
    (["networking"],                             "networking"),
    (["entidades", "publicas"],                  "sector_publico"),
    (["contactos", "publico"],                   "sector_publico"),
    (["alianza"],                                "alianzas"),
    (["financiero"],                             "financiero"),
    (["financiacion"],                           "financiero"),

    # ── OFRECE ──────────────────────────────────────────────────
    (["software", "aplicaciones"],               "software_plataformas"),
    (["software", "plataformas"],                "software_plataformas"),
    (["aplicaciones", "plataformas"],            "software_plataformas"),
    (["seguridad", "digital"],                   "infraestructura_cloud"),
    (["nube", "infraestructura"],                "infraestructura_cloud"),
    (["seguridad", "nube"],                      "infraestructura_cloud"),
    (["transformacion", "digital"],              "consultoria_digital"),
    (["acompanamiento", "transformacion"],       "consultoria_digital"),
    (["estrategia", "digital"],                  "consultoria_digital"),
    (["comercio", "electronico", "marketing"],   "ecommerce_marketing"),
    (["marketing", "digital", "contenidos"],     "ecommerce_marketing"),
    (["comercio", "electronico"],                "ecommerce_marketing"),
    (["equipos", "dispositivos"],                "hardware_equipos"),
    (["hardware", "dispositivos"],               "hardware_equipos"),
    (["pcs", "servidores"],                      "hardware_equipos"),
    (["formacion", "cursos"],                    "formacion_investigacion"),
    (["investigacion", "aplicada"],              "formacion_investigacion"),
    (["cursos", "investigacion"],                "formacion_investigacion"),
    (["inversion", "apoyo", "financiero"],       "inversion_financiera"),
    (["inversion", "financiero"],                "inversion_financiera"),
    (["apoyo", "financiero"],                    "inversion_financiera"),
    (["espacios", "comunidad"],                  "ecosistema_emprendimiento"),
    (["programas", "crecer"],                    "ecosistema_emprendimiento"),
    (["comunidad", "programas"],                 "ecosistema_emprendimiento"),
    (["impacto", "social", "ambiental"],         "tech_impacto"),
    (["tecnologia", "impacto"],                  "tech_impacto"),
    (["automatizar", "tareas"],                  "automatizacion"),
    (["automatizar", "procesos"],                "automatizacion"),
    (["herramientas", "automatizar"],            "automatizacion"),
    (["herramientas", "procesos"],               "automatizacion"),

    # ── LEGACY / fallback genérico ───────────────────────────────
    (["tecnolog"],                               "software_plataformas"),
    (["certificacion"],                          "formacion_investigacion"),
    (["consultoria"],                            "consultoria_digital"),
    (["logistica"],                              "proveedores_tech"),
    (["financiero"],                             "inversion_financiera"),
    (["seguro"],                                 "inversion_financiera"),
    (["credito"],                                "inversion_financiera"),
]


def nk(k: str) -> str:
    s = unicodedata.normalize("NFKD", str(k))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def nk_compact(k: str) -> str:
    return re.sub(r"\s+", "", nk(k))


def canonicalizar(val: str) -> str:
    k = nk(val)
    for keywords, canon in CANON_RULES:
        if all(kw in k for kw in keywords):
            return canon
    return k


def parsear_multivalor(val: str) -> set:
    if not val or str(val).strip() in ("", "nan", "None"):
        return set()
    raw = str(val)
    if ";" in raw:
        items = raw.split(";")
    elif "," in raw:
        items = raw.split(",")
    else:
        items = raw.split("\n")
    items = {v.strip() for v in items if v.strip()}
    result = set()
    for i in items:
        c = canonicalizar(i)
        if c and c != "otro" and len(c) > 2:
            result.add(c)
    return result


def get_sheets_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS", "")
    if not creds_json:
        raise HTTPException(status_code=500, detail="GOOGLE_CREDENTIALS no configurado")
    creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=SCOPES)
    return gspread.authorize(creds)

def normalizar_tel(val) -> str:
    return "".join(filter(str.isdigit, str(val)))

def nombre_completo(nombres: str, apellidos: str) -> str:
    return f"{nombres} {apellidos}".strip()

def jaccard(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0

def roles_complementarios(rol_a: str, rol_b: str) -> bool:
    ra = rol_a.strip()
    rb = rol_b.strip()
    for pair in ROLES_COMPLEMENTARIOS:
        pa, pb = list(pair)
        if (ra == pa and rb == pb) or (ra == pb and rb == pa):
            return True
    # fallback: comparación normalizada
    ra_n = nk(ra)
    rb_n = nk(rb)
    for pair in ROLES_COMPLEMENTARIOS:
        pa, pb = [nk(x) for x in pair]
        if (ra_n == pa and rb_n == pb) or (ra_n == pb and rb_n == pa):
            return True
    return False

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
    if str(a.get("empresa","")).strip().lower() == str(b.get("empresa","")).strip().lower() != "":
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
        labels = {
            # Tech B2B - ofrece
            "software_plataformas":        "software, aplicaciones o plataformas",
            "infraestructura_cloud":       "seguridad digital, nube o infraestructura",
            "consultoria_digital":         "acompañamiento en transformación digital",
            "ecommerce_marketing":         "comercio electrónico y marketing digital",
            "hardware_equipos":            "equipos y dispositivos tecnológicos",
            "formacion_investigacion":     "formación, cursos o investigación aplicada",
            "inversion_financiera":        "inversión o apoyo financiero",
            "ecosistema_emprendimiento":   "espacios, comunidad o programas para crecer",
            "tech_impacto":                "tecnología con impacto social o ambiental",
            "automatizacion":              "herramientas para automatizar tareas y procesos",
            # Tech B2B - busca
            "clientes_b2b":                "clientes para productos o servicios",
            "proveedores_tech":            "proveedores de tecnología o servicios",
            "alianzas":                    "aliados para nuevos proyectos",
            "apoyo_emprendimiento":        "apoyo para hacer crecer el emprendimiento",
            "talento":                     "personas para sumar al equipo",
            "financiero":                  "opciones de inversión o financiación",
            "aprendizaje":                 "ideas y casos reales para aprender",
            "impacto_social":              "proyectos con impacto social o ambiental",
            "networking":                  "nuevas conexiones en el sector tecnológico",
            "sector_publico":              "contactos en entidades públicas",
            # Roles canonizados
            "startup_tech":                "startups y emprendimientos tecnológicos",
            "proveedor_tech":              "proveedores de soluciones tecnológicas",
            "inversionista":               "inversión y financiación",
            "consultor_tech":              "consultoría en transformación digital",
            "proveedor_software":          "software y servicios tecnológicos",
            "proveedor_hardware":          "equipos y redes",
            "marketing_digital":           "marketing digital y comercio electrónico",
            "ecommerce":                   "comercio electrónico",
            "academia":                    "investigación e innovación",
            "sector_publico":              "sector público y entidades gubernamentales",
            "ecosistema":                  "ecosistema de emprendimiento",
            "empresa_usuaria":             "empresas que adoptan tecnología",
        }
        label = labels.get(item, item.replace("_", " "))
        return f"{b.get('nombres', '')} ofrece '{label}', que es exactamente lo que buscas."
    if roles_complementarios(str(a.get("rol","")), str(b.get("rol",""))):
        return f"Roles complementarios: {a.get('rol','')} ↔ {b.get('rol','')}, alta sinergia en el ecosistema tech."
    return "Perfil estratégico con potencial de colaboración en el ecosistema tecnológico."


def buscar_columna(row: dict, *candidatos) -> str:
    rn = {nk_compact(k): v for k, v in row.items()}
    for c in candidatos:
        v = rn.get(nk_compact(c))
        if v is not None:
            return str(v)
    return ""


def leer_participantes(ss) -> list:
    try:
        sheet = ss.worksheet(SHEET_REGISTROS)
    except Exception:
        raise HTTPException(status_code=500, detail=f"Hoja '{SHEET_REGISTROS}' no encontrada")
    result = []
    for r in sheet.get_all_records():
        tel_raw = buscar_columna(r, "telefono", "telefono movil", "movil", "celular", "tel")
        result.append({
            "telefono" : normalizar_tel(tel_raw),
            "nombres"  : buscar_columna(r, "nombres", "nombre"),
            "apellidos": buscar_columna(r, "apellidos", "apellido"),
            "email"    : buscar_columna(r, "email", "correo"),
            "empresa"  : buscar_columna(r, "empresa", "empresa institucion", "institucion"),
            "cargo"    : buscar_columna(r, "cargo"),
            "rol"      : buscar_columna(r, "rol cadena", "rolcadena", "rol principal", "rol", "a que te dedicas", "dedicas"),
            "busca"    : buscar_columna(r, "busca", "que quieres encontrar", "en este evento que estas buscando principalmente maximo 3 opciones", "buscando"),
            "ofrece"   : buscar_columna(r, "ofrece", "que puedes ofrecer", "que ofreces a otros participantes del evento maximo 3 opciones", "ofreces"),
            "tipo"     : buscar_columna(r, "tipo entrada", "tipoentrada", "tipo"),
        })
    return result


def mapear_registro(r: dict) -> dict:
    return {
        "telefono" : normalizar_tel(buscar_columna(r, "telefono", "telefono movil", "movil")),
        "nombres"  : buscar_columna(r, "nombres", "nombre"),
        "apellidos": buscar_columna(r, "apellidos", "apellido"),
        "email"    : buscar_columna(r, "email", "correo"),
        "empresa"  : buscar_columna(r, "empresa", "empresa institucion"),
        "cargo"    : buscar_columna(r, "cargo"),
        "rol"      : buscar_columna(r, "rol cadena", "rolcadena", "rol", "a que te dedicas", "dedicas"),
        "busca"    : buscar_columna(r, "busca", "que quieres encontrar", "buscando"),
        "ofrece"   : buscar_columna(r, "ofrece", "que puedes ofrecer", "ofreces"),
        "tipo"     : buscar_columna(r, "tipo entrada", "tipoentrada", "tipo"),
    }


class MatchRequest(BaseModel):
    movil: str

class ClearRequest(BaseModel):
    movil: str

class BatchRequest(BaseModel):
    registros: Optional[List[dict]] = None
    todos: Optional[List[dict]] = None
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


@app.get("/")
def root():
    return {"status": "ok", "mensaje": "ANDICOM/ASBAMA Matchmaking API v3.0.0 activa", "version": "3.0.0"}

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/debug")
def debug():
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    try:
        sheet = ss.worksheet(SHEET_REGISTROS)
        records = sheet.get_all_records()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not records:
        return {"columnas": [], "muestra_raw": {}, "muestra_mapeada": {}}
    participantes = leer_participantes(ss)
    m = participantes[0] if participantes else {}
    return {
        "total_registros" : len(records),
        "columnas"        : list(records[0].keys()),
        "muestra_raw"     : records[0],
        "muestra_mapeada" : m,
        "sets_canonicos"  : {
            "busca" : list(parsear_multivalor(m.get("busca", ""))),
            "ofrece": list(parsear_multivalor(m.get("ofrece", ""))),
        }
    }

@app.get("/debug-user/{movil}")
def debug_user(movil: str):
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    participantes = leer_participantes(ss)
    movil_norm = normalizar_tel(movil)
    usuario = next((p for p in participantes if p["telefono"] == movil_norm), None)
    if not usuario:
        raise HTTPException(status_code=404, detail=f"No encontrado: {movil}")
    busca_set  = parsear_multivalor(usuario.get("busca",  ""))
    ofrece_set = parsear_multivalor(usuario.get("ofrece", ""))
    candidatos = [p for p in participantes if p["telefono"] != movil_norm]
    scores_debug = []
    for c in candidatos:
        ofrece_c = parsear_multivalor(c.get("ofrece", ""))
        busca_c  = parsear_multivalor(c.get("busca",  ""))
        score  = calcular_score(usuario, c)
        scores_debug.append({
            "nombre"         : nombre_completo(c["nombres"], c["apellidos"]),
            "empresa"        : c["empresa"],
            "rol"            : c.get("rol", ""),
            "score"          : score,
            "j_ofrece_busca" : round(jaccard(ofrece_set, busca_c), 3),
            "j_busca_ofrece" : round(jaccard(ofrece_c, busca_set), 3),
            "rol_ok"         : roles_complementarios(str(usuario.get("rol","")), str(c.get("rol",""))),
            "ofrece_c"       : list(ofrece_c),
            "busca_c"        : list(busca_c),
            "busca_raw"      : c.get("busca", ""),
            "ofrece_raw"     : c.get("ofrece", ""),
        })
    scores_debug.sort(key=lambda x: x["score"], reverse=True)
    return {
        "usuario"      : nombre_completo(usuario["nombres"], usuario["apellidos"]),
        "rol"          : usuario.get("rol"),
        "busca_raw"    : usuario.get("busca"),
        "ofrece_raw"   : usuario.get("ofrece"),
        "busca_canon"  : list(busca_set),
        "ofrece_canon" : list(ofrece_set),
        "top10_scores" : scores_debug[:10],
    }

@app.post("/clear-history")
def clear_history(req: ClearRequest):
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    movil_norm = normalizar_tel(req.movil)
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
        records = sheet.get_all_records()
    except Exception:
        return {"status": "ok", "mensaje": "Hoja MatchHistoria no existe, nada que borrar."}
    for i, row in enumerate(records):
        if normalizar_tel(str(row.get("Movil", ""))) == movil_norm:
            sheet.delete_rows(i + 2)
            return {"status": "ok", "mensaje": f"Historial de {req.movil} eliminado."}
    return {"status": "ok", "mensaje": f"No se encontró historial para {req.movil}"}

@app.post("/clear-all-history")
def clear_all_history():
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
        sheet.clear()
        sheet.append_row(["Movil", "FechaConsulta", "MatchesJSON", "VecesConsultado"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "mensaje": "Historial completo eliminado."}

@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest):
    if not req.movil:
        raise HTTPException(status_code=400, detail="Campo 'movil' es requerido")
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    movil_norm = normalizar_tel(req.movil)
    matches_guardados = obtener_historial(movil_norm, ss)
    if matches_guardados:
        incrementar_contador(movil_norm, ss)
        participantes = leer_participantes(ss)
        u = next((p for p in participantes if p["telefono"] == movil_norm), None)
        nombre_u = nombre_completo(u["nombres"], u["apellidos"]) if u else req.movil
        return MatchResponse(status="ok", fuente="historial", usuario=nombre_u,
            matches=matches_guardados, mensaje=formatear_mensaje(nombre_u, matches_guardados))
    participantes = leer_participantes(ss)
    usuario_row = next((p for p in participantes if p["telefono"] == movil_norm), None)
    if not usuario_row:
        raise HTTPException(status_code=404, detail=f"No se encontró usuario con móvil {req.movil}")
    empresa_mejor: dict = {}
    for c in participantes:
        if c["telefono"] == movil_norm:
            continue
        score = calcular_score(usuario_row, c)
        emp = str(c.get("empresa", "")).strip().lower()
        if emp not in empresa_mejor or score > empresa_mejor[emp][0]:
            empresa_mejor[emp] = (score, c)
    scored = sorted(empresa_mejor.values(), key=lambda x: x[0], reverse=True)
    matches = [
        MatchResult(
            posicion=i+1, nombre=nombre_completo(c["nombres"], c["apellidos"]),
            email=c["email"], movil=c["telefono"], empresa=c["empresa"], cargo=c["cargo"],
            score=score, nivel=nivel_desde_score(score), razon=razon_match(usuario_row, c),
        )
        for i, (score, c) in enumerate(scored[:DEFAULT_TOP_N])
    ]
    guardar_historial(movil_norm, matches, ss)
    nombre_u = nombre_completo(usuario_row["nombres"], usuario_row["apellidos"])
    return MatchResponse(status="ok", fuente="nuevo", usuario=nombre_u,
        matches=matches, mensaje=formatear_mensaje(nombre_u, matches))

@app.post("/batch-match", response_model=BatchResponse)
def batch_match(req: BatchRequest):
    """
    Modo 1 (sin registros): lee Sheet completo y procesa todo.
    Modo 2 (registros + todos): procesa el lote contra la base completa.
    Permite partir 1000 participantes en lotes de 50 sin timeout.
    """
    gc = get_sheets_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    top_n = req.top_n or DEFAULT_TOP_N

    if req.registros and req.todos:
        lote = [mapear_registro(r) for r in req.registros]
        base = [mapear_registro(r) for r in req.todos]
    elif req.registros and not req.todos:
        lote = [mapear_registro(r) for r in req.registros]
        base = lote
    else:
        lote = leer_participantes(ss)
        base = lote

    if not lote or not base:
        raise HTTPException(status_code=400, detail="No hay participantes")

    df_lote = pd.DataFrame(lote)
    df_base = pd.DataFrame(base)

    all_matches = []
    for _, usuario in df_lote.iterrows():
        empresa_mejor: dict = {}
        for _, c in df_base[df_base["telefono"] != usuario["telefono"]].iterrows():
            score = calcular_score(usuario.to_dict(), c.to_dict())
            emp = str(c.get("empresa", "")).strip().lower()
            if emp not in empresa_mejor or score > empresa_mejor[emp][0]:
                empresa_mejor[emp] = (score, c.to_dict())
        for pos, (score, c) in enumerate(sorted(empresa_mejor.values(), key=lambda x: x[0], reverse=True)[:top_n]):
            all_matches.append({
                "posicion": pos+1, "tel_usuario": usuario["telefono"],
                "nombre_usuario": nombre_completo(usuario["nombres"], usuario["apellidos"]),
                "email_usuario": usuario["email"], "empresa_usuario": usuario["empresa"],
                "tel_match": c["telefono"], "nombre_match": nombre_completo(c["nombres"], c["apellidos"]),
                "email_match": c["email"], "empresa_match": c["empresa"], "cargo_match": c["cargo"],
                "score": score, "nivel": nivel_desde_score(score), "razon": razon_match(usuario.to_dict(), c),
            })

    if not req.todos:
        try:
            try:
                sheet_res = ss.worksheet(SHEET_RESULTADOS)
                sheet_res.clear()
            except Exception:
                sheet_res = ss.add_worksheet(title=SHEET_RESULTADOS, rows=str(len(all_matches)+10), cols="15")
            if all_matches:
                headers = list(all_matches[0].keys())
                sheet_res.update([headers] + [[m.get(h, "") for h in headers] for m in all_matches], "A1")
        except Exception:
            pass

    return BatchResponse(
        status="ok",
        total_usuarios=len(lote),
        total_matches=len(all_matches),
        matches=all_matches,
        mensaje=f"Lote procesado: {len(lote)} usuarios × top-{top_n}."
    )


def obtener_historial(movil_norm, ss):
    try:
        records = ss.worksheet(SHEET_HISTORIA).get_all_records()
    except Exception:
        return None
    for row in records:
        if normalizar_tel(str(row.get("Movil", ""))) == movil_norm:
            try:
                return [MatchResult(**m) for m in json.loads(row.get("MatchesJSON", "[]"))]
            except Exception:
                return None
    return None

def guardar_historial(movil_norm, matches, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
    except Exception:
        sheet = ss.add_worksheet(title=SHEET_HISTORIA, rows="2000", cols="5")
        sheet.append_row(["Movil", "FechaConsulta", "MatchesJSON", "VecesConsultado"])
    sheet.append_row([movil_norm, datetime.utcnow().isoformat(),
        json.dumps([m.dict() for m in matches], ensure_ascii=False), 1])

def incrementar_contador(movil_norm, ss):
    try:
        sheet = ss.worksheet(SHEET_HISTORIA)
        for i, row in enumerate(sheet.get_all_records()):
            if normalizar_tel(str(row.get("Movil", ""))) == movil_norm:
                sheet.update_cell(i+2, 4, int(row.get("VecesConsultado", 1))+1)
                return
    except Exception:
        pass

def formatear_mensaje(nombre_usuario, matches):
    msg = f"🌿 *{nombre_usuario}*, encontré tus conexiones estratégicas para el evento!\n\n"
    msg += "Analicé todos los perfiles y estos son los más afines a ti:\n\n"
    for m in matches:
        msg += f"*{m.posicion}. {m.nombre}* — {m.nivel} ({m.score}pts)\n"
        msg += f"🏢 {m.empresa}\n📱 {m.movil}\n💡 {m.razon}\n\n"
    msg += "👉 Escribe *ver todos mis contactos* para ver más conexiones."
    return msg
