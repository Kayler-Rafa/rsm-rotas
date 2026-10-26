# RSM — Rotas Sustentáveis Multimodais

MVP web do sistema de recomendação de rotas sustentáveis para a Região
Metropolitana do Recife, construído sobre a modelagem das Etapas 1 e 2 do
projeto (Faculdade Nova Roma — Análise e Projeto de Complexidade de Algoritmos).

**Corredor de referência:** Igreja da Sé (Alto da Sé, Olinda) ⇄ Igreja de Nossa
Senhora da Piedade (Jaboatão dos Guararapes) — 18,7 km em linha reta, 22,4 km de
carro pela via real, atravessando três municípios.

## Como rodar

Não há nada para instalar: o backend usa apenas a biblioteca padrão do Python 3.

```bash
python src/server.py
```

Depois abra <http://localhost:8000>. Para usar outra porta: `python src/server.py 8080`.

Para conferir que as rotas estão corretas:

```bash
python -m unittest discover -s tests -v
```

O mapa carrega tiles do OpenStreetMap e a biblioteca Leaflet por CDN, então a
interface precisa de internet. Todo o cálculo de rotas é local.

## Duas telas

### `/` — o app

Uma decisão por vez: **escolher a viagem**. Você informa de onde e para onde, e
o app devolve as opções em cards — como um aplicativo de corrida.

- **As condições não são perguntadas.** Clima vem do Open-Meteo em tempo real
  (sem chave de API); trânsito é estimado pelo horário. A barra do topo mostra o
  que foi medido e o que foi estimado.
- **Cards por prioridade** — mais rápida, menor custo, menor emissão, menos
  esforço e equilibrada. Perfis que caem na mesma rota viram um card só, com as
  prioridades que ele atende como etiquetas.
- **O app sugere um e explica em uma frase**; quem escolhe é você. Sob chuva
  forte ele sugere a opção abrigada e avisa nos cards expostos que não é hora de
  pedalar. No pico, sugere o que não depende do trânsito.
- **Parada para recarregar** aparece como interruptor no card que usa o carro
  elétrico próprio, com o custo em tempo e dinheiro ao lado. Você decide. A
  variante já vem calculada, então a troca é instantânea.
- **Escuro por padrão**, com botão para o claro. O visual segue o design do
  artifact `6GbHjBDz9TsGkrBF8vaR98`: mapa em tela cheia e painel flutuante (no
  celular, uma folha que se arrasta).

### `/admin` — a análise técnica

Tudo o que sustenta o relatório da disciplina, fora do caminho do usuário:
fronteira de Pareto completa, Dijkstra × A\*, viabilidade por modal, efeito
isolado de cada condição, Martins × NSGA-II, propriedades do grafo — e controles
manuais de modais, clima, trânsito e segurança para experimentar.

| Aba | O que mostra |
|---|---|
| **Alternativas** | Fronteira de Pareto (Martins), gráfico tempo × custo colorido por emissão, e a recomendação de cada perfil por TOPSIS sobre a mesma fronteira |
| **Viabilidade dos modais** | Para cada modal, a melhor viagem usando **somente ele mais a caminhada** |
| **Efeito das condições** | Varia *uma* condição por vez, isolando clima, trânsito e segurança |
| **Dijkstra × A\*** | Vértices expandidos, redução do espaço de busca e verificação de que ambos chegam à mesma rota |
| **Eixo metroferroviário** | Melhor rota obrigada a passar pelo metrô, contra a melhor rota livre |
| **Exato × NSGA-II** | Fronteira exata contra a aproximada, com cobertura e avaliações |

## Como as rotas são calculadas

**Os pontos vêm do OpenStreetMap, não de memória.** A primeira versão tinha a
Igreja da Sé a ~790 m do lugar, a Estação Tancredo Neves a 3,3 km, uma estação
inventada e duas faltando — e isso, junto com velocidades que eu tinha atribuído
à mão, fazia a rota de carro sair pelo interior e passar pelo aeroporto. Hoje:

- estações do metrô e igrejas: nós do OSM consultados via Overpass;
- pontos de rua: tirados das manobras da rota real do roteador (OSRM), portanto
  sobre a via certa.

**Carro e carro de app andam pela via real.** Não percorrem os pontos do modelo:
são arestas-atalho com a distância e o tempo que o OSRM calcula sobre toda a
malha do OpenStreetMap. O OSRM dá tempo em fluxo livre; o Recife não anda em
fluxo livre, então o tempo é multiplicado por **1,647** — o índice TomTom de
64,7% do Recife é definido exatamente como tempo extra sobre o fluxo livre. Sé →
Piedade: 27,8 min livres → **45,7 min típicos**, pela mesma rota que o roteador
escolhe (Agamenon, Cruz Cabugá, centro, Ponte Paulo Guerra, Domingos Ferreira,
Visconde de Jequitinhonha, Ayrton Senna).

| Modal | Distância | Tempo |
|---|---|---|
| carro, carro de app | via real (OSRM) | fluxo livre × 1,647 × trânsito |
| ônibus | via real entre pontos do corredor | fluxo livre × 1,647 × 1,35 (paradas) × trânsito |
| a pé, bicicletas | rota real a pé / de bicicleta, sem mão única | ÷ velocidade do modal |
| metrô | linha reta × 1,05 | ÷ 32 km/h |

Os dados do roteador ficam em cache em `dados/` (uma matriz 30×30 e os traçados).
Para refazer — obrigatório se algum ponto mudar:

```bash
python src/geometria.py
```

**A pé e de bicicleta não existe mão única.** Esses traçados vêm do roteador do
FOSSGIS (`routing.openstreetmap.de`, perfis a pé e de bicicleta sobre o
OpenStreetMap). A bicicleta fica com o menor caminho entre o perfil de bike, nos
dois sentidos, e o perfil a pé. Exemplo: de Pina à Ponte Paulo Guerra, o carro
contorna 3,48 km; de bicicleta são 0,26 km.

Esses perfis excluem vias expressas (`trunk`), que no Recife incluem avenidas
com calçada e ciclovia, como a Agamenon e a Av. Sul. Onde o caminho do carro é
mais curto, é ele que vale.

Para refazer só essa parte: `python src/geometria.py --so-ativos --forcar`.

## Segurança viária

O app **não manda quem anda ou pedala por rua perigosa**, e diz quando desviou e
por quê.

- **Dado:** sinistros de trânsito da CTTU no Recife, 2022–2024. São 12.016
  registros, obtidos pela API do Portal de Dados Abertos do Recife. Para cada
  rua, calcula-se a densidade de sinistros com pedestre e com ciclista por km
  por ano.
- **Níveis:**
  - **Inseguro:** rua entre as 10% arteriais do Recife mais perigosas para
    aquele usuário. O trecho sai da rota a pé ou de bicicleta.
  - **Atenção:** rua entre as 25% mais perigosas. É permitida e avisada.
  - **Sem dado** (Olinda, Jaboatão): isso é dito ao usuário, e nunca tratado
    como seguro.
  - A avaliação usa as ruas por onde o pedestre ou o ciclista realmente passa.
    Uma rua com menos de 5 sinistros no período não bloqueia sozinha, porque
    com contagens tão pequenas o veredito vira ruído.
- Quando o filtro muda a escolha, o card mostra, por exemplo: *"Não te mandamos
  a pé pela Avenida Dantas Barreto: 10 sinistros com pedestre em 2022–2024
  (CTTU), entre as 10% vias mais perigosas do Recife para quem anda. A
  alternativa segura (Carro elétrico) custa +R$ 6,43 e leva 17 min a menos."*

**Limite:** isto é segurança **viária**. Não existe dado aberto de
criminalidade por rua na RMR: o conjunto de ocorrências da Guarda Municipal está
publicado sem nenhum arquivo.

Para refazer os dados: `python src/seguranca.py`.

## Atualização automática

A tela recalcula as opções **a cada minuto** (só com a aba visível) e mantém a
opção que você escolheu. Se a sugestão mudar, por exemplo porque começou a
chover ou entrou a hora de pico, o texto avisa.

## Condições automáticas

| O quê | Fonte | Natureza |
|---|---|---|
| Clima | [Open-Meteo](https://open-meteo.com), sem chave, cache de 5 min (a fonte atualiza a cada 15) | **medição** |
| Trânsito | heurística de horário (pico útil 06:30–09:00 e 16:30–19:30) | **estimativa** |

Não há fonte aberta de trânsito em tempo real para a RMR; a faixa de pico vem do
índice TomTom agregado (Recife é a capital brasileira mais congestionada, 64,7%).
A interface diz qual das duas é medida e qual é estimada.

Se a rede falhar, o app assume tempo bom e **avisa que assumiu** — uma previsão
errada silenciosa seria pior do que declarar a ausência de dado.

## Estrutura

```
rotas/
├── src/
│   ├── rede_rsm.py    modelo da rede: modais, pontos, trechos, transferências,
│   │                  eletropostos, opções do usuário e construção do grafo
│   ├── algoritmos.py  Dijkstra, A*, dominância, Martins, NSGA-II e TOPSIS
│   ├── clima.py       condições automáticas (Open-Meteo + heurística de trânsito)
│   ├── seguranca.py   segurança viária por rua (sinistros da CTTU + OSM)
│   ├── geometria.py   traçado e distância reais das vias (OSRM/OpenStreetMap)
│   ├── motor.py       consulta, rota, cards do app e análise de viabilidade
│   └── server.py      servidor HTTP (biblioteca padrão)
├── tests/
│   └── test_rotas.py  18 testes de corretude das rotas, dos algoritmos e da segurança
├── dados/
│   ├── matriz_carro.json   distância e tempo de carro entre os 30 pontos (OSRM)
│   ├── geometria.json      traçados reais (OSRM)
│   ├── seguranca_cttu.json sinistros por rua (CTTU 2022–2024) e ruas de cada trecho
│   └── estacoes_osm.json · rota_referencia_steps.json   fontes das coordenadas
└── web/
    ├── tokens.css     cores claro/escuro, comum às duas telas
    ├── index.html · app.css · app.js      app do usuário   (/)
    └── admin.html · admin.css · admin.js  análise técnica  (/admin)
```

Rodar `python src/rede_rsm.py` imprime |V|, |E| e densidade para várias
combinações de opções, mais uma tabela do custo de percorrer o corredor inteiro
em cada modal.

## API

**Do app:**

| Rota | Parâmetros | Retorna |
|---|---|---|
| `GET /api/opcoes` | `origem`, `destino`, `acessivel` | condições medidas, os cards e qual é recomendado |
| `GET /api/condicoes-atuais` | `forcar` | clima e trânsito correntes |

**Da análise técnica:**

| Rota | Parâmetros | Retorna |
|---|---|---|
| `GET /api/rede` | — | pontos, trechos, modais, eletropostos, climas, trânsitos, seguranças e perfis |
| `GET /api/rota` | `normalizacao`, `pareto` | Dijkstra, A\*, fronteira de Pareto, TOPSIS e contraprova do metrô |
| `GET /api/condicoes` | `normalizacao` | varia uma dimensão por vez (clima, trânsito, segurança) |
| `GET /api/viabilidade` | — | veredito de viabilidade por modal |
| `GET /api/nsga2` | — | comparação Martins × NSGA-II |

Todas aceitam `origem`, `destino`, `perfil`, `modos` (lista separada por
vírgula), `clima`, `transito`, `seguranca`, `acessivel` e `recarga`.

## Modelagem

Grafo dirigido e ponderado `G = (V, E)` com `V ⊆ P × M × F × R`. Cada vértice é
uma quádrupla **(ponto, modal, já usou veículo individual, já recarregou)**.
Arestas de **deslocamento** preservam o modal; de **transferência** preservam a
posição e cobram o custo da troca; de **recarga** viram o bit R. Cada aresta
carrega um vetor de quatro componentes, não um escalar:

```
w(e) = [ tempo (min), custo (R$), CO₂ (g), desconforto ]
desconforto = dist × δ_modo × (2 − segurança) × α_cenário
```

Grafo do corredor com todos os modais: **30 pontos, 44 trechos (10 de metrô),
8 modais → 228 vértices e 698 arestas**, densidade 3,06 (rede esparsa, o que
justifica a lista de adjacência com espaço O(V+E)). Com a parada de recarga
ligada, 466 e 1.577.

### O bit F: um veículo individual por viagem

O terceiro componente do vértice registra se a viagem **já embarcou em um
veículo individual**. Camadas de veículo individual só existem com o bit
em 1, e só se entra nelas a partir do bit 0. A consequência é que uma viagem usa
no máximo **um** veículo individual.

É o que impede rotas fisicamente absurdas — "pedala a bicicleta própria, larga no
meio do caminho e aluga uma elétrica" — sem impedir as combinações que de fato
ocorrem, porque as camadas coletivas (a pé, ônibus, metrô) existem nos dois
estados:

- a pé + metrô, a pé + ônibus + metrô
- bicicleta + metrô (bicicletário na estação)
- carro + metrô (*park-and-ride*)

Regras complementares de embarque e desembarque:

| Tipo de modo | Onde embarca | Onde desembarca |
|---|---|---|
| **Próprio** (bicicleta, carro elétrico) | só na origem | destino, ou estação/terminal com vaga |
| **Compartilhado** (bike elétrica, patinete) | pontos de micromobilidade, **só no Recife** | idem |
| **Aplicativo** (carro elétrico de app) | origem, destino, estações e terminais | idem |

Na origem e no destino da consulta sempre se pode pegar ou deixar o próprio
carro, a bicicleta ou um carro de app, qualquer que seja o tipo do ponto.

### O bit R: parada de recarga

Só é desdobrado quando o usuário pede a parada — sem ele, todo o grafo fica em
R=0 e |V| não cresce. A aresta de recarga no eletroposto é a única que vira R de
0 para 1, e o destino só é aceito com R=1. Obrigar a parada vira, assim, uma
**restrição estrutural do grafo**, resolvida pela mesma busca.

Além disso, toda viagem **termina a pé**: o destino só é aceito no nó pedestre.
Sem isso o Dijkstra encerrava no nó do carro e a rota nunca pagava o desembarque
— nem o tempo de estacionar, nem a vaga.

### Modais e custos

| Modal | km/h | Preço | g CO₂eq/km | Elétrico |
|---|---|---|---|---|
| a pé | 4,8 | — | 0 | — |
| bicicleta (própria) | 14,0 | — | 0 | — |
| bicicleta elétrica compartilhada | 18,0 | R$ 0,55/**min** + R$ 1,00 desbloqueio | 0,83 | sim |
| patinete compartilhado | 16,0 | R$ 0,65/**min** + R$ 1,00 desbloqueio | 1,25 | sim |
| metrô/VLT | 32,0 | R$ 4,10 (tarifa) | 3,70 | sim |
| ônibus | 18,0 | R$ 4,10 (tarifa) | 68,00 | **não** |
| carro elétrico (próprio) | via real ¹ | R$ 0,25/km + R$ 8,00 estacionamento | 12,45 | sim |
| carro elétrico de aplicativo | via real ¹ | R$ 1,90/km + R$ 6,00 bandeirada | 12,45 | sim |

¹ Tempo do OSRM × 1,647. O ônibus também usa o tempo de via (× 1,35 de paradas);
o 18 km/h da tabela só vale se a matriz do OSRM não existir.

A integração temporal VEM (2 h) isenta a troca direta ônibus ⇄ metrô de nova
tarifa.

### Complexidade

| Algoritmo | Tempo | Espaço |
|---|---|---|
| Construção do grafo | O(\|T\|·\|M\| + \|P\|·\|M\|²) | O(V+E) |
| Dijkstra (min-heap) | O((V+E) log V) = O(E log V) | O(V+E) |
| A\* | O(E log V) no pior caso | O(V+E) |
| Martins (Pareto exato) | O(N log N + N·d·k) | O(N) |
| NSGA-II | O(G·P²·d) | O(P) |
| TOPSIS | O(k·d) | O(k·d) |

O bit de estado dobra |V| no pior caso, mas não altera nenhuma dessas ordens.

## Diferenças em relação à Etapa 2

O par origem–destino mudou de Piedade → Praça de Boa Viagem (~5 km,
intramunicipal) para Sé de Olinda → Igreja de Piedade (18,7 km em linha reta, três
municípios), e o conjunto de modais foi revisto. Isso muda resultados de forma
substantiva:

1. **As "soluções mistas" da Etapa 2 eram um artefato do modelo.** A §5.2 do
   relatório apresentava rotas que combinam bicicleta própria com bicicleta
   elétrica como evidência de que a formulação multiobjetivo acrescenta
   informação. Elas são fisicamente impossíveis: ninguém abandona a própria
   bicicleta no meio do trajeto. Com o bit de estado, **21 das 28 rotas da
   fronteira anterior desapareceram** — e as combinações que sobram são as
   reais (bicicleta + metrô, carro + metrô, a pé + ônibus + metrô).

2. **O custo da micromobilidade estava por quilômetro; a cobrança real é por
   minuto.** Pelo modelo antigo, atravessar o corredor de bicicleta elétrica
   custava R$ 11,80. Com cobrança por minuto são **R$ 45,00** — e o patinete,
   R$ 59,50. Isso reclassifica os dois de "competitivos" para inviáveis neste
   par origem–destino, o que corresponde ao que eles são: modos de primeira e
   última milha.

3. **O metrô deixa de ser descartável.** Na Etapa 2 forçar o eixo
   metroferroviário custava +228,5% no tempo, porque origem e destino ficavam
   ambos sobre a orla. No corredor atual a Linha Sul corre aproximadamente na
   direção da viagem e a rota via metrô passa a ser competitiva.

4. **"A pé + metrô" sozinho não serve este corredor.** A aba de viabilidade
   mostra por quê: a Linha Sul começa na Estação Recife e Olinda não é servida
   por trilho, então a perna a pé passa de 10 km. O par que funciona é
   **ônibus/bicicleta + metrô**, e é o que o perfil "menor custo" recomenda —
   R$ 4,10 na integração VEM.

5. **A heurística do A\* precisou mudar de limite.** A Etapa 2 dividia a
   distância em linha reta pela maior velocidade *nominal* da rede (metrô,
   32 km/h). Com o carro andando na velocidade real das vias, isso deixa de ser
   seguro: com trânsito livre o carro cobre 39,1 km/h em linha reta, a heurística
   superestimaria e o A\* poderia devolver rota errada. O limite agora é medido
   no próprio grafo — a maior velocidade em linha reta de qualquer aresta —, o
   que garante admissibilidade por construção. Verificado: A\* = Dijkstra em
   870 pares × 3 condições de trânsito.

6. **A normalização do TOPSIS passa a importar.** Na Etapa 2 a emissão variava
   de 0 a 4,4 g na fronteira inteira e a normalização era irrelevante. Aqui ela
   varia de 0 a mais de 1.000 g, e a normalização vetorial clássica faz o peso
   efetivo de cada critério depender da **dispersão** da coluna: a emissão passa
   a dominar mesmo com peso 0,10, e quatro dos cinco perfis colapsam na mesma
   rota. O MVP usa min-max por padrão, que reescala cada critério para [0,1] e
   faz os pesos significarem o que dizem — a vetorial continua selecionável na
   interface para tornar o efeito visível.

7. **A assimetria regulatória virou regra estrutural do grafo.** Micromobilidade
   compartilhada só é instanciada em pontos do Recife, porque a regulamentação
   levantada na Etapa 1 não alcança Olinda nem Jaboatão. Na Etapa 2 isso existia
   apenas como cenário.

8. **Correção de bug herdado.** O cruzamento do NSGA-II listado na §4.5 do
   relatório trunca a lista de nós na remoção de ciclos sem atualizar o conjunto
   de visitados, e o `index()` seguinte estoura com `ValueError`. Se o código
   original da Etapa 2 ainda for executado, tem o mesmo defeito latente.

## Ressalvas

Estes números são **estimativa**, não medição:

- Não há feed GTFS aberto nem API de tempo real para os ônibus da RMR. O modelo
  é estático e determinístico: representa a oferta típica, não o estado
  instantâneo da rede. Os tempos de espera são penalidades fixas de
  transferência.
- **Não existe frota de ônibus elétrico em operação na RMR.** O ônibus é
  modelado como diesel, a 68 g CO₂eq/km, e é a única fonte relevante de emissão
  entre os modais disponíveis.
- A emissão dos modais elétricos é **operacional** (0,15 kWh/km × 83 g CO₂eq/kWh
  da matriz brasileira), enquanto o baseline de comparação — 155 g CO₂eq/km do
  automóvel flex compacto, ICCT 2023 — é de **ciclo de vida**. A comparação
  favorece levemente o elétrico.
- O custo do carro próprio cobre energia, desgaste e uma vaga de R$ 8,00; não
  inclui depreciação, seguro nem IPVA. O do carro de aplicativo não modela
  tarifa dinâmica nem deslocamento em vazio, e a frota elétrica de aplicativo na
  RMR ainda é pequena — a disponibilidade assumida é otimista.
- A tarifa de R$ 4,10 do anel A é herdada da Etapa 1 e deve ser reverificada
  junto ao Grande Recife antes de qualquer uso real.
- Os 30 pontos têm coordenada do OpenStreetMap, mas continuam sendo um
  **recorte** da rede: não há parada de ônibus em todos (no Marco Zero, por
  exemplo, não há — e por isso, com mobilidade reduzida, o transporte público não
  aparece a partir dali), e o ônibus é modelado como um corredor contínuo
  Olinda–Piedade, quando na prática exige baldeação. Sem GTFS não há como saber
  quais linhas existem.
- Mobilidade reduzida é modelada com caminhada a 3 km/h e no máximo 0,8 km por
  trecho a pé. São parâmetros de produto, não medição.
- Os índices de segurança e a marcação de acessibilidade são *proxies*
  atribuídos por tipo de via, não levantamento de campo.
- Os limiares de viabilidade (120 min / R$ 25 para inviável; 75 min / R$ 12 para
  limítrofe) são juízo de produto, não resultado de algoritmo, e estão
  explicitados na própria aba.
- A disponibilidade de frota compartilhada é tratada como opção binária, não
  como estado consultado em API de operador.
- Os 7 eletropostos **não são dados oficiais**: são posições plausíveis em
  pontos já modelados, para permitir testar a funcionalidade. Tempos e preços de
  recarga (25 min / R$ 26,00 no rápido; 50 min / R$ 22,00 no semirrápido) são
  estimativas. Em produção devem vir de uma base real com disponibilidade.
- A autonomia do veículo elétrico não é modelada: a recarga é uma parada que o
  usuário pede, não uma necessidade calculada a partir de bateria e distância.
- O tempo típico de via é o fluxo livre do OSRM × 1,647 (índice TomTom de
  64,7% para o Recife). Os fatores por cima disso — trânsito livre ×0,75,
  congestionado ×1,45, chuva — são multiplicadores por ordem de grandeza, não
  medições.
