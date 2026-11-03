# Example 2 — Store information and policies

**Scenario:** A customer from another city asks for the address, whether the store is open right now (Saturday 12:30, it closes at 13:00), delivery to Dourados and paying part with PIX and part by card.

**What it demonstrates:**

- Answers grounded only in the policy manual (no tools needed) — challenge scenario 2.
- Awareness of the current time: open/closed status and closing time computed in code.
- Applying conditional rules (combined payment only above R$ 2.000; freight outside the metro area).

**How it was generated:** a real, unedited run of the agent (`python -m examples.generate_examples`) with model `gemini-3.5-flash-lite` and the store clock pinned to `2026-03-28T12:30`. Each tool call is shown with its raw result in a collapsible block.

---

## Transcript

**Cliente:** Qual o endereço da loja?

**Lia:** Rua 14 de Maio, 3200, Centro, Campo Grande - MS. Estamos te esperando por aqui! 🎸

**Cliente:** Vocês estão abertos agora? Dá tempo de eu passar aí?

**Lia:** Sim, estamos abertos hoje até as 13:00! Se conseguir passar até lá, dá tempo sim. Passa aqui para dar uma olhada nos instrumentos! 🎸

**Cliente:** Na verdade moro em Dourados. Vocês entregam aí? Quanto tempo demora?

**Lia:** Entregamos sim para Dourados! Nós enviamos pelos Correios ou pela transportadora Jadlog. O prazo varia conforme a modalidade:

- SEDEX (Correios): 2 a 5 dias úteis
- Jadlog: 3 a 8 dias úteis
- PAC (Correios): 5 a 12 dias úteis

O valor do frete e o prazo exato são calculados na hora com o seu CEP. Posso te ajudar a escolher algum instrumento?

**Cliente:** Se eu comprar um violão de R$ 2.500, posso pagar uma parte no PIX e o resto no cartão?

**Lia:** Sim! Nós permitimos a combinação de formas de pagamento (como PIX + cartão) para compras acima de R$ 2.000,00. 

Se quiser, posso te mostrar algumas opções de violões nessa faixa de preço para você escolher. Posso listar?
