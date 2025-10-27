# Projeto-IA 
<img width="886" height="493" alt="image" src="https://github.com/user-attachments/assets/68e0a99a-582d-4865-a5b5-280b2e846a81" />

Entrada: {
  "companyId": 123,
  "year": 2026,
  "useAiForecast": true,
  "historicalMonthly": [
    {
      "ano": 2024,
      "mes": 12,
      "receitaBruta": "48000.00",
      "folhaSalarios": "10000.00",
      "lucroLiquidoContabil": "3000.00",
      "insumosCreditoPisCofins": "2500.00",
      "retencaoIRPJ": "0.00",
      "retencaoCSLL": "0.00"
    }
  ],
  "targetYearMonthly": [
    {
      "ano": 2026,
      "mes": 1,
      "receitaBruta": "52000.00",
      "folhaSalarios": "11000.00",
      "lucroLiquidoContabil": "3100.00",
      "insumosCreditoPisCofins": "2700.00",
      "retencaoIRPJ": "0.00",
      "retencaoCSLL": "0.00"
    }
  ]
}


Saída: 
{
    "raw_output": "```json\n{\n  \"companyId\": 123,\n  \"year\": 2026,\n  \"metodo\": \"ia:v1:regras2025+forecastARIMA\",\n  \"faturamentoTotalAnual\": \"624000.00\",\n  \"baseMensal\": [\n    {\n      \"ano\": 2026,\n      \"mes\": 1,\n      \"receitaBruta\": \"52000.00\",\n      \"folhaSalarios\": \"11000.00\"\n    }\n  ],\n  \"regimes\": [\n    {\n      \"nome\": \"Simples Nacional - Anexo V\",\n      \"impostoTotalAnual\": \"82867.20\",\n      \"impostoTotalMensal\": [\n        {\n          \"mes\": 1,\n          \"valor\": \"6905.60\"\n        }\n      ],\n      \"aliquotaEfetiva\": \"0.1328\",\n      \"detalhesTributos\": {\n        \"IRPJ\": \"20716.80\",\n        \"CSLL\": \"12430.08\",\n        \"PIS\": \"2303.71\",\n        \"COFINS\": \"10623.57\",\n        \"ISS\": \"12885.85\",\n        \"CPP\": \"23908.20\"\n      },\n      \"observacoes\": \"Fator R < 28%; enquadrado no Anexo V.\"\n    },\n    {\n      \"nome\": \"Lucro Presumido\",\n      \"impostoTotalAnual\": \"101899.20\"\n    },\n    {\n      \"nome\": \"Lucro Real\",\n      \"impostoTotalAnual\": \"94851.00\"\n    }\n  ],\n  \"recomendado\": \"Simples Nacional - Anexo V\"\n}\n```"
}
