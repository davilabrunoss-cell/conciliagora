# -- coding: utf-8 --
"""
Validador de Comprovantes (Pipefy – 1 arquivo) • Visual Ágora
"""

import os, re, io, imghdr, requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import streamlit as st
import pandas as pd
from PIL import Image
import pytesseract
import numpy as np
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

# PDF (opcional)
try:
    import pdfplumber
except Exception:
    pdfplumber = None

# =================== Config página + CSS ===================
st.set_page_config(page_title="CONCILIÁGORA – Validador", page_icon="🧾", layout="wide")

st.markdown("""
<style>
:root {
  --teal:#23b7a2;        /* botões / boxes */
  --teal-dark:#159686;
  --bg1:#0a2f33;         /* topo gradiente */
  --bg2:#0b1c20;         /* base gradiente */
  --panel:#0e2428;       /* painel esquerdo */
  --text:#e6f6f4;
  --muted:#a6c5c1;
}
.block-container {padding-top: 1.5rem; padding-bottom: 1rem; max-width: 1220px;}
body {color: var(--text) !important;}
[data-testid="stAppViewContainer"] > .main {background: linear-gradient(180deg, var(--bg1) 0%, var(--bg2) 100%);}
.sidebar, [data-testid="stSidebar"] {background: var(--panel);}
h1,h2,h3,h4,h5,h6 {color: var(--text) !important;}
.small {color: var(--muted); font-size: 0.9rem}
.hero {font-size: 44px; font-weight: 800; letter-spacing: 1px; margin-bottom: .25rem;}
.hero .accent {color: var(--teal);}
.panel {
  background: var(--panel); border-radius: 16px; padding: 18px; border: 1px solid rgba(255,255,255,0.05);
}
.upload-box {
  background: #2dd4bf22; border: 2px dashed #2dd4bf66; padding: 18px; border-radius: 14px;
}
.stFileUploader > section > div {padding: 0 !important;}
.stFileUploader label {font-weight: 600; color: var(--text);}
.stButton>button {
  background: var(--teal); color: #062522; border: 0; padding: 10px 18px;
  font-weight: 700; border-radius: 12px;
}
.stButton>button:hover {background: var(--teal-dark);}
[data-testid="stMetricValue"] {font-weight: 800;}
.badge {display:inline-block; padding:2px 10px; border-radius:999px; font-size:12px; margin-left:8px;}
.badge.ok {background:#065f46; color:#ecfdf5;}
.badge.warn {background:#7c2d12; color:#ffedd5;}
.badge.na {background:#334155; color:#e2e8f0;}
table td, table th {white-space: nowrap;}
</style>
""", unsafe_allow_html=True)

# =================== Utilidades ===================
ATT_DIR = os.path.abspath("anexos")
os.makedirs(ATT_DIR, exist_ok=True)

def read_table(uploaded):
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    data = uploaded.read()
    try:
        return pd.read_csv(io.BytesIO(data), sep=None, engine="python")
    except Exception:
        for sep in [";", ",", "\t", "|"]:
            try:
                return pd.read_csv(io.BytesIO(data), sep=sep)
            except Exception:
                continue
    raise ValueError("Não consegui ler o arquivo. Exporte como XLSX/CSV simples.")

def sanitize_filename(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9.-]+", "", name)[:120]
    return base or "arquivo"

def parse_ptbr_number(txt: str):
    try:
        return float(str(txt).replace('.', '').replace(',', '.'))
    except Exception:
        return None

def iter_amount_spans(text: str):
    if not text: return
    rx_all = re.compile(r'(?:R\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})|([0-9]+,[0-9]{2})', re.MULTILINE)
    for m in rx_all.finditer(text):
        raw = m.group(1) or m.group(2)
        if not raw: continue
        val = parse_ptbr_number(raw)
        if val is None: continue
        yield (val, m.start(), m.end(), raw)

def pick_best_amount(text: str, expected: float, tol: float = 0.02):
    if expected is None: return None, None, "", None
    best = best_delta = best_span = best_raw = None
    for val, a, b, raw in iter_amount_spans(text):
        delta = abs(val - abs(float(expected)))
        if best is None or delta < best_delta:
            best, best_delta, best_span, best_raw = val, delta, (a,b), raw
    if best is None: return None, None, "", None
    a,b = best_span; start = max(0, a-40); end = min(len(text), b+40)
    snippet = text[start:end].replace("\n"," ")
    return best, (best - abs(float(expected))), snippet, best_raw

def extract_text_from_pdf(path):
    if not pdfplumber: return ""
    try:
        out = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[:5]:
                out.append(page.extract_text() or "")
        return "\n".join(out)
    except Exception:
        return ""

def extract_text_from_image(path):
    try:
        img = Image.open(path)
        return pytesseract.image_to_string(img, lang="por+eng") or ""
    except Exception:
        return ""

def sniff_is_image(path):
    try:
        return imghdr.what(path) in {"jpeg","png","gif","bmp","tiff"}
    except Exception:
        return False

def download_one(url: str, suggested_name: str):
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            return None, f"http_status_{r.status_code}"
        fname = None
        cd = r.headers.get('Content-Disposition')
        if cd and 'filename=' in cd:
            fname = cd.split('filename=')[-1].strip('"')
        if not fname:
            fname = sanitize_filename(suggested_name)
        path = os.path.join(ATT_DIR, fname)
        with open(path, 'wb') as f:
            f.write(r.content)
        return path, "ok"
    except requests.exceptions.RequestException:
        return None, "network_error"
    except Exception:
        return None, "download_error"

def to_float_br(x):
    if pd.isna(x): return None
    if isinstance(x, (int, float)): return float(x)
    s = str(x).replace("R$","").replace(".","").replace(",",".").strip()
    try: return float(s)
    except Exception: return None

def sanitize_for_excel_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]) or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(lambda x: (np.nan if pd.isna(x) else ILLEGAL_CHARACTERS_RE.sub("", str(x))))
    return out

# Detecta OCR disponível (para cloud avisar)
def ocr_disponivel() -> bool:
    try:
        _ = pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False

OCR_OK = ocr_disponivel()
if not OCR_OK:
    st.info("🔎 OCR não disponível neste ambiente. PDFs com texto serão lidos; imagens podem ficar como 'Não processados'.")

# =================== Layout principal ===================
left, right = st.columns([0.36, 0.64], gap="large")

with left:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    # Logo + título painel
    if os.path.exists("agora_logo.png"):
        st.image("agora_logo.png", width=120)
    st.markdown("### Mapeamento de colunas")
    col_codigo     = st.text_input("Coluna do Código (opcional)", "Código")
    col_valor_pago = st.text_input("Coluna do Valor pago", "Valor pago")
    col_url        = st.text_input("Coluna do comprovante", "Comprovante de pagamento")

    st.markdown("### Parâmetros")
    tol_centavos = st.number_input("Tolerância de valor (R$)", value=0.02, min_value=0.00, step=0.01, format="%.2f")
    max_workers  = st.slider("Download simultâneos", 1, 10, 6)
    st.markdown("</div>", unsafe_allow_html=True)

with right:
    # Hero
    st.markdown(
        "<div class='hero'>CONCILI<span class='accent'>ÁGORA</span></div>"
        "<div class='small'>Validador de Comprovantes</div>",
        unsafe_allow_html=True
    )

    st.markdown("*📄 Envie a planilha do Pipefy (XLSX/CSV)*")
    st.markdown("<div class='upload-box'>", unsafe_allow_html=True)
    up = st.file_uploader(" ", type=["xlsx","xls","csv"], label_visibility="collapsed", key="pipefy")
    st.markdown("</div>", unsafe_allow_html=True)

    run = st.button("Validar comprovantes")

# =================== Execução ===================
if run:
    if not up:
        st.warning("Envie a planilha primeiro.")
        st.stop()

    df = read_table(up)

    # checagem de colunas
    for col, label in [(col_valor_pago, "Valor pago"), (col_url, "URL do comprovante")]:
        if col not in df.columns:
            st.error(f"Não encontrei a coluna *{label}* ('{col}') na planilha. Ajuste no painel esquerdo.")
            st.stop()

    valores = df[col_valor_pago].apply(to_float_br)
    urls    = df[col_url].astype(str).fillna("").tolist()
    codigos = df[col_codigo] if col_codigo in df.columns else pd.Series([None]*len(df))

    st.info("Baixando comprovantes…")
    paths, statuses = [None]*len(urls), [""]*len(urls)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {}
        for idx, u in enumerate(urls):
            if isinstance(u, str) and u.startswith("http"):
                sug = f"row{idx+1}_" + sanitize_filename(os.path.basename(u.split("?")[0]) or "comprovante")
                futures[ex.submit(download_one, u, sug)] = idx
        for fut in as_completed(futures):
            i = futures[fut]
            p, status = fut.result()
            paths[i], statuses[i] = p, status

    st.success("Downloads concluídos. Processando arquivos…")

    contains, notes = [], []
    found_amounts, found_raws, diffs, snippets = [], [], [], []

    for i in range(len(df)):
        amount = valores.iloc[i]; url = urls[i]; p = paths[i]; status = statuses[i]
        ok = None; note = ""; found_amt = None; found_raw = None; diff_val = None; snippet = ""
        if not url or not isinstance(url, str) or not url.startswith("http"):
            ok = None; note = "sem_URL"
        elif status != "ok" or not p or not os.path.exists(p):
            ok = None; note = status or "download_falhou"
        else:
            try:
                if p.lower().endswith(".pdf") and pdfplumber:
                    txt = extract_text_from_pdf(p)
                    found_amt, diff_val, snippet, found_raw = pick_best_amount(txt, amount, tol=tol_centavos)
                    if txt.strip() == "": note = "pdf_sem_texto"
                    ok = (found_amt is not None and abs(diff_val) <= tol_centavos)
                elif sniff_is_image(p):
                    if OCR_OK:
                        txt = extract_text_from_image(p)
                        found_amt, diff_val, snippet, found_raw = pick_best_amount(txt, amount, tol=tol_centavos)
                        ok = (found_amt is not None and abs(diff_val) <= tol_centavos)
                    else:
                        ok = None; note = "ocr_indisponivel"
                else:
                    ok = False; note = "tipo_não_suportado"
            except Exception:
                ok = None; note = "erro_processamento"

        contains.append(ok); notes.append(note)
        found_amounts.append(found_amt); found_raws.append(found_raw)
        diffs.append(diff_val); snippets.append(snippet)

    out = pd.DataFrame({
        "Código": codigos,
        "Valor pago": df[col_valor_pago],
        "Valor pago (num)": valores,
        "URL comprovante": urls,
        "Arquivo local": paths,
        "Status download": statuses,
        "Comprovante contém o valor?": contains,
        "Valor encontrado no comprovante (num)": found_amounts,
        "Valor encontrado (texto)": found_raws,
        "Diferença (encontrado - pago)": diffs,
        "Trecho do texto (amostra)": snippets,
        "Obs": notes
    })

    # ======== Métricas de topo ========
    ok_qtd = sum(1 for x in out["Comprovante contém o valor?"] if x is True)
    no_qtd = sum(1 for x in out["Comprovante contém o valor?"] if x is False)
    na_qtd = sum(1 for x in out["Comprovante contém o valor?"] if x is None)

    st.subheader("Resumo")
    m1, m2, m3 = st.columns(3)
    m1.metric("✔️ Valor encontrado", ok_qtd)
    m2.metric("❌ Divergências", no_qtd)
    m3.metric("⚠️ Não processados", na_qtd)
    status_badge = ('<span class="badge ok">OK</span>' if no_qtd==0 and na_qtd==0
                    else '<span class="badge warn">atenção</span>' if no_qtd>0
                    else '<span class="badge na">parcial</span>')
    st.markdown(f"*Status:* {status_badge}", unsafe_allow_html=True)

    # ======== Abas ========
    tab1, tab2, tab3 = st.tabs(["📋 Auditoria completa", "⚠️ Divergências", "🚧 Não processados / 404"])

    with tab1:
        st.dataframe(out, use_container_width=True, height=460)

    with tab2:
        diverg = out[out["Comprovante contém o valor?"] == False][
            ["Código","Valor pago","Valor encontrado no comprovante (num)","Diferença (encontrado - pago)"]
        ].copy()
        diverg = diverg.sort_values(by="Diferença (encontrado - pago)", key=lambda s: s.abs(), ascending=False)
        st.dataframe(diverg, use_container_width=True, height=400)
        if not diverg.empty:
            st.download_button("⬇️ Baixar divergências (CSV)",
                               data=diverg.to_csv(index=False).encode("utf-8"),
                               file_name="divergencias.csv",
                               mime="text/csv")

    with tab3:
        na = out[out["Comprovante contém o valor?"].isna()][["Código","Valor pago","URL comprovante","Status download","Obs"]]
        st.dataframe(na, use_container_width=True, height=400)
        only404 = na[na["Status download"]=="http_status_404"]
        if not only404.empty:
            st.download_button("⬇️ Baixar apenas 404 (CSV)",
                               data=only404.to_csv(index=False).encode("utf-8"),
                               file_name="links_404.csv",
                               mime="text/csv")

    # ======== Exportar Excel (saneado) ========
    out_name = f"auditoria_comprovantes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    aud_all  = sanitize_for_excel_df(out)
    aud_fail = sanitize_for_excel_df(out[out["Comprovante contém o valor?"] == False])
    aud_na   = sanitize_for_excel_df(out[out["Comprovante contém o valor?"].isna()])

    with pd.ExcelWriter(out_name) as writer:
        aud_all.to_excel(writer, index=False, sheet_name="Auditoria")
        aud_fail.to_excel(writer, index=False, sheet_name="Nao_bateu")
        aud_na.to_excel(writer, index=False, sheet_name="Nao_processado")

    with open(out_name, "rb") as f:
        st.download_button("⬇️ Baixar relatório Excel",
                           f, file_name=out_name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.markdown("---")
st.caption("Feito com ❤️ pela dupla Bruno & Luna • Modo: *apenas planilha do Pipefy (links dos comprovantes)*.")