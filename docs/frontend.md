# Frontend React

O frontend do Delta Mapas é uma aplicação React + TypeScript servida pelo Vite. Ele consome a API
multitenant em `/api/v1`, mantém a sessão JWT no `sessionStorage` e nunca recebe as credenciais da
Copernicus ou do MinIO.

## Rotas

| Rota | Função |
| --- | --- |
| `/login` | autenticação e restauração da sessão |
| `/` | indicadores de créditos, propriedades, jobs e mapas |
| `/properties` | desenho, edição, importação, lista e visualização MapLibre |
| `/jobs` | acompanhamento do pipeline e dos erros processáveis |
| `/jobs/new` | criação idempotente de um mapa NDVI por propriedade |
| `/maps` | prévia privada, estatísticas e downloads PNG/PDF |
| `/billing` | saldo, preço vigente e ledger auditável |

As rotas internas são protegidas por `ProtectedRoute`. Ao abrir a aplicação com tokens existentes,
o `AuthProvider` valida a identidade em `/auth/me/`. Um `401` tenta uma única renovação coordenada em
`/auth/refresh/`; se ela falhar, a sessão local é descartada. O logout invalida o refresh token no
backend e limpa o cache do TanStack Query.

## Fluxos principais

- propriedades podem ser desenhadas por cliques, receber múltiplos componentes e furos, ter todos
  os anéis ajustados por vértices, ser coladas como `Polygon`/`MultiPolygon` GeoJSON ou importadas
  de um shapefile ZIP;
- componentes e furos são contados na interface e podem ser removidos individualmente; novos furos
  precisam ficar integralmente dentro de um componente e novos polígonos não podem sobrepor os
  existentes;
- a área exibida nunca é calculada no navegador: ela vem da normalização geoespacial do backend;
- o upload usa `multipart/form-data` autenticado e mostra requisitos do conjunto `.shp`, `.shx`,
  `.dbf` e `.prj` antes do envio;
- jobs usam uma chave de idempotência nova por envio, mostram custo e saldo antes da criação e são
  acompanhados por polling;
- previews e downloads são obtidos com `Authorization` e convertidos para URLs `blob`, sem tornar o
  bucket público;
- propriedades, jobs, mapas e ledger usam paginação controlada pelo servidor; busca, filtros e
  ordenação ficam nos query params da URL e sobrevivem à navegação;
- mutações e downloads exibem notificações acessíveis; consultas com falha oferecem retry;
- falhas de rede, respostas `5xx`, expiração da sessão e erros inesperados de renderização possuem
  tratamento centralizado;
- jobs ativos podem ser cancelados após confirmação; jobs terminais podem ser reprocessados com
  confirmação explícita do custo, chave idempotente reutilizável e notificação do novo estado;
- páginas e MapLibre são carregados sob demanda para reduzir o bundle inicial;
- estados de carregamento, ausência de dados e falhas de mutação são apresentados em português.

## Desenvolvimento e verificação

```bash
docker compose up -d frontend
docker compose exec frontend npm run lint
docker compose exec frontend npm run test
docker compose exec frontend npm run build
```

A suíte usa Vitest, jsdom e Testing Library. Ela cobre busca/paginação, notificações globais,
cancelamento/reprocessamento e as operações puras de composição, validação, movimentação e remoção
de anéis geoespaciais.

O proxy de desenvolvimento do Vite encaminha `/api` para o serviço `backend`. A aplicação local fica
em <http://localhost:5173>.

## Limites atuais

- o editor ainda não divide, une ou recorta componentes visualmente;
- a aplicação usa polling, sem WebSocket ou Server-Sent Events;
- o mapa de propriedades usa estilo vetorial vazio para funcionar sem depender de um provedor
  externo de mapa-base.
