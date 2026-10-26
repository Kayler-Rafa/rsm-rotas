# Prompt para modelar a interface do RSM

Cole o bloco abaixo inteiro em uma conversa nova do Claude (modo artifact/design).
Ele é autocontido: descreve o produto, os dados reais e as restrições, sem
depender deste repositório.

Depois de receber o resultado, o que interessa trazer de volta para o projeto é
o **HTML/CSS** — a lógica (`app.js`) já existe e consome a API descrita.

---

```
Preciso da interface de um app de rotas urbanas. Quero HTML + CSS em um único
arquivo, sem framework e sem build. Pode usar Leaflet por CDN para o mapa.
Use dados de exemplo embutidos, no formato que eu passo abaixo — a API real já
existe e devolve exatamente isso.

## O produto

RSM — Rotas Sustentáveis Multimodais. Um app de planejamento de viagem para a
Região Metropolitana do Recife. O usuário diz de onde e para onde, e o app
devolve algumas opções de viagem combinando a pé, bicicleta, bicicleta elétrica
compartilhada, patinete, metrô, ônibus, carro elétrico próprio e carro elétrico
de aplicativo.

A referência de experiência é um app de corrida (Uber, 99): mapa grande, poucos
campos, e opções em cards que o usuário escolhe. NÃO é um painel de dados.

## Duas telas

### 1. App (a que importa)

Elementos, e nada além disso:

- Barra fina no topo: sigla do app, as condições atuais em texto corrido, e um
  botão de tema claro/escuro.
- Campo "de onde" e campo "para onde" (selects), com um botão de inverter.
- Um interruptor discreto: "Preciso de rota acessível".
- Uma frase de sugestão do app, explicando por que ele recomendou aquela opção.
- Os cards de opção de viagem.
- Ao selecionar um card, o passo a passo do trajeto.
- Mapa ocupando o resto da tela, com a rota do card selecionado desenhada.
- No rodapé: link discreto para a tela técnica e uma nota de que os números são
  estimativa.

### 2. Tela técnica (/admin)

Só precisa de um esqueleto: abas com tabelas e um gráfico de dispersão. Não é o
foco. Se quiser, entregue só a tela do app.

## As condições são medidas, não perguntadas

O usuário NUNCA informa clima nem trânsito. O clima vem de uma API meteorológica
e o trânsito é estimado pelo horário. A barra do topo precisa deixar claro o que
é medição e o que é estimativa, sem virar um parágrafo.

Exemplo real do que chega:

```json
{
  "clima": {
    "clima": "bom",
    "descricao": "predominantemente limpo",
    "temperatura": 27.9,
    "umidade": 62,
    "precipitacao": 0.0,
    "fonte": "Open-Meteo",
    "medido_em": "2026-09-22T10:45",
    "disponivel": true,
    "calor": false
  },
  "transito": {
    "transito": "normal",
    "motivo": "dia util fora do pico",
    "hora_local": "10:53",
    "fonte": "estimativa por horario",
    "medido": false
  }
}
```

`clima` é um de: `bom`, `chuva_leve`, `chuva_forte`.
`transito` é um de: `livre`, `normal`, `congestionado`.
Se `disponivel` for `false`, a interface precisa dizer que o clima não pôde ser
medido e que o app assumiu tempo bom.

## Os cards

O app roda uma otimização multiobjetivo (tempo, custo, CO₂, esforço) e devolve
as opções não dominadas. Cada card é uma **rota distinta**, e carrega etiquetas
dizendo em que prioridades ela ganha: "mais rápida", "menor custo", "menor
emissão", "menos esforço", "equilibrada". Uma rota pode ganhar em mais de uma —
por isso as etiquetas são uma lista, não um título.

Um card vem marcado como recomendado pelo app, e a frase de sugestão explica o
porquê. **Quem escolhe é o usuário.**

Exemplo real de três cards (campos de geometria removidos por brevidade):

```json
[
  {
    "resumo": "Carro eletrico",
    "perfis": ["Equilibrada"],
    "recomendado": true,
    "tempo": 72.7, "custo": 14.57, "co2": 327.2, "co2_evitado": 3746.6,
    "dist_km": 26.28, "transferencias": 2, "recargas": 0,
    "km_expostos": 0, "usa_carro": true, "avisos": [],
    "modos": ["carro"],
    "segmentos": [
      {"tipo": "transferencia", "para_rotulo": "carro eletrico (proprio)",
       "ponto_nome": "Igreja da Se (Alto da Se)", "tempo": 2.0, "custo": 0.0},
      {"tipo": "deslocamento", "modo": "carro",
       "modo_rotulo": "carro eletrico (proprio)", "cor": "#0f766e",
       "dist_km": 26.28, "tempo": 65.7},
      {"tipo": "transferencia", "para_rotulo": "a pe",
       "ponto_nome": "Igreja de N. Sra. da Piedade", "tempo": 5.0, "custo": 8.0}
    ],
    "variante_recarga": {
      "tempo": 97.7, "custo": 40.57, "recargas": 1,
      "segmentos": [
        {"tipo": "deslocamento", "modo": "carro", "cor": "#0f766e",
         "dist_km": 18.9, "tempo": 47.2},
        {"tipo": "recarga", "local": "Eletroposto Shopping Recife",
         "rotulo": "recarga rapido (50 kW)", "tempo": 25.0, "custo": 26.0},
        {"tipo": "deslocamento", "modo": "carro", "cor": "#0f766e",
         "dist_km": 5.84, "tempo": 14.6}
      ]
    }
  },
  {
    "resumo": "Carro de app",
    "perfis": ["Mais rapida", "Menos esforco"],
    "recomendado": false,
    "tempo": 68.3, "custo": 52.93, "co2": 307.5, "co2_evitado": 3521.0,
    "dist_km": 24.7, "transferencias": 2, "km_expostos": 0,
    "usa_carro": false, "avisos": [],
    "modos": ["carro_app"]
  },
  {
    "resumo": "Bicicleta + Metro + Onibus",
    "perfis": ["Menor custo", "Menor emissao"],
    "recomendado": false,
    "tempo": 91.0, "custo": 4.10, "co2": 228.4, "co2_evitado": 4110.0,
    "dist_km": 27.4, "transferencias": 5, "km_expostos": 9.7,
    "usa_carro": false,
    "modos": ["bike", "metro", "onibus"],
    "avisos": [
      {"nivel": "info",
       "texto": "Sem horarios em tempo real na RMR: a espera e uma estimativa de 7 min."}
    ]
  }
]
```

O que cada card precisa comunicar, em ordem de importância:

1. **Como se vai** — "Carro elétrico", "Bicicleta + Metrô + Ônibus".
2. **Quanto tempo** — em destaque. Formato "1 h 09" / "45 min".
3. **Quanto custa** — em reais.
4. **Impacto** — "sem emissão" quando `co2 < 1`, senão "evita 3,7 kg de CO₂"
   (`co2_evitado` vem em gramas).
5. As etiquetas de prioridade e o selo de recomendado.

Gosto da ideia de uma **barra fina de composição modal** no card: uma barra
horizontal segmentada pela distância de cada modal, usando a cor de cada um.
Fica claro num relance que uma opção é 100% carro e outra é bicicleta + metrô.

### Cores dos modais

```
a pé                            #64748b
bicicleta                       #16a34a
bicicleta elétrica compartilhada #0891b2
patinete compartilhado          #7c3aed
metrô/VLT                       #dc2626
ônibus (diesel)                 #d97706
carro elétrico próprio          #0f766e
carro elétrico de aplicativo    #065f46
```

### Avisos

`avisos` é uma lista com `nivel` (`alerta`, `aviso`, `info`) e `texto`. Os de
nível `alerta` são os únicos que aparecem no card — o resto vai no detalhe do
trajeto. Exemplo de alerta real, quando chove e a rota tem trechos expostos:

> "Chuva forte agora: 10 km expostos. Não é a melhor hora para pedalar ou
> caminhar esse trecho."

### A opção de recarregar

Só nos cards em que `usa_carro` é `true` e existe `variante_recarga`: um
interruptor dentro do card, "Parar para recarregar", com o custo ao lado
(`+25 min · +R$ 26,00`, calculado da diferença entre a variante e o card).
Marcar troca os números do card e o traçado no mapa. **Não** dispara requisição.

Clicar no interruptor não pode selecionar/deselecionar o card.

## O mapa

- A rota é desenhada por segmento, cada um na cor do seu modal, linha grossa com
  pontas arredondadas.
- O metrô é tracejado (é trilho, não via).
- Transferências: círculo pequeno vazado.
- Parada de recarga: círculo maior e preenchido, visualmente distinto.
- Origem e destino: marcadores nas pontas.
- Eletropostos disponíveis (círculo tracejado, discreto) só aparecem quando o
  card selecionado usa o carro próprio. Isso importa: eles ficam em cima de
  pontos da via, e mostrá-los sempre fazia parecer que a viagem estava parando
  para carregar.
- No tema escuro, os tiles do OpenStreetMap são claros demais — aplique um
  filtro de inversão para eles não virarem a única área branca da tela.

## Tema claro e escuro

Obrigatório. Segue `prefers-color-scheme` por padrão, com botão para forçar, e a
escolha é lembrada. Use custom properties em `:root`, redefinidas sob
`@media (prefers-color-scheme: dark)` e sob um atributo `data-tema` no `<html>`,
com o atributo vencendo a media query.

## Direção visual

- Minimalista de verdade: pouca informação, muito espaço, hierarquia clara.
- Nada de jargão técnico na tela do app. Nenhum "Pareto", "TOPSIS", "|V|",
  "escalarizado", "desconforto". Se um número não ajuda a escolher a viagem,
  ele não entra.
- Um acento de cor só, verde-azulado (`#0f766e` no claro, `#2dd4bf` no escuro),
  usado com parcimônia.
- Tipografia de sistema, sem fonte externa.
- Funciona em telefone: abaixo de 900px o mapa vai para cima e os cards descem.
- Respeite `prefers-reduced-motion`.

## O que NÃO quero

- Framework, build, Tailwind por CDN.
- Ícones em emoji.
- Gradientes decorativos, sombras pesadas, cantos muito arredondados.
- Qualquer coisa que dê a entender que os números são medição em tempo real. São
  estimativa, e a interface tem que ser honesta sobre isso sem ser barulhenta.

Entregue um arquivo HTML completo com os dados de exemplo embutidos, para eu ver
os três cards, o card selecionado com o passo a passo, o mapa com a rota, os dois
temas e o estado de alerta de chuva.
```
