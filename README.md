# Conciliação Ágora – Validador de Comprovantes

App Streamlit que lê a planilha do Pipefy, baixa os comprovantes (PDF/imagem), extrai o valor e compara com o valor pago.

## Como usar (Cloud)
1. Clique em **Browse files** e envie a planilha (.xlsx/.csv).
2. Ajuste nomes das colunas no painel (se necessário).
3. Clique **Validar comprovantes**.
4. Baixe o **Relatório Excel** ou **Divergências (CSV)**.

### Observação
- OCR de imagens ativo (Tesseract via `packages.txt`).
- Se algum link retornar **404**, ele aparece separado na aba “Não processados / 404”.

