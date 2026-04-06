# Matchmaking API

API de matchmaking para eventos B2B (ANDICOM / ASBAMA) construida con **FastAPI** y desplegada en **Vercel**.

Se conecta a **Google Sheets** como base de datos y genera matches personalizados basados en 4 variables clave de perfil.

---

## 📐 Arquitectura

```
Eve (WhatsApp) → n8n/Make → POST /match → Google Sheets → Respuesta con 5 matches
```

---

## 🔌 Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/` | Estado de la API |
| GET | `/health` | Health check |
| POST | `/match` | Generar/consultar matches |

### POST `/match`

**Request body:**
```json
{
  "movil": "573188042522",
  "rol": "Proveedor TIC",
  "especialidadtec": "IA",
  "industria": "Banca",
  "objetivo": "Conseguir clientes"
}
```

**Response:**
```json
{
  "status": "ok",
  "fuente": "nuevo",
  "usuario": "Andres Diaz",
  "matches": [
    {
      "posicion": 1,
      "nombre": "Felipe Mora",
      "email": "felipem@gmail.com",
      "movil": "573127899893",
      "score": 93,
      "nivel": "Excepcional",
      "razon": "Perfil complementario clave..."
    }
  ],
  "mensaje": "Andres, encontré tus conexiones..."
}
```

---

## 🚀 Despliegue en Vercel

### 1. Conecta el repositorio en Vercel
- Ve a [vercel.com](https://vercel.com) → **Add New Project**
- Selecciona este repositorio

### 2. Configura las variables de entorno en Vercel

En **Settings → Environment Variables** agrega:

| Variable | Descripción |
|----------|-------------|
| `SPREADSHEET_ID` | ID de tu Google Sheet (el fragmento largo en la URL) |
| `GOOGLE_CREDENTIALS` | JSON completo de tu Service Account (en una sola línea) |

### 3. Configura Google Sheets

1. Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com)
2. Habilita la **Google Sheets API** y la **Google Drive API**
3. Crea una **Service Account** y descarga el JSON de credenciales
4. En tu Google Sheet, comparte el archivo con el email de la Service Account
5. Tu hoja debe tener una pestaña `Registros` con columnas: `nombres`, `apellidos`, `email`, `telefono`

---

## 🛠️ Desarrollo local

```bash
# Clonar
git clone https://github.com/royandi200/matchmaking-api.git
cd matchmaking-api

# Instalar dependencias
pip install -r api/requirements.txt

# Crear .env con tus variables
cp .env.example .env
# Edita .env con tus valores reales

# Correr localmente
uvicorn api.index:app --reload
```

La API quedará en `http://localhost:8000`  
Documentación automática en `http://localhost:8000/docs`

---

## 📋 Variables de perfil soportadas

### Rol en el ecosistema
- Proveedor TIC
- Empresa compradora
- Gobierno
- Inversor
- Startup
- Academia

### Especialidad tecnológica
- IA / Data Analytics
- Ciberseguridad
- Cloud Computing
- Conectividad / Telco
- Desarrollo de Software
- Smart Cities / IoT
- BPO / Servicios TIC

### Industria que sirven
- Banca / Fintech
- Salud
- Retail / Comercio
- Manufactura
- Gobierno / Sector Público
- Educación
- Energía
- Agroindustria

### Objetivo en el evento
- Conseguir clientes
- Buscar proveedor / solución
- Levantar inversión
- Hacer alianzas técnicas
- Contratar talento
- Aprender / explorar

---

## 📞 Flujo con Eve (WhatsApp)

1. Eve recolecta las 4 variables durante la conversación
2. n8n/Make dispara `POST /match` con el JSON
3. La API consulta Sheets y retorna los 5 matches
4. El campo `mensaje` contiene el texto listo para enviar al usuario
5. Eve lo presenta de forma natural en WhatsApp
