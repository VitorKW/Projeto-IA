from flask import Flask, request, jsonify
from google import genai
import os, json

app = Flask(__name__)

# 🔑 Configure sua API Key do Gemini
os.environ["GOOGLE_API_KEY"] = "CHAVE"

# Inicializa o cliente
client = genai.Client()

# Prompt fixo para garantir saída sempre no mesmo modelo
PROMPT_PADRAO = """
Você é um assistente contábil inteligente que analisa dados financeiros de empresas.

Regras obrigatórias:
- Responda SEMPRE exatamente no mesmo formato JSON abaixo.
- Não adicione texto fora do JSON.
- Preencha os valores com base nos dados recebidos.
- Se algum valor não puder ser calculado, use "0.00" ou deixe como string vazia.
- O campo "recomendado" deve ser o regime com menor imposto total anual.

MODELO FIXO DE RESPOSTA:
{
  "companyId": 123,
  "year": 2026,
  "metodo": "ia:v1:regras2025+forecastARIMA",
  "faturamentoTotalAnual": "720000.00",
  "baseMensal": [
    {
      "ano": 2026,
      "mes": 1,
      "receitaBruta": "52000.00",
      "folhaSalarios": "11000.00"
    }
  ],
  "regimes": [
    {
      "nome": "Simples Nacional - Anexo III",
      "impostoTotalAnual": "84567.22",
      "impostoTotalMensal": [
        { "mes": 1, "valor": "7000.00" }
      ],
      "aliquotaEfetiva": "0.1176",
      "detalhesTributos": {
        "IRPJ": "0.00",
        "CSLL": "0.00",
        "PIS": "3500.00",
        "COFINS": "16100.00",
        "ISS": "22000.00",
        "CPP": "21967.22"
      },
      "observacoes": "Fator R > 28%; enquadrado no Anexo III."
    },
    {
      "nome": "Lucro Presumido",
      "impostoTotalAnual": "93210.80"
    },
    {
      "nome": "Lucro Real",
      "impostoTotalAnual": "96000.00"
    }
  ],
  "recomendado": "Simples Nacional - Anexo III"
}

Agora gere a resposta conforme esse modelo, usando os dados que vou enviar.
"""

@app.route("/chat", methods=["POST"])
def chat():
    try:
        dados = request.get_json()
        if not dados:
            return jsonify({"error": "Envie um JSON válido no corpo da requisição."}), 400

        # Converte a entrada em string para enviar ao modelo
        entrada_json = json.dumps(dados, ensure_ascii=False, indent=2)

        # Chamada ao Gemini
        resposta = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=f"{PROMPT_PADRAO}\n\nEntrada:\n{entrada_json}"
        )

        texto = resposta.text.strip()

        # Tenta converter para JSON
        try:
            saida = json.loads(texto)
            return jsonify(saida)
        except:
            # Se o modelo não retornar JSON válido
            return jsonify({"raw_output": texto})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
