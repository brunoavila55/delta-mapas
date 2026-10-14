# Delta Mapas

Aplicação de mapas agrícolas em **Rust/Axum e PostgreSQL/PostGIS**. Permite cadastrar
propriedades e talhões, importar CAR ou GeoJSON, solicitar NDVI e baixar resultados.

## Funcionalidades

- Contas individuais, sessões persistentes e dados isolados por usuário.
- Importação de ZIP do CAR e GeoJSON; o CAR representa o limite do imóvel inteiro.
- Análises Sentinel-2 via Copernicus, com fila, histórico e controle de uso.
- Exportação GeoTIFF, PNG e JSON; mapa cartográfico PDF separado e relatório com mapa embutido.
- Mapas em SIRGAS 2000/UTM, com logo Delta Mapas, escala, norte geográfico, quadrícula e coordenadas.
- Demonstração com dados sintéticos, sem credenciais de satélite.
- Acompanhamento semanal por talhão e alertas de queda de NDVI dentro da aplicação.

A interface usa React e TypeScript, compilados pelo Vite e servidos pelo backend Rust.
Recuperação de senha e cobrança ainda estão pendentes.

## Executar localmente

```sh
python3 scripts/setup-dev.py
docker compose up -d --build
```

Abra **http://127.0.0.1:3010**. O script cria `.env` sem substituir configurações
existentes; o Compose inicia banco, migrations, servidor e worker.

Para análises reais, configure `COPERNICUS_CLIENT_ID` e `COPERNICUS_CLIENT_SECRET`
no `.env` e recrie os serviços:

```sh
docker compose up -d --no-deps --force-recreate app worker
```

## Verificar

```sh
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
scripts/test-saas.sh
```

O último comando exige PostgreSQL/PostGIS e usa um banco temporário isolado.
O GitHub Actions também executa essas verificações e uma demonstração em container.

## Produção e documentação

O `compose.prod.yml` prepara servidor, worker, banco e HTTPS com Caddy. Configure
`.env.prod` a partir de `.env.prod.example`; a implantação OCI ainda está pendente.

- [Guia técnico e operação](docs/GUIA-TECNICO.md)
- [Arquitetura e próximas entregas](MVP-e-arquitetura.md)
- [Verificação e limites](VERIFICACAO.md)

## Interface React

O frontend usa React, TypeScript e Vite. O código editável fica em `frontend/src/`.
Os arquivos de produção em `src/ui/` são gerados e embutidos no binário Rust;
eles permanecem no repositório para permitir `cargo build` sem Node instalado.
Depois de alterar o frontend, gere novamente esses arquivos:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
```

O Docker compila a interface automaticamente em uma etapa Node e incorpora o
resultado no build Rust. Em desenvolvimento, com o backend em `127.0.0.1:3010`:

```sh
npm run dev --prefix frontend
```

O Vite encaminha `/api` ao backend local, inclusive a origem das requisições.
Esse proxy é exclusivo de desenvolvimento. Em produção, a interface e as APIs
são servidas pela mesma origem e mantêm cookies, CSRF e CSP existentes.

Para verificar os fluxos e os layouts no navegador:

```sh
cd frontend
npx playwright install chromium
npm test
```

Os testes de interface usam respostas controladas no formato das APIs para
verificar autenticação, importação, edição, idempotência, estados e exportações.
Os testes SaaS existentes continuam verificando o backend real com PostGIS.

## Acompanhamento automático

Em **Talhões → Ativar acompanhamento**, informe cultura, fase atual, início/fim da safra e
queda mínima absoluta de NDVI (padrão 0,15). O worker verifica agendamentos a cada
minuto e solicita uma análise semanal da janela dos últimos sete dias completos
em UTC, limitada ao período da safra. A seleção continua sendo a cena com menos
nuvens, com desempate pela mais recente; a atualização depende de imagens utilizáveis.

Cada análise bem-sucedida consome um crédito da franquia existente. Sem saldo,
o agendador aguarda e verifica novamente em uma hora. Falhas liberam a reserva.
O acompanhamento exige ativação explícita por talhão. Desativar impede novos pedidos;
trabalhos já enfileirados continuam e podem consumir crédito. Salvar configurações
inicia uma nova sequência de comparação.

Os alertas comparam a média do NDVI de duas observações automáticas com datas
distintas, até 30 dias de intervalo, pelo menos 90% de cobertura válida e a mesma
geometria/configuração de safra. Dados sintéticos não geram alertas. Alterar o talhão
ou a configuração reinicia a base de comparação. A fase é informada pelo usuário: na maturação e colheita os mapas continuam, mas
os alertas de queda ficam suspensos. A cultura fica registrada como contexto; não há
modelo de fenologia ou diagnóstico agronômico automático.
Os alertas aparecem na aplicação e podem ser marcados como conferidos.

## Mapas e relatórios

Novas análises geram **Mapa cartográfico PDF** (`map.pdf`), uma prancha A4 paisagem,
e **Relatório PDF** (`report.pdf`), com síntese A4 retrato e a mesma prancha na segunda
página. O mapa inclui logo Delta Mapas, contorno vetorial (com partes e furos),
quadrícula UTM em metros, centroide em graus decimais, fuso/EPSG, norte geográfico,
escala gráfica e numérica, fonte/data da observação e legenda de NDVI. A escala
numérica pressupõe impressão da página A4 a 100%; a escala gráfica acompanha o mapa.

O texto caracteriza a área cadastrada e os dados observados, com qualidade, estatísticas
e distribuição por faixas de NDVI na grade original. Cultura/fase aparecem quando
informadas no acompanhamento. Não há consulta externa de município, solo ou clima.
Nomes de propriedade/talhão e contexto são preservados no pedido (migration 0004).
Nomes extensos são abreviados nos quadros para manter a diagramação.

O PNG continua sendo a imagem simples do índice, e o GeoTIFF mantém georreferenciamento.
Produtos históricos permanecem intactos; o botão do mapa cartográfico aparece somente
quando a análise possui esse produto nos metadados. Uma nova análise gera o novo layout.
As fontes Liberation Sans são incorporadas ao PDF, com licença SIL OFL em `src/assets/fonts`.
