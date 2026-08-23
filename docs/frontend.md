# Interface web Django + HTMX

A interface do Delta Mapas é renderizada pelo Django e não possui bundle, Node.js, React ou
TypeScript. Templates, CSS e JavaScript progressivo vivem em `backend/apps/web`; o HTMX é carregado
de forma declarativa para atualizar somente as regiões necessárias.

## Sessão e autorização

O navegador usa sessão Django e CSRF. O login valida uma `Membership` ativa no tenant resolvido pelo
hostname e limita tentativas por IP e por conta. Perfis `VIEWER` podem consultar todas as telas, mas
as views de criação, edição, cancelamento e reprocessamento recusam mutações.

Não existe uma API pública paralela. Toda autenticação e operação do produto passam pela sessão e
pelos formulários Django protegidos por CSRF.

## Rotas

| Rota | Função |
| --- | --- |
| `/login/` | autenticação por sessão |
| `/` | visão geral da operação |
| `/properties/` | inventário, busca e ordenação de propriedades |
| `/properties/new/` | cadastro por shapefile ZIP ou GeoJSON |
| `/jobs/` | pipeline com filtros e atualização automática |
| `/jobs/new/` | nova solicitação NDVI |
| `/maps/` | biblioteca de mapas e downloads privados |
| `/billing/` | saldo, preço e ledger |

## Uso do HTMX

- busca, filtros, ordenação e paginação substituem somente a região de resultados e mantêm os query
  params na URL;
- a lista de jobs se atualiza a cada cinco segundos enquanto houver itens ativos na página;
- cancelamento substitui apenas a linha afetada;
- exclusão de propriedade remove o card após confirmação;
- respostas de sessão expirada enviam `HX-Redirect` para evitar que a tela de login seja inserida em
  um fragmento.

Toda mutação continua sendo um formulário HTML válido com `{% csrf_token %}` e funciona sem depender
de estado armazenado no navegador. Downloads passam por uma view autenticada e o bucket MinIO
permanece privado.

## Arquivos principais

```text
backend/apps/web/
├── access.py
├── forms.py
├── urls.py
├── views/
│   ├── auth.py
│   ├── billing.py
│   ├── jobs.py
│   ├── maps.py
│   └── properties.py
├── templates/web/
│   ├── base.html
│   └── partials/
└── static/web/
    ├── css/app.css
    └── js/app.js
```

## Desenvolvimento e verificação

```bash
docker compose up --build
docker compose exec backend python manage.py check
docker compose exec backend pytest
docker compose exec backend python manage.py collectstatic --noinput
```

A interface local fica em <http://localhost:8000/>. Não existe serviço separado na porta 5173 nem
etapa de build de frontend.
