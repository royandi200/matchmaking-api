// ============================================================
// MATCHMAKING WEBHOOK ASBAMA 2026 — Google Apps Script
// MATCH: preview top 3 | CONTACTOS: siguientes 5 | QR: mensaje completo
// v2.6 — limpiarDuplicadosParticipantes() integrada en correrModelo()
// ============================================================


const CONFIG = {
  SPREADSHEET_ID   : "18XUwGcjHbZ1I3pBVDqtUIol1L_DkUhE6mRZZfKMRAdg",
  SHEET_REGISTROS  : "Participantes",
  SHEET_RESULTADOS : "MatchResultados",
  SHEET_HISTORIA   : "MatchHistoria",
  SHEET_LOGS       : "APILogs",
  API_VERCEL_MATCH : "https://matchmaking-api-theta.vercel.app/match",
  API_VERCEL_BATCH : "https://matchmaking-api-theta.vercel.app/batch-match",
  TOP_N            : 10,
  TOP_MATCH        : 3,
  TOP_CONTACTOS    : 5,
  OFFSET_CONTACTOS : 3,
  TAMANO_LOTE      : 50,
};



// ── LIMPIAR DUPLICADOS ────────────────────────────────────────
// Elimina filas con teléfono repetido en "Participantes".
// Conserva la primera aparición. Se llama automáticamente al inicio de correrModelo().
function limpiarDuplicadosParticipantes() {
  const ss      = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const sheet   = ss.getSheetByName(CONFIG.SHEET_REGISTROS);
  if (!sheet || sheet.getLastRow() < 2) {
    Logger.log("limpiarDuplicados: hoja vacía, nada que hacer.");
    return;
  }

  const data    = sheet.getDataRange().getValues();
  const headers = data[0].map(function(h) { return h.toString().toLowerCase().trim(); });

  // Detectar columna de teléfono automáticamente
  const telCol = headers.findIndex(function(h) {
    return h.includes("tel") || h.includes("movil") ||
           h.includes("celular") || h.includes("móvil");
  });

  if (telCol === -1) {
    Logger.log("limpiarDuplicados: ❌ No se encontró columna de teléfono.");
    return;
  }

  const seen     = new Set();
  const toDelete = [];

  // Recorrer de abajo hacia arriba para no alterar índices al borrar
  for (let i = data.length - 1; i >= 1; i--) {
    const tel = data[i][telCol].toString().replace(/\D/g, "").trim();
    if (tel === "" || seen.has(tel)) {
      toDelete.push(i + 1); // +1: sheet es 1-indexed
    } else {
      seen.add(tel);
    }
  }

  if (toDelete.length === 0) {
    Logger.log("limpiarDuplicados: ✅ Sin duplicados — " + (data.length - 1) + " participantes únicos.");
    return;
  }

  toDelete.forEach(function(row) { sheet.deleteRow(row); });
  Logger.log(
    "limpiarDuplicados: 🧹 Eliminadas " + toDelete.length + " filas duplicadas. " +
    "Participantes únicos: " + (data.length - 1 - toDelete.length)
  );
}



// ── WEBHOOK PRINCIPAL ────────────────────────────────────────
function doPost(e) {
  let action = "UNKNOWN", phone = "", rawContent = "";


  try {
    rawContent = e.postData ? e.postData.contents : "";
    const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
    let logSheet = ss.getSheetByName(CONFIG.SHEET_LOGS);
    if (!logSheet) {
      logSheet = ss.insertSheet(CONFIG.SHEET_LOGS);
      logSheet.getRange(1, 1, 1, 5)
              .setValues([["Timestamp", "Action", "Teléfono", "Request", "Response"]])
              .setBackground("#4285f4")
              .setFontColor("#ffffff")
              .setFontWeight("bold");
    }
    logSheet.appendRow([new Date(), "RECIBIDO", "", rawContent.substring(0, 1000), ""]);
  } catch (logErr) {
    Logger.log("LOG INICIAL ERROR: " + logErr.toString());
  }


  try {
    if (!rawContent || !rawContent.trim()) {
      return jsonResponse({ error: true, mensaje: "Body vacío" });
    }


    const jsonRaw    = JSON.parse(rawContent);
    const textoParse = jsonRaw.info || jsonRaw.Info || rawContent;
    const jsonMatch  = textoParse.toString().match(/\{[^{}]*"action"[^{}]*\}/);


    if (!jsonMatch) {
      return jsonResponse({ error: true, mensaje: "No se encontró JSON válido" });
    }


    const requestData = JSON.parse(jsonMatch[0]);
    action = requestData.action || "UNKNOWN";
    phone  = String(
      requestData["Usuari@"] ||
      requestData.Usuari ||
      requestData.usuari ||
      requestData.phone ||
      ""
    );


    if (!phone) {
      return jsonResponse({ error: true, mensaje: "Falta el campo Usuari" });
    }


    const cache    = CacheService.getScriptCache();
    const cacheKey = normalizarTelefono(phone) + "_" + action + "_" + Math.floor(Date.now() / 5000);


    if (cache.get(cacheKey)) {
      return jsonResponse({ error: false, mensaje: "OK duplicado ignorado", duplicate: true });
    }
    cache.put(cacheKey, "1", 5);


    const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);


    let response;
    switch (action) {
      case "MATCH":
        response = accionMatch(phone, ss);
        break;
      case "CONTACTOS":
        response = accionContactos(phone, ss);
        break;
      case "QR":
        response = accionQR(phone, ss);
        break;
      default:
        response = { error: true, mensaje: "Acción no reconocida: " + action };
    }


    logRequest(action, phone, requestData, response, ss);
    return jsonResponse(response);


  } catch (err) {
    return jsonResponse({
      error: true,
      mensaje: "Error interno: " + err.message,
      debug: { action: action, raw: rawContent.substring(0, 300) }
    });
  }
}



// GET para pruebas rápidas
function doGet(e) {
  try {
    const action = e.parameter.action;
    const phone  = e.parameter["Usuari@"] || e.parameter.Usuari || e.parameter.phone;


    if (!action || !phone) {
      return jsonResponse({
        status: "ok",
        mensaje: "ASBAMA Matchmaking API activa",
        version: "v2.6"
      });
    }


    const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);


    switch (action) {
      case "MATCH":
        return jsonResponse(accionMatch(phone, ss));
      case "CONTACTOS":
        return jsonResponse(accionContactos(phone, ss));
      case "QR":
        return jsonResponse(accionQR(phone, ss));
      default:
        return jsonResponse({ error: true, mensaje: "Action inválida" });
    }


  } catch (err) {
    return jsonResponse({ error: true, mensaje: err.toString() });
  }
}



// ── ACCIÓN MATCH — devuelve TOP 3 (preview) ──────────────────
function accionMatch(phone, ss) {
  Logger.log("MATCH para " + phone);
  if (!phone) return { error: true, mensaje: "Teléfono requerido" };


  const historial = obtenerHistorial(phone, ss);
  if (historial) {
    incrementarContador(phone, ss);
    const top3 = historial.slice(0, CONFIG.TOP_MATCH);
    Logger.log("Desde historial → top 3");
    return {
      error: false,
      fuente: "historial",
      matches: top3,
      mensaje: formatearMensaje(top3, true)
    };
  }


  const matchesSheet = buscarEnResultados(phone, ss, CONFIG.TOP_N);
  if (matchesSheet) {
    guardarHistorial(phone, matchesSheet, ss);
    const top3 = matchesSheet.slice(0, CONFIG.TOP_MATCH);
    Logger.log("Desde MatchResultados → top 3");
    return {
      error: false,
      fuente: "resultados",
      matches: top3,
      mensaje: formatearMensaje(top3, true)
    };
  }


  return {
    error: false,
    fuente: "pendiente",
    matches: [],
    mensaje: "⏳ Tu perfil aún no tiene matches calculados. Consulta al organizador."
  };
}



// ── ACCIÓN CONTACTOS — devuelve 5 diferentes a los 3 primeros ────────────────
function accionContactos(phone, ss) {
  Logger.log("CONTACTOS para " + phone);
  if (!phone) return { error: true, mensaje: "Teléfono requerido" };


  const historial = obtenerHistorial(phone, ss);
  if (historial) {
    incrementarContador(phone, ss);
    const siguientes5 = historial.slice(CONFIG.OFFSET_CONTACTOS, CONFIG.OFFSET_CONTACTOS + CONFIG.TOP_CONTACTOS);
    Logger.log("Desde historial → siguientes 5");
    return {
      error: false,
      fuente: "historial",
      matches: siguientes5,
      mensaje: formatearMensaje(siguientes5, false)
    };
  }


  const matchesSheet = buscarEnResultados(phone, ss, CONFIG.TOP_N);
  if (matchesSheet) {
    guardarHistorial(phone, matchesSheet, ss);
    const siguientes5 = matchesSheet.slice(CONFIG.OFFSET_CONTACTOS, CONFIG.OFFSET_CONTACTOS + CONFIG.TOP_CONTACTOS);
    Logger.log("Desde MatchResultados → siguientes 5");
    return {
      error: false,
      fuente: "resultados",
      matches: siguientes5,
      mensaje: formatearMensaje(siguientes5, false)
    };
  }


  return {
    error: false,
    fuente: "pendiente",
    matches: [],
    mensaje: "⏳ Activa primero el Matching para ver tus contactos."
  };
}



// ── ACCIÓN QR — devuelve mensaje completo ────────────────────
function accionQR(phone, ss) {
  Logger.log("QR para " + phone);


  if (!phone) {
    return {
      error: true,
      action: "QR",
      mensaje: "No pude procesar tu solicitud porque falta el número de teléfono."
    };
  }


  const sheet = ss.getSheetByName(CONFIG.SHEET_REGISTROS);
  if (!sheet || sheet.getLastRow() < 2) {
    return {
      error: true,
      action: "QR",
      mensaje: "No fue posible consultar tu pase en este momento."
    };
  }


  const data    = sheet.getDataRange().getValues();
  const headers = data[0].map(function(h) {
    return h.toString().trim().toLowerCase();
  });


  const col = {
    ticket_id    : headers.indexOf("ticket_id"),
    tipo_entrada : headers.indexOf("tipo_entrada"),
    qr_code      : headers.indexOf("qr_code"),
    nombres      : headers.indexOf("nombres"),
    apellidos    : headers.indexOf("apellidos"),
    telefono     : headers.indexOf("telefono"),
    empresa      : headers.indexOf("empresa"),
    cargo        : headers.indexOf("cargo")
  };


  if (col.telefono === -1 || col.qr_code === -1) {
    return {
      error: true,
      action: "QR",
      mensaje: "No fue posible ubicar la información de tu QR en este momento."
    };
  }


  const phoneNorm = normalizarTelefono(phone);


  for (let i = 1; i < data.length; i++) {
    const telFila = normalizarTelefono(data[i][col.telefono]);
    if (!telFila) continue;


    if (telefonosCoinciden(phoneNorm, telFila)) {
      const nombres        = String(data[i][col.nombres] || "").trim();
      const apellidos      = String(data[i][col.apellidos] || "").trim();
      const nombreCompleto = (nombres + " " + apellidos).trim();
      const ticketId       = col.ticket_id > -1 ? String(data[i][col.ticket_id] || "").trim() : "";
      const tipoEntrada    = col.tipo_entrada > -1 ? String(data[i][col.tipo_entrada] || "").trim() : "";
      const empresa        = col.empresa > -1 ? String(data[i][col.empresa] || "").trim() : "";
      const cargo          = col.cargo > -1 ? String(data[i][col.cargo] || "").trim() : "";
      const qr             = String(data[i][col.qr_code] || "").trim();


      if (!qr) {
        return {
          error: true,
          action: "QR",
          mensaje: "Encontré tu registro, pero tu código QR aún no está disponible."
        };
      }


      const esImagen = qr.indexOf("http://") === 0 || qr.indexOf("https://") === 0;


      let msg = "🎟️ *Pase de acceso al Congreso Bananero 2026*\n\n";


      if (nombreCompleto) msg += "*" + nombreCompleto + "*\n";
      if (ticketId) msg += "🎫 Ticket #: " + ticketId + "\n";
      if (tipoEntrada) msg += "🏷️ " + tipoEntrada + "\n";


      if (empresa && cargo) {
        msg += "🏢 " + empresa + " · " + cargo + "\n";
      } else if (empresa) {
        msg += "🏢 " + empresa + "\n";
      } else if (cargo) {
        msg += "🏢 " + cargo + "\n";
      }


      msg += "\nTu código QR de entrada:\n";


      if (esImagen) {
        msg += "![QR de acceso](" + qr + ")\n\n";
      } else {
        msg += "━━━━━━━━━━━━━━━━━\n";
        msg += "`" + qr + "`\n";
        msg += "━━━━━━━━━━━━━━━━━\n\n";
      }


      msg += "📲 Preséntalo en la entrada desde tu celular o impreso.\n\n";
      msg += "📍 *Ingreso al evento:*\n";
      msg += "Centro de Convenciones Estelar Santamar — Santa Marta\n";
      msg += "📅 Jueves 21 y Viernes 22 de Mayo · 8:00 AM – 6:00 PM\n\n";
      msg += "💡 _Guarda este pase para tenerlo listo al llegar._";


      return {
        error: false,
        action: "QR",
        mensaje: msg
      };
    }
  }


  return {
    error: true,
    action: "QR",
    mensaje: "No encontré un registro con este número para generar tu QR."
  };
}



// ── BUSCAR EN MatchResultados ─────────────────────────────────
function buscarEnResultados(phone, ss, topN) {
  const sheet = ss.getSheetByName(CONFIG.SHEET_RESULTADOS);
  if (!sheet || sheet.getLastRow() < 2) return null;


  const data    = sheet.getDataRange().getValues();
  const headers = data[0].map(function(h) {
    return h.toString().trim().toLowerCase();
  });


  const col = {
    tel_usu  : headers.indexOf("tel_usuario"),
    nombre   : headers.indexOf("nombre_match"),
    email    : headers.indexOf("email_match"),
    tel_match: headers.indexOf("tel_match"),
    empresa  : headers.indexOf("empresa_match"),
    cargo    : headers.indexOf("cargo_match"),
    score    : headers.indexOf("score"),
    nivel    : headers.indexOf("nivel"),
    razon    : headers.indexOf("razon"),
    posicion : headers.indexOf("posicion")
  };


  const phoneNorm = normalizarTelefono(phone);
  const matches   = [];
  let pos = 1;


  for (let i = 1; i < data.length && matches.length < topN; i++) {
    const telUsuario = normalizarTelefono(data[i][col.tel_usu]);
    if (telefonosCoinciden(phoneNorm, telUsuario)) {
      matches.push({
        posicion : data[i][col.posicion] || pos,
        nombre   : data[i][col.nombre] || "",
        email    : data[i][col.email] || "",
        movil    : String(data[i][col.tel_match] || ""),
        empresa  : data[i][col.empresa] || "",
        cargo    : data[i][col.cargo] || "",
        score    : Number(data[i][col.score]) || 0,
        nivel    : data[i][col.nivel] || "",
        razon    : data[i][col.razon] || ""
      });
      pos++;
    }
  }


  return matches.length > 0 ? matches : null;
}



// ── FORMATEAR MENSAJE WhatsApp ────────────────────────────────
function formatearMensaje(matches, esPreview) {
  if (!matches || matches.length === 0) return "Sin matches disponibles.";


  let msg = esPreview
    ? "🌿 *Tus top 3 conexiones para el Congreso Bananero 2026:*\n\n"
    : "📋 *Tus siguientes 5 conexiones estratégicas:*\n\n";


  matches.forEach(function(m) {
    msg += "*" + m.posicion + ". " + m.nombre + "* — " + m.nivel + " (" + m.score + "pts)\n";
    msg += "🏢 " + m.empresa + "\n";
    msg += "📱 " + m.movil + "\n";
    msg += "💡 " + m.razon + "\n\n";
  });


  if (esPreview) {
    msg += "👉 Escribe *ver todos mis contactos* para ver más conexiones.";
  }


  return msg;
}



// ── HISTORIAL ─────────────────────────────────────────────────
function obtenerHistorial(phone, ss) {
  const sheet = ss.getSheetByName(CONFIG.SHEET_HISTORIA);
  if (!sheet || sheet.getLastRow() < 2) return null;


  const data      = sheet.getDataRange().getValues();
  const phoneNorm = normalizarTelefono(phone);


  for (let i = 1; i < data.length; i++) {
    const telHist = normalizarTelefono(data[i][0]);
    if (telefonosCoinciden(phoneNorm, telHist)) {
      try {
        return JSON.parse(data[i][2]);
      } catch (e) {
        return null;
      }
    }
  }


  return null;
}



function guardarHistorial(phone, matches, ss) {
  let sheet = ss.getSheetByName(CONFIG.SHEET_HISTORIA);
  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.SHEET_HISTORIA);
    sheet.getRange(1, 1, 1, 4)
         .setValues([["Móvil", "Fecha consulta", "Matches JSON", "Veces consultado"]])
         .setBackground("#0f9d58")
         .setFontColor("#ffffff")
         .setFontWeight("bold");
  }
  sheet.appendRow([phone, new Date(), JSON.stringify(matches), 1]);
}



function incrementarContador(phone, ss) {
  const sheet = ss.getSheetByName(CONFIG.SHEET_HISTORIA);
  if (!sheet) return;


  const data      = sheet.getDataRange().getValues();
  const phoneNorm = normalizarTelefono(phone);


  for (let i = 1; i < data.length; i++) {
    const telHist = normalizarTelefono(data[i][0]);
    if (telefonosCoinciden(phoneNorm, telHist)) {
      sheet.getRange(i + 1, 4).setValue(Number(data[i][3]) + 1);
      return;
    }
  }
}



// ── LOGS ──────────────────────────────────────────────────────
function logRequest(action, phone, requestData, response, ss) {
  try {
    let sheet = ss.getSheetByName(CONFIG.SHEET_LOGS);
    if (!sheet) {
      sheet = ss.insertSheet(CONFIG.SHEET_LOGS);
      sheet.getRange(1, 1, 1, 5)
           .setValues([["Timestamp", "Action", "Teléfono", "Request", "Response"]])
           .setBackground("#4285f4")
           .setFontColor("#ffffff")
           .setFontWeight("bold");
    }


    const requestTxt  = JSON.stringify(requestData);
    const responseTxt = JSON.stringify(response);


    sheet.appendRow([
      new Date(),
      action,
      phone,
      requestTxt.length > 1000 ? requestTxt.substring(0, 1000) + "…[truncado]" : requestTxt,
      responseTxt.length > 4000 ? responseTxt.substring(0, 4000) + "…[truncado]" : responseTxt
    ]);
  } catch (e) {
    Logger.log("Log error: " + e.toString());
  }
}



// ── UTILIDADES ────────────────────────────────────────────────
function normalizar(val) {
  return String(val || "").replace(/-/g, "");
}


function normalizarTelefono(val) {
  return String(val || "").replace(/\D/g, "").trim();
}


function telefonosCoinciden(a, b) {
  a = normalizarTelefono(a);
  b = normalizarTelefono(b);
  if (!a || !b) return false;
  return a === b || a.endsWith(b) || b.endsWith(a);
}


function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj, null, 2))
    .setMimeType(ContentService.MimeType.JSON);
}



// ── CORRER MODELO EN LOTES ────────────────────────────────────
function correrModelo() {
  Logger.log("\n══════════════════════════════════");
  Logger.log("CORRIENDO MODELO — " + new Date());
  Logger.log("══════════════════════════════════");

  // ── PASO 0: Eliminar duplicados antes de procesar ──────────
  limpiarDuplicadosParticipantes();
  // ──────────────────────────────────────────────────────────

  const ss    = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const sheet = ss.getSheetByName(CONFIG.SHEET_REGISTROS);
  if (!sheet) {
    Logger.log("ERROR: Hoja no encontrada");
    return;
  }


  const data    = sheet.getDataRange().getValues();
  const headers = data[0];
  const todos   = [];


  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    if (!row.some(function(c) { return c !== ""; })) continue;
    const obj = {};
    headers.forEach(function(h, j) {
      obj[h] = row[j];
    });
    todos.push(obj);
  }


  const total       = todos.length;
  const lote        = CONFIG.TAMANO_LOTE;
  const nlotes      = Math.ceil(total / lote);
  const props       = PropertiesService.getScriptProperties();
  const loteInicio  = Number(props.getProperty("LOTE_ACTUAL") || 1);
  const esNuevo     = loteInicio === 1;


  Logger.log("Total: " + total + " | Lotes: " + nlotes + " | Iniciando desde lote " + loteInicio);


  const LIMITE_MS = 5 * 60 * 1000;
  const inicio    = Date.now();


  for (let n = loteInicio; n <= nlotes; n++) {
    props.setProperty("LOTE_ACTUAL", String(n));


    if (Date.now() - inicio > LIMITE_MS) {
      Logger.log("⏱ Límite de tiempo — guardado en lote " + n);
      Logger.log("Corre correrModeloContinuar para retomar.");
      return;
    }


    const i         = (n - 1) * lote;
    const registros = todos.slice(i, i + lote);


    Logger.log("Lote " + n + "/" + nlotes + " (registros " + (i + 1) + "-" + Math.min(i + lote, total) + ")...");


    try {
      const resp = UrlFetchApp.fetch(CONFIG.API_VERCEL_BATCH, {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify({ registros: registros, todos: todos, topn: CONFIG.TOP_N }),
        muteHttpExceptions: true
      });


      const code = resp.getResponseCode();
      Logger.log("  HTTP " + code);


      if (code === 200) {
        const json = JSON.parse(resp.getContentText());
        if (json.matches && json.matches.length) {
          appendResultados(json.matches, ss, n === 1 && esNuevo);
          Logger.log("  ✓ " + json.matches.length + " matches escritos");
        }
      } else {
        Logger.log("  ERROR: " + resp.getContentText().substring(0, 200));
      }
    } catch (err) {
      Logger.log("  EXCEPCIÓN lote " + n + ": " + err.message);
    }


    if (n < nlotes) Utilities.sleep(300);
  }


  props.deleteProperty("LOTE_ACTUAL");
  Logger.log("✅ MODELO COMPLETO — " + total + " participantes, " + nlotes + " lotes.");
}



function correrModeloContinuar() {
  correrModelo();
}


function reiniciarModelo() {
  PropertiesService.getScriptProperties().deleteProperty("LOTE_ACTUAL");
  Logger.log("Progreso borrado — próximo correrModelo empieza desde lote 1.");
}


function appendResultados(matches, ss, limpiar) {
  let sheet = ss.getSheetByName(CONFIG.SHEET_RESULTADOS);
  const hdrs = [
    "tel_usuario","nombre_usuario","email_usuario","empresa_usuario",
    "tel_match","nombre_match","email_match","empresa_match",
    "cargo_match","score","nivel","razon","posicion"
  ];


  if (!sheet) {
    sheet = ss.insertSheet(CONFIG.SHEET_RESULTADOS);
    limpiar = true;
  }


  if (limpiar) {
    sheet.clearContents();
    sheet.getRange(1, 1, 1, hdrs.length)
         .setValues([hdrs])
         .setBackground("#0f9d58")
         .setFontColor("#ffffff")
         .setFontWeight("bold");
    sheet.setFrozenRows(1);
  }


  const rows = matches.map(function(m) {
    return [
      m.tel_usuario, m.nombre_usuario, m.email_usuario, m.empresa_usuario,
      m.tel_match, m.nombre_match, m.email_match, m.empresa_match,
      m.cargo_match, m.score || 0, m.nivel, m.razon, m.posicion
    ];
  });


  if (rows.length > 0) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, hdrs.length).setValues(rows);
  }
}



// ── ADMINISTRACIÓN ────────────────────────────────────────────
function testMatch() {
  const fakePost = {
    postData: {
      contents: JSON.stringify({
        info: JSON.stringify({ action: "MATCH", "Usuari@": "573157261315" })
      })
    }
  };
  Logger.log(doPost(fakePost).getContent());
}


function testContactos() {
  const fakePost = {
    postData: {
      contents: JSON.stringify({
        info: JSON.stringify({ action: "CONTACTOS", "Usuari@": "573157261315" })
      })
    }
  };
  Logger.log(doPost(fakePost).getContent());
}


function testQR() {
  const fakePost = {
    postData: {
      contents: JSON.stringify({
        info: JSON.stringify({ action: "QR", "Usuari@": "573157261315" })
      })
    }
  };
  Logger.log(doPost(fakePost).getContent());
}


function resetearUsuario() {
  const phone = "573157261315";
  const ss    = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const sheet = ss.getSheetByName(CONFIG.SHEET_HISTORIA);
  if (!sheet) return;


  const data      = sheet.getDataRange().getValues();
  const phoneNorm = normalizarTelefono(phone);


  for (let i = 1; i < data.length; i++) {
    const telHist = normalizarTelefono(data[i][0]);
    if (telefonosCoinciden(phoneNorm, telHist)) {
      sheet.deleteRow(i + 1);
      Logger.log("Historial borrado: " + phone);
      return;
    }
  }


  Logger.log("No se encontró historial para " + phone);
}


function resetearTodoElHistorial() {
  const ss    = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const sheet = ss.getSheetByName(CONFIG.SHEET_HISTORIA);
  if (!sheet || sheet.getLastRow() < 2) {
    Logger.log("Sin historial que borrar");
    return;
  }
  sheet.deleteRows(2, sheet.getLastRow() - 1);
  Logger.log("✅ Historial completo borrado.");
}


function verHistorial() {
  const ss    = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  const sheet = ss.getSheetByName(CONFIG.SHEET_HISTORIA);
  if (!sheet) {
    Logger.log("Sin historial aún");
    return;
  }
  Logger.log("Usuarios con matches guardados: " + (sheet.getLastRow() - 1));
}


function testSheet() {
  try {
    const ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
    Logger.log("✅ OK: " + ss.getName());
  } catch (e) {
    Logger.log("❌ ERROR: " + e.toString());
  }


  try {
    const ss2 = SpreadsheetApp.getActiveSpreadsheet();
    Logger.log("✅ ACTIVE OK: " + ss2.getName() + " | ID: " + ss2.getId());
  } catch (e2) {
    Logger.log("❌ ACTIVE ERROR: " + e2.toString());
  }
}
