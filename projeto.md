# projeto.md — estado do RSM para quem pegar o trabalho

Documento de handoff. Descreve o que existe, por que cada decisão foi tomada, o
que está em aberto e onde mexer. Quem continuar o trabalho deve **atualizar este
arquivo junto com o código** e **rodar os testes antes de declarar algo pronto**.

Última atualização: 2026-09-23 (segurança viária com dado da CTTU, rotas que
evitam vias perigosas, atualização automática a cada minuto).

```bash
python src/server.py                          # app em http://localhost:8000, técnico em /admin
python -m unittest discover -s tests -v       # 18 testes de corretude (~2 min)
python src/geometria.py                       # rebaixa matriz e traçados do OSRM (rede mudou)
python src/seguranca.py                       # rebaixa sinistros da CTTU e comprimentos do OSM
python src/rede_rsm.py                        # |V|, |E| e custo por modal
```

---

## 0. Leia primeiro: o que estava errado e como foi corrigido

A rota recomendada **estava errada**, e o usuário percebeu antes de mim: o carro
saía de Olinda pelo interior (Agamenon → Av. Sul → Imbiribeira) e passava pelo
aeroporto. O roteador real (OSRM) vai por Agamenon → Cruz Cabugá → centro →
Ponte Paulo Guerra → Av. Domingos Ferreira → Visconde de Jequitinhonha → Ayrton
Senna. As causas, em ordem de gravidade:

| # | Causa | Evidência | Correção |
|---|---|---|---|
| 1 | **Pontos posicionados de memória** | Igreja da Sé a ~790 m do real; Estação Tancredo Neves a 3,3 km; uma estação inventada ("Largo da Paz"); Porta Larga e Monte dos Guararapes faltando; Tancredo Neves e Aeroporto em ordem trocada | Estações e igrejas dos nós do OSM (Overpass); pontos de rua tirados dos pontos de manobra da rota real do OSRM |
| 2 | **Velocidade do carro por "classe viária" escolhida à mão** | Eu classifiquei Av. Sul/Imbiribeira como expressa (×1,55); foi isso que puxou a rota para o interior | Carro e carro de app viram **arestas-atalho** com tempo e distância do OSRM (ver §3) |
| 3 | **Descer do carro só em pontos de certos tipos** | "Só carro" até a Praça de Boa Viagem estacionava numa estação de metrô e terminava a pé | Na origem e no destino da consulta sempre se pode pegar/deixar carro, bicicleta ou carro de app |
| 4 | **Variante "parar para recarregar" escolhida por TOPSIS** | Carregava 50 min no eletroposto lento, largava o carro e seguia de metrô: +83 min | A variante é só carro, com a parada que menos atrasa: +25 min, sem desvio |
| 5 | **Mobilidade reduzida caminhava à vontade** | "Menor custo" acessível = estacionar e andar 13 km (2 h 44) | 3 km/h e no máximo 0,8 km por trecho a pé |
| 6 | **Acessibilidade oferecia bicicleta** (regressão minha, da troca de cenários por opções) | Card de bicicleta saindo do Marco Zero com "rota acessível" ligada | `cenario_de` volta a bloquear as duas rodas |
| 7 | **Heurística do A\* podia superestimar** | Com trânsito livre o carro faz 39,1 km/h em linha reta, acima dos 32 km/h do metrô usados como limite | Limite medido no próprio grafo (`velocidade_maxima_reta`) |

Todas estas viraram testes em `tests/test_rotas.py` — se alguma voltar, um teste
falha.

---

## 1. O que é

**RSM — Rotas Sustentáveis Multimodais.** MVP web de recomendação de rotas
multimodais na Região Metropolitana do Recife, sobre as Etapas 1 e 2 de um
trabalho de Análise e Projeto de Complexidade de Algoritmos (Faculdade Nova
Roma). PDFs de origem em `C:\Users\Rafael Diniz\Documents\grafos`.

**Corredor:** Igreja da Sé (Alto da Sé, Olinda) ⇄ Igreja de N. Sra. da Piedade
(Jaboatão). 18,7 km em linha reta, 22,4 km de carro pela via real. Origem e
destino podem ser qualquer um dos 30 pontos.

**Restrição de stack (decisão do usuário):** backend Python **só com biblioteca
padrão**; algoritmos implementados do zero. Frontend HTML/CSS/JS puro, Leaflet
por CDN.

---

## 2. Arquitetura

```
rotas/
├── projeto.md · README.md · prompt-design.md
├── src/
│   ├── rede_rsm.py    pontos, trechos, modais, eletropostos, opções, construção do grafo
│   ├── algoritmos.py  Dijkstra, A*, dominância, Martins, NSGA-II, TOPSIS
│   ├── geometria.py   matriz e traçados do OSRM (tabela + rota), cache em dados/
│   ├── clima.py       condições automáticas: Open-Meteo + trânsito por horário
│   ├── seguranca.py   segurança viária por rua: sinistros da CTTU + comprimento do OSM
│   ├── motor.py       consulta, descrição de rota, cards, viabilidade, serialização
│   └── server.py      HTTP + parsing da query string
├── tests/test_rotas.py
├── dados/
│   ├── matriz_carro.json        OSRM table 30×30: distância e tempo em fluxo livre
│   ├── geometria.json           traçados de carro por par de pontos
│   ├── seguranca_cttu.json      sinistros por rua (CTTU 2022–2024), limiares, ruas de cada trecho
│   ├── estacoes_osm.json        estações do OSM (Overpass) — fonte das coordenadas
│   ├── rota_referencia_steps.json  manobras da rota real Sé→Piedade — fonte dos pontos de rua
│   ├── nearest.json · geocodificacao.json   conferência de pontos
└── web/
    ├── index.html · app.css · app.js      app do usuário (/), design do artifact
    └── admin.html · admin.css · admin.js · tokens.css   análise técnica (/admin)
```

Dependência: `server → motor → {algoritmos, clima, geometria} → rede_rsm`.
`rede_rsm` importa `geometria` de forma tardia (dentro das funções) para quebrar
o ciclo.

### Grafo

`G = (V, E)`, `V ⊆ P × M × F × R`. **O vértice é uma quádrupla**
`(ponto, modo, F, R)`:

| Componente | O quê | Por quê |
|---|---|---|
| `F ∈ {0,1}` | já embarcou em veículo individual? | impede bike própria + bike elétrica na mesma viagem |
| `R ∈ {0,1}` | já recarregou? | só é desdobrado quando a recarga é pedida |

Arestas: `deslocamento` (preserva modo), `transferencia` (preserva ponto),
`recarga` (única que vira R de 0 para 1). Peso vetorial
`[tempo(min), custo(R$), CO₂(g), desconforto]`.

Rede atual: **30 pontos, 44 trechos (10 de metrô), 8 modais** → 228 vértices e
698 arestas com todos os modais; 466/1.577 com recarga.

Regras estruturais (todas testadas):
- **Toda viagem termina a pé** (`motor.nos_destino`), senão a rota não paga
  desembarque nem estacionamento.
- **No máximo um veículo individual** por viagem (bit F).
- **Carro próprio embarca só na origem**; desembarca no destino ou em
  estação/terminal (*park-and-ride*).
- **Na origem e no destino** sempre se pode pegar/deixar carro, bicicleta e
  carro de app, qualquer que seja o tipo do ponto.
- **Micromobilidade compartilhada só no Recife** (regulamentação, Etapa 1).
- Transferência para dentro/fora de veículo só onde a camada do veículo existe
  (evita nós mortos que só incham o grafo).

---

## 3. Como o tempo de cada modal é calculado

| Modal | Distância | Tempo |
|---|---|---|
| **carro, carro de app** | OSRM, via real | OSRM em fluxo livre **× 1,647** × trânsito |
| **ônibus** | OSRM entre pontos consecutivos do corredor | OSRM × 1,647 **× 1,35** (paradas) × trânsito |
| **a pé, bicicletas** | rota real a pé / de bicicleta, **sem mão única** (FOSSGIS; ver abaixo) | distância ÷ velocidade do modal |
| **metrô** | linha reta × 1,05 | ÷ 32 km/h |

**Por que 1,647:** o índice TomTom de congestionamento do Recife (64,7%, Etapa 1)
é definido exatamente como o tempo extra de viagem sobre o fluxo livre. O OSRM dá
fluxo livre (27,8 min no corredor); tempo típico = 27,8 × 1,647 = 45,7 min.
Trânsito livre ×0,75, congestionado ×1,45 por cima disso.

**Carro e carro de app não percorrem os trechos do modelo.** São arestas-atalho
entre os pontos onde uma perna de carro pode começar ou terminar (origem,
destino, estações, terminais e, com recarga, eletropostos), com tempo e
distância da matriz do OSRM. É o desenho dos *transfer graphs* da literatura da
Etapa 1 (Potthoff e Sauer, 2022): a rede de transporte público fica explícita; o
trecho por via é pré-calculado sobre a malha viária completa. Consequência: a
rota de carro **é** a do roteador real, e o teste
`test_carro_segue_o_roteador_real` garante isso.

**A pé e de bicicleta não há mão única** (`geometria.construir_ativos`). O OSRM
público (`router.project-osrm.org`) só tem carro: `/foot/` e `/cycling/`
devolvem rota de automóvel. O **FOSSGIS** (`routing.openstreetmap.de`,
mantenedores do OSM) roda OSRM com os perfis a pé e de bicicleta, sem chave. Por
trecho são 3 consultas: a pé, bike na ida e bike na volta. O cache guarda em
`dados/geometria.json`, nas chaves `u|v|foot` e `u|v|cycling`, o traçado, a
distância e as ruas percorridas (`vias`).

- **Bicicleta = o menor** entre: perfil bike na ida, perfil bike na volta
  (invertido), perfil a pé e rota de carro nos dois sentidos. O perfil bike do
  OSRM já aceita contramão, mas como "empurrando" a 6 km/h, e por isso muitas
  vezes prefere pedalar um contorno. Quem pedala no Recife não contorna
  quarteirão por mão única (pedido do usuário, 2026-09-23). Pina → Ponte Paulo
  Guerra: carro 3,48 km, bike 0,26 km.
- **A pé = o menor** entre o perfil a pé e a rota de carro nos dois sentidos.
- **Por que a rota de carro entra na disputa:** os perfis a pé e de bike do OSRM
  **excluem `highway=trunk`**. No Recife essa classe inclui avenidas urbanas com
  calçada e ciclovia: Agamenon, Av. Sul, Mascarenhas de Moraes. O perfil a pé
  dava 5,4 km de Olinda até a Cruz Cabugá, contra 2,4 km pela Agamenon. Nesses
  casos o traçado é o do carro, com `vias=None`, e a segurança usa as ruas da
  rota de carro.
- O tempo continua vindo da velocidade do modal, não do OSRM.
- Sem esse cache, `distancia_trecho` volta à regra antiga: distância de carro se
  ≤ 1,6× a reta, senão 1,3× a reta.

Para refazer: `python src/geometria.py --so-ativos [--forcar]`.
`test_bike_e_pedestre_nao_contornam_mao_unica` garante que nenhum trecho de bike
fica mais longo que o carro no melhor sentido.

**O +58% de inflação da versão anterior acabou**, por dois motivos: os pontos
agora estão sobre as vias certas (o OSRM não precisa "encaixar" com desvio), e o
carro não soma mais trechos — usa a rota direta.

---

## 4. Condições automáticas (`clima.py`)

O usuário **não** informa clima nem trânsito.

- **Clima:** Open-Meteo, sem chave, cache de 10 min. Classifica em
  `bom`/`chuva_leve`/`chuva_forte` pela **pior** leitura entre código WMO e
  precipitação.
- **Trânsito:** heurística de horário (pico útil 06:30–09:00 e 16:30–19:30).
  **Estimativa**, rotulada como tal. Não existe fonte aberta em tempo real na RMR.
- **Falha de rede:** assume tempo bom e **avisa** (`disponivel: false`).

`motor._recomendar` escolhe o card sugerido e a frase que explica (chuva forte →
menos km expostos; chuva leve/calor ≥31 °C → mais rápida com ≤2 km expostos;
pico → mais rápida sem motorizado; normal → equilibrada). `motor._avisos` gera o
"não é a melhor hora para pedalar" nos cards expostos.

`rede_rsm.Opcoes` (modos, clima, trânsito, segurança, acessível, recarga) é o que
o `/admin` manipula à mão; o app preenche clima e trânsito sozinho.

**Mobilidade reduzida** (`acessivel=True`): remove trechos não acessíveis, remove
as duas rodas, caminhada a **3 km/h** e só em trechos de até **0,8 km**. Do Alto
da Sé só sai de carro/app — a única saída sem carro é a ladeira de
paralelepípedo, não acessível. Isso é o correto, não um defeito.

---

## 4b. Segurança viária (`seguranca.py`)

**Fonte:** CTTU (Autarquia de Trânsito do Recife), conjunto "Chamados de
Sinistros de Trânsito com e sem vítimas" do Portal de Dados Abertos do Recife,
anos **2022–2024**, 12.016 sinistros. A coleta usa a API `datastore_search` do
portal. Só os **agregados por rua** ficam em `dados/seguranca_cttu.json`.

**O que não existe em dado aberto:** criminalidade por rua. O conjunto
"Ocorrências" da Guarda Municipal está no catálogo com **zero arquivos**. O MVP
mede segurança **viária** (atropelamento, sinistro com ciclista), não segurança
pública (assalto). Não apresente uma coisa como se fosse a outra.

**Cobertura:** só o Recife. Trechos em Olinda e Jaboatão ficam **"sem dado"**, e
esse nível nunca é tratado nem exibido como seguro.

**Como a base vira risco por trecho:**
1. Os sinistros são agregados pelo nome da rua, porque a CTTU não publica
   coordenada.
2. O comprimento de cada rua vem do OSM (Overpass, 8.908 ruas nomeadas do
   Recife). **Pista dupla conta uma vez:** um segmento de mão única conta pela
   metade se existe, a menos de 80 m, outro de mesmo nome no sentido oposto.
   Duas tentativas anteriores erravam:
   - somar tudo dava Agamenon = 20 km, com a densidade caindo à metade;
   - usar a maior distância entre pontos dava Agamenon = 5,5 km, porque a
     avenida é um arco.
3. Densidade = sinistros com pedestre (ou com ciclista) ÷ km ÷ ano. Em rua
   curta, o comprimento usado é de **no mínimo 0,5 km**
   (`KM_MINIMO_DENSIDADE`), para 1 sinistro em 100 m não virar a rua mais
   perigosa da cidade. Antes, rua curta ficava sem densidade, e a rota real do
   pedestre, que passa por ruas pequenas, caía em "sem dado".
4. **Poucos eventos não bloqueiam** (`MIN_SINISTROS_PARA_BLOQUEAR = 5`). Uma rua
   com menos de 5 sinistros daquele tipo de usuário no período entra com a
   densidade limitada logo abaixo do P90. Ela pode gerar "atenção", mas nunca
   "inseguro" sozinha. Sem essa regra, a Ponte Paulo Guerra (3 sinistros com
   ciclista em 260 m) cortava a única ligação de bike do centro com Boa Viagem,
   e o card "menor emissão" virava 4 h de caminhada.
5. As ruas de cada trecho são as da **rota daquele modo**: para quem anda, a
   rota a pé; para quem pedala, a de bike (`geometria.item_ativo(...)["vias"]`).
   Sem ela, entram as ruas da rota de carro (`trechos` no JSON).
   **A orla é exceção.** Ali quem anda ou pedala está
   no calçadão da Av. Boa Viagem, enquanto o carro sai pela Domingos Ferreira;
   por isso as ruas são declaradas em `VIAS_A_PE_DECLARADAS`. Sem essa exceção,
   a orla herdaria os sinistros justamente da via perigosa que ela ajuda a
   evitar.
6. Os nomes são casados primeiro de forma exata. Se falhar, compara sem o tipo
   da via ("RUA Visconde de Jequitinhonha" na CTTU é "Avenida" no OSM).
7. Risco do trecho = média ponderada por km. O trecho só é julgado se ≥ 50% dele
   tem dado. Uma rua do Recife **sem nenhum sinistro registrado** também conta
   como sem dado, porque o JSON só guarda ruas que aparecem na CTTU. Guardar a
   lista de ruas do OSM permitiria contá-la como 0; ainda não foi feito.
8. A rua citada no aviso é a que mais pesa no veredito (km × densidade),
   priorizando as que têm ≥ 5 sinistros, e não a de maior densidade.

**Níveis** (limiares da **cidade**, calculados sobre as arteriais do Recife com
≥ 1 km):

| Nível | Pedestre | Ciclista | Efeito |
|---|---|---|---|
| inseguro (P90) | ≥ 0,623 /km/ano | ≥ 0,562 | o trecho **sai do grafo** para quem anda ou pedala |
| atenção (P75) | ≥ 0,407 | ≥ 0,301 | permitido, com aviso no passo a passo |
| sem dado | — | — | dito explicitamente |

Ônibus e carro não são cortados. Quem está dentro do veículo não é o usuário
exposto que esses sinistros medem.

Hoje são inseguros, a pé: Agamenon, Cruz Cabugá e Dantas Barreto (trecho Santo
Antônio → Estação Recife). De bicicleta, nenhum trecho é inseguro. Ficam em
atenção a Agamenon, a Cruz Cabugá, a Rua do Hospício, a Ponte Paulo Guerra e a
Domingos Ferreira; esta última está a 2% do limiar para pedestre. O nível
intermediário existe por casos como esse.

**Como o desvio é explicado** (`motor._evitados`): `opcoes_de_viagem` calcula a
fronteira duas vezes, com e sem o filtro. Para cada perfil, se a escolha sem
filtro passava por trecho inseguro, o card recebe um aviso no critério daquele
card:
*"Não te mandamos a pé pela Avenida Dantas Barreto: 10 sinistros com pedestre em
2022–2024 (CTTU), entre as 10% vias mais perigosas do Recife para quem anda. A
alternativa segura (Carro elétrico) custa +R$ 6,43 e leva 17 min a menos."*

Na varredura, 23 dos 870 pares têm algo evitado, sempre a Dantas Barreto a pé. O par Sé → Piedade não tem
nenhum. `evitar_inseguros=0` na API desliga o filtro (para comparação no
`/admin`).

## 4c. Atualização automática

O app reconsulta `/api/opcoes` **a cada 60 s**, e só com a aba visível. Ao voltar
para a aba, reconsulta se já passou mais de um minuto. A atualização não mostra
spinner e não mexe no mapa. Ela **mantém a opção escolhida**, identificada por
resumo + modais e não por índice, porque a ordem dos cards pode mudar. O mesmo
vale para o interruptor de recarga. Se a sugestão mudar, o texto começa com "A
sugestão mudou." Se a opção escolhida deixar de existir, a seleção volta para a
sugerida.

O clima tem cache de 5 min no servidor. O Open-Meteo só atualiza o dado corrente
a cada 15 min, então buscar com mais frequência é desperdício. O trânsito é
estimado por horário e só muda na virada de faixa.

---

## 5. Cards do app (`motor.opcoes_de_viagem`)

1. Uma fronteira de Pareto (Martins) sobre o grafo com clima/trânsito medidos.
2. **Cards extremos = mínimo exato do objetivo na fronteira** (mais rápida, menor
   custo, menor emissão, menos esforço). Só "equilibrada" usa TOPSIS. O rótulo
   promete "mais rápida"; tem de ser literalmente a de menor tempo — o TOPSIS com
   peso 0,70 já devolveu uma 0,5 min mais lenta.
3. Perfis que caem na mesma rota viram **um** card com várias etiquetas.
4. **Variante de recarga** (cards com carro próprio): grafo só `{pe, carro}` com
   recarga obrigatória, Dijkstra lexicográfico (tempo, depois o resto). Promete
   "a mesma viagem com uma parada"; o teste
   `test_variante_recarga_e_a_mesma_viagem_de_carro` garante que não vira outra.
5. Traçado real buscado ao vivo **só para os cards**, no máximo 6 por consulta
   (`MAX_TRACADOS_AO_VIVO`), gravado no cache.

Resultado atual Sé → Piedade, tempo bom, trânsito normal:

| Card | Tempo | Custo | Etiquetas |
|---|---|---|---|
| Carro elétrico | 53 min | R$ 13,59 | recomendado, equilibrada |
| Carro de app | 52 min | R$ 48,52 | mais rápida, menos esforço |
| Bicicleta | 1 h 38 | R$ 0,00 | menor custo, menor emissão |

Recarga no card do carro: **+25 min, +R$ 26,00** (Eletroposto Visconde de
Jequitinhonha, rápido, sobre a rota — o acréscimo é só a carga, sem desvio).

---

## 6. Algoritmos (`algoritmos.py`)

| Função | Complexidade |
|---|---|
| `dijkstra` | O(E log V) |
| `a_estrela` | O(E log V) pior caso |
| `martins` | O(N log N + N·d·k) |
| `nsga2` | O(G·P²·d) |
| `topsis` | O(k·d) |

- **Heurística do A\*:** `velocidade_maxima_reta(g)` mede a maior velocidade em
  linha reta de qualquer aresta; h = reta ÷ esse limite. Admissível e
  consistente por construção. Usar a velocidade nominal do metrô (32 km/h) é
  inadmissível com trânsito livre (carro a 39,1 km/h em linha reta).
- **`escalarizar`** divide por `ESCALAS = (90 min, R$ 40, 2000 g, 25)`. Se o
  corredor mudar, revise.
- **TOPSIS** tem `minmax` (padrão) e `vetorial` (clássica da Etapa 2, expõe o
  efeito da dispersão).
- **Bug herdado da Etapa 2 (§4.5), corrigido:** o cruzamento do NSGA-II truncava
  a lista na remoção de ciclos sem atualizar os visitados → `ValueError`. O código
  original do relatório tem o mesmo defeito latente.

---

## 7. Testes (`tests/test_rotas.py`)

18 testes, stdlib `unittest`, ~2 min. Cada um verifica uma **propriedade** que tem
de valer, não um número copiado da saída:

| Teste | Garante |
|---|---|
| `test_a_estrela_iguala_dijkstra` | mesmo custo ótimo, 6 pares × 3 trânsitos × 5 perfis |
| `test_heuristica_nunca_superestima` | h(n) ≤ custo real até o destino, vértice a vértice |
| `test_martins_contem_os_otimos_de_cada_objetivo` | a fronteira contém o ótimo de cada objetivo isolado |
| `test_fronteira_sem_rota_dominada` | nenhuma rota da fronteira domina outra |
| `test_no_maximo_um_veiculo_individual` | bit F funciona |
| `test_toda_rota_termina_a_pe` | ninguém "termina dentro do carro" |
| `test_carro_proprio_so_embarca_na_origem` | — |
| `test_recarga_obrigatoria_passa_por_eletroposto` | bit R funciona |
| `test_mobilidade_reduzida_nao_caminha_longe` | sem caminhada longa nem duas rodas |
| `test_carro_segue_o_roteador_real` | só-carro = rota direta do OSRM (distância e tempo) |
| `test_nenhum_ponto_longe_da_via` | estações e igrejas a < 50 m do OSM |
| `test_card_extremo_e_o_minimo_da_fronteira` | "mais rápida" é a mais rápida etc. |
| `test_variante_recarga_e_a_mesma_viagem_de_carro` | só carro, uma parada, +≥25 min |
| `test_ninguem_anda_ou_pedala_em_via_insegura` | **nos 870 pares**, nenhuma perna a pé ou de duas rodas em trecho inseguro |
| `test_aviso_so_quando_a_rota_evitada_era_mesmo_insegura` | aviso verdadeiro e com o nome da via |
| `test_caso_real_dantas_barreto` | Imbiribeira → Recife Antigo avisa a Dantas Barreto |
| `test_bike_e_pedestre_nao_contornam_mao_unica` | Pina ↔ Ponte PG < 0,5 km a pé e de bike; nenhum trecho de bike maior que o carro |
| `test_sem_dado_nao_e_seguro` | trecho em Olinda = "sem dado", nunca "ok" |

Varredura completa feita uma vez (não está na suíte por tempo): **870 pares ×
3 trânsitos, A\* = Dijkstra em todos; Martins contém o ótimo em 60 pares × 4
objetivos; 0 pares sem rota; 0 pares sem rota no modo acessível.** Só-carro
diverge da rota direta em 14 pares — todos trechos curtos onde andar vence o
carro (ex.: Pina → Ponte Paulo Guerra, 260 m a pé contra 3,5 km de carro por
mão única). É o roteador acertando.

---

## 8. API

Parâmetros comuns: `origem`, `destino`, `perfil`, `modos`, `clima`, `transito`,
`seguranca`, `acessivel`, `recarga`. `/api/opcoes` aceita também
`evitar_inseguros` (padrão 1) e devolve `evitados`, `seguranca_fonte`,
`gerado_em` e, em cada card, `seguranca` e `evitou`.

| Rota | Uso |
|---|---|
| `GET /api/opcoes` | app: condições + cards + recomendado e motivo |
| `GET /api/condicoes-atuais` | clima e trânsito correntes |
| `GET /api/rede` | pontos, trechos, modais, eletropostos, opções |
| `GET /api/rota` | admin: Dijkstra, A\*, fronteira, TOPSIS, contraprova do metrô |
| `GET /api/condicoes` | admin: varia uma dimensão por vez |
| `GET /api/viabilidade` | admin: cada modal isolado |
| `GET /api/nsga2` | admin: Martins × NSGA-II |

---

## 9. Interface

**`/`** — design do artifact `https://claude.ai/artifact/6GbHjBDz9TsGkrBF8vaR98`
ligado à API real: mapa em tela cheia, painel flutuante (folha arrastável no
celular), opções em linhas com glifo, preço, horário de chegada e barra de
composição modal; interruptor de recarga no card do carro; escuro por padrão.
Diferenças deliberadas em relação ao artifact: os botões de demonstração
"bom/chuva" saíram (as condições são reais); "Tela técnica" aponta para `/admin`;
a acessibilidade **recalcula no servidor** em vez de só reordenar no navegador.

**`/admin`** — tela técnica anterior (Pareto, Dijkstra × A\*, viabilidade,
condições, NSGA-II), com `tokens.css` + `admin.css`.

---

## 10. O que falta

- **Não há dado aberto de segurança pública (assalto, roubo) por rua na RMR.**
  Caminhos possíveis: a API do Fogo Cruzado (tiroteios geolocalizados no Grande
  Recife; exige cadastro, então o usuário cria a conta e fornece a chave) ou um
  pedido de acesso à SDS-PE. Nenhum dos dois foi feito.
- **Risco por turno:** a CTTU registra a hora de cada sinistro. Daria para ter
  risco noturno, e a atualização por minuto mudaria a rota ao anoitecer. Não foi
  feito porque, separando por rua e por turno, a amostra fica pequena.
- **Olinda e Jaboatão não têm dado de segurança**, porque a CTTU só cobre o
  Recife.

- **Parada de ônibus em alguns pontos** (Marco Zero, orla): para mobilidade
  reduzida, o transporte público não aparece a partir deles. Falta de dado na
  rede, não erro de algoritmo.
- **Ônibus é corredor contínuo** Olinda–Piedade. Sem GTFS não dá para saber quais
  linhas existem; na prática exige baldeação.
- **Transporte público nunca ganha card** neste par com todos os modais: carro
  ganha tempo/esforço, bicicleta ganha custo/emissão. O arranjo
  ônibus/bicicleta + metrô está na fronteira (visível no `/admin`) mas não é
  extremo de nenhum objetivo. Decisão de produto em aberto.
- Eletropostos e acessibilidade são *proxies*. O índice de segurança por modal
  (`seguranca` na API, usado no custo de desconforto) também é *proxy*. O
  **filtro** de vias perigosas usa dado real (seção 4b).
- Tarifa de R$ 4,10 herdada da Etapa 1, a reverificar.
- Autonomia do carro elétrico não é modelada.
- Rotas a pé e de bike vêm do FOSSGIS, que exclui `trunk`. Onde a rota de carro
  foi usada no lugar, o traçado pode incluir um trecho de mão única que o
  pedestre faria pelo outro lado da avenida. Um OSRM próprio com perfil ajustado
  para o Brasil (`trunk` com calçada) resolveria.
- **A contramão de bicicleta é infração** (CTB art. 58), salvo onde houver
  sinalização. O app segue o comportamento real, que foi o pedido do usuário, mas
  não avisa trecho a trecho. Um próximo passo seria marcar no passo a passo onde
  a rota escolhida vai contra o fluxo.

---

## 11. Armadilhas

1. **O vértice é uma quádrupla**; o código indexa `[0]` e `[1]`. Não desempacote
   como par.
2. **Mudou pontos? Rode `python src/geometria.py`.** A matriz é indexada por id; um
   ponto movido sem refazer a matriz carrega tempo de carro do lugar antigo.
3. **Não rode duas builds de `geometria.py` ao mesmo tempo** — cada uma regrava o
   arquivo inteiro e o último vence.
4. **`polilinha` devolve cópia.** Devolver a lista do cache deixava `extend()`
   mutá-lo (uma rota chegou a 200 mil pontos).
5. **Não coloque coordenada de memória.** Foi a origem da rota errada.
   Estação/igreja: Overpass. Ponto de rua: manobra do OSRM ou `nearest` conferido
   pelo nome da via.
6. **Não volte a dar velocidade por classe viária escolhida à mão** para
   motorizado. Tempo de via vem do roteador.
7. **Reinicie o servidor depois de mexer em `.py`**; `web/` é `no-store`.
8. **Martins:** 2–8 mil rótulos, 40–340 ms; salvaguarda `max_rotulos=400_000`.
9. **O portal da CTTU devolve no máximo 500 registros por página**, qualquer
   que seja o `limit`. A primeira versão avançava de 5.000 em 5.000 e pulou 90%
   dos sinistros. `_registros` avança pelo que veio e falha se o total não bater.
10. **"Sem dado" não é "seguro".** Não troque `sem_dado` por `ok` para simplificar
    a interface.
11. **`python src/seguranca.py` reaproveita as ruas de cada trecho** (salvas no
    JSON). Se a rede mudou, rode com `--refazer-trechos`.
12. **Pista dupla**: se mexer no cálculo de comprimento, confira a Agamenon
    (~12,8 km). Com 20 km a densidade cai à metade e ela deixa de ser insegura.
