# RSM — Rotas Sustentáveis Multimodais

Leia **`projeto.md`** antes de mexer em qualquer coisa: é o documento de handoff
(arquitetura, decisões, dados, armadilhas, o que falta). `README.md` é a visão
para usuário.

- Backend: Python **só biblioteca padrão** (decisão do projeto). Frontend: HTML/CSS/JS
  puro + Leaflet por CDN.
- Rodar: `python src/server.py` → http://localhost:8000 (técnico em `/admin`).
- Testes: `python -m unittest discover -s tests -v` — rode antes de declarar algo pronto.
- Mudou algo? Atualize `projeto.md` junto com o código.
